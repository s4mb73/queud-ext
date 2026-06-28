"""Scalable headless Playwright tmpt solver with worker pool and session cache."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from rugby_sa.cookies import apply_cookie_jar, has_cookie
from rugby_sa.log_util import log, warn
from rugby_sa.proxy import parse_proxy
from rugby_sa.settings import Settings

_POOL: HeadlessTmptPool | None = None
_POOL_LOCK = threading.Lock()

EPSF_TITLE = "Let's Get Your Identity Verified"
EVENT_MARKERS = ("ism-module", "Event Information Screen")


@dataclass(frozen=True)
class TmptSolveResult:
    cookies: tuple[dict[str, str], ...]
    proxy_line: str
    page_url: str
    final_url: str
    solved_at: float
    has_tmpt: bool
    has_abck: bool
    passed_epsf: bool

    @property
    def cache_key(self) -> str:
        return _cache_key(self.proxy_line, self.page_url)


def _cache_key(proxy_line: str, page_url: str) -> str:
    host = urlparse(page_url).hostname or ""
    proxy = proxy_line.strip() or "direct"
    return hashlib.sha256(f"{host}|{proxy}".encode()).hexdigest()[:24]


def playwright_proxy(proxy_line: str) -> dict[str, str] | None:
    if not proxy_line.strip():
        return None
    parts = proxy_line.strip().split(":")
    if len(parts) < 4:
        raise ValueError(f"Invalid proxy line: {proxy_line!r}")
    return {
        "server": f"http://{parts[0]}:{parts[1]}",
        "username": ":".join(parts[2:-1]),
        "password": parts[-1],
    }


def _cookie_list(context) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for cookie in context.cookies():
        items.append(
            {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain") or "",
                "path": cookie.get("path") or "/",
            }
        )
    return items


def _passed_epsf(html: str, url: str) -> bool:
    if any(marker in html for marker in EVENT_MARKERS):
        return True
    if EPSF_TITLE in html:
        return False
    if "web-identity" in url or "login.sarugby" in url:
        return True
    return "queue-it" not in url.lower()


class HeadlessTmptSolver:
    """Solve tmpt + Akamai cookies in ephemeral headless Chromium."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def solve(self, page_url: str, proxy_line: str = "") -> TmptSolveResult:
        worker_dir = self._worker_dir()
        hostname = urlparse(self.settings.base_url).hostname or ""
        proxy_cfg = playwright_proxy(proxy_line) if proxy_line else None
        if proxy_line:
            host, _, _ = parse_proxy(proxy_line)
            session_id = proxy_line.split("-session-", 1)[-1].split(":", 1)[0]
            log(f"[headless] ZA proxy {host} (session {session_id[:12]}...)")
        else:
            log("[headless] direct connection")

        final_url = page_url
        html = ""
        cookies: list[dict[str, str]] = []

        with sync_playwright() as p:
            browser = None
            context = None
            use_profile = (
                self.settings.tmpt_headless_use_profile
                and self.settings.profile_dir.exists()
            )
            if use_profile:
                log(f"[headless] using profile {self.settings.profile_dir}")
                for channel in ("chrome", None):
                    try:
                        kwargs: dict[str, Any] = {
                            "user_data_dir": str(self.settings.profile_dir),
                            "headless": True,
                            "viewport": {"width": 1400, "height": 900},
                            "locale": "en-GB",
                            "proxy": proxy_cfg,
                            "args": ["--disable-blink-features=AutomationControlled"],
                        }
                        if channel:
                            kwargs["channel"] = channel
                        context = p.chromium.launch_persistent_context(**kwargs)
                        break
                    except Exception as exc:
                        log(f"[headless] profile launch failed ({channel}): {exc}")
            if context is None:
                for channel in ("chrome", None):
                    try:
                        launch_kwargs: dict[str, Any] = {
                            "headless": True,
                            "args": ["--disable-blink-features=AutomationControlled"],
                        }
                        if channel:
                            launch_kwargs["channel"] = channel
                        browser = p.chromium.launch(**launch_kwargs)
                        break
                    except Exception as exc:
                        log(f"[headless] launch failed ({channel}): {exc}")
                if browser is None:
                    browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1400, "height": 900},
                    locale="en-GB",
                    proxy=proxy_cfg,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
            page = context.pages[0] if context.pages else context.new_page()
            log(f"[headless] opening {page_url[:90]}")
            page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)

            reloaded_after_tmpt = False
            deadline = time.time() + self.settings.tmpt_headless_timeout
            while time.time() < deadline:
                try:
                    html = page.content()
                    final_url = page.url
                    title = page.title()
                except Exception:
                    break

                if "queue-it" in final_url.lower() or title == "Queue-it":
                    log("[headless] Queue-it — waiting...")
                    time.sleep(self.settings.queue_wait_seconds)
                    continue

                names = {c["name"] for c in context.cookies()}
                if "tmpt" in names and not reloaded_after_tmpt:
                    log("[headless] tmpt set — reloading event page...")
                    page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)
                    reloaded_after_tmpt = True
                    time.sleep(2)
                    continue

                if _passed_epsf(html, final_url) and "tmpt" in names:
                    cookies = _cookie_list(context)
                    break

                if EPSF_TITLE in html:
                    time.sleep(2)
                    continue

                time.sleep(1.5)

            cookies = _cookie_list(context) if not cookies else cookies
            context.close()

        shutil.rmtree(worker_dir, ignore_errors=True)

        names = {c["name"] for c in cookies}
        result = TmptSolveResult(
            cookies=tuple(cookies),
            proxy_line=proxy_line,
            page_url=page_url,
            final_url=final_url,
            solved_at=time.time(),
            has_tmpt="tmpt" in names,
            has_abck="_abck" in names,
            passed_epsf=_passed_epsf(html, final_url),
        )
        if not result.has_tmpt:
            raise RuntimeError(
                f"Headless tmpt solve failed — no tmpt (url={final_url[:100]})"
            )
        if not result.passed_epsf:
            warn(
                f"[headless] tmpt acquired but EPSF not cleared "
                f"(url={final_url[:80]}) — cookies may not replay over HTTP"
            )
        else:
            log(
                f"[headless] tmpt OK — abck={result.has_abck} "
                f"epsf_passed={result.passed_epsf} cookies={len(cookies)}"
            )
        return result

    def _worker_dir(self) -> Path:
        root = self.settings.tmpt_workers_dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"worker-{uuid.uuid4().hex[:10]}"
        path.mkdir(parents=True, exist_ok=True)
        return path


class HeadlessTmptPool:
    """Thread-pooled headless solver with TTL cache and in-flight deduplication."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, TmptSolveResult] = {}
        self._inflight: dict[str, Future[TmptSolveResult]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=settings.tmpt_pool_workers,
            thread_name_prefix="tmpt-worker",
        )
        self._solver = HeadlessTmptSolver(settings)

    def _fresh(self, result: TmptSolveResult) -> bool:
        return (time.time() - result.solved_at) < self.settings.tmpt_pool_cache_ttl

    def acquire(self, page_url: str, proxy_line: str = "") -> TmptSolveResult:
        key = _cache_key(proxy_line, page_url)
        with self._lock:
            cached = self._cache.get(key)
            if cached and self._fresh(cached):
                log(f"[headless-pool] cache hit ({key[:8]})")
                return cached
            inflight = self._inflight.get(key)

        if inflight is not None:
            log(f"[headless-pool] waiting on in-flight solve ({key[:8]})")
            return inflight.result(timeout=self.settings.tmpt_headless_timeout + 60)

        fut = self._executor.submit(self._solver.solve, page_url, proxy_line)
        with self._lock:
            self._inflight[key] = fut

        try:
            result = fut.result(timeout=self.settings.tmpt_headless_timeout + 60)
        finally:
            with self._lock:
                self._inflight.pop(key, None)

        with self._lock:
            self._cache[key] = result
        return result

    def warm(self, page_url: str, proxy_lines: list[str]) -> int:
        """Pre-solve sessions for multiple proxies (parallel)."""
        if not proxy_lines:
            proxy_lines = [""]
        futures = [
            self._executor.submit(self._solver.solve, page_url, proxy)
            for proxy in proxy_lines
        ]
        ok = 0
        for fut in futures:
            try:
                result = fut.result(timeout=self.settings.tmpt_headless_timeout + 60)
                with self._lock:
                    self._cache[result.cache_key] = result
                ok += 1
            except Exception as exc:
                warn(f"[headless-pool] warm failed: {exc}")
        log(f"[headless-pool] warmed {ok}/{len(proxy_lines)} sessions")
        return ok

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def get_tmpt_pool(settings: Settings) -> HeadlessTmptPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = HeadlessTmptPool(settings)
        return _POOL


def shutdown_tmpt_pool() -> None:
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.shutdown()
            _POOL = None


def apply_headless_cookies(client: Any, result: TmptSolveResult) -> None:
    apply_cookie_jar(
        client.session,
        list(result.cookies),
        include_akamai=True,
    )
    host = client.hostname
    if not has_cookie(client.session, "tmpt", host):
        warn("Headless cookies applied but tmpt not visible on HTTP session")


def refresh_tmpt_headless(client: Any, page_url: str, *, use_pool: bool = True) -> None:
    settings = client.settings
    if use_pool:
        result = get_tmpt_pool(settings).acquire(page_url, client.proxy_line)
    else:
        result = HeadlessTmptSolver(settings).solve(page_url, client.proxy_line)
    apply_headless_cookies(client, result)
    log("tmpt acquired (headless)")