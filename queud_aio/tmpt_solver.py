#!/usr/bin/env python3
"""Hybrid tmpt solver for Ticketmaster EPSF sites.

tmpt requires a reCAPTCHA Enterprise v3 action token posted to /epsf/gec/v3/{page}.
Google's enterprise reload endpoint now expects application/x-protobuffer, so the
token is obtained via headless grecaptcha.enterprise.execute() (not anchor/reload HTTP).

Flow:
  1. Seed EPSF session (event page, eps-mgr, eps/log) over wreq
  2. Headless Playwright: grecaptcha.enterprise.execute(action)
  3. POST token to /epsf/gec/v3/{action} via wreq
  4. tmpt cookie is set on the HTTP session
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from typing import Any
from urllib.parse import urlparse

DEFAULT_SITE_KEY = "6LcvL3UrAAAAAO_9u8Seiuf-I6F_tP_jSS-zndXV"
DEFAULT_ACTION = "Event"
REQUEST_TIMEOUT = int(os.environ.get("SPRINGBOKS_TIMEOUT_SEC", "60"))


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [tmpt] {msg}", flush=True)


def _has_tmpt(session: Any, hostname: str = "") -> bool:
    host = hostname.lstrip(".")
    for cookie in session.cookies.jar:
        if cookie.name != "tmpt":
            continue
        if not host:
            return True
        cookie_host = (cookie.domain or "").lstrip(".")
        if cookie_host == host or host.endswith(cookie_host):
            return True
    return False


def _recaptcha_token_playwright(
    page_url: str,
    site_key: str,
    action: str,
    proxy_line: str = "",
    timeout_s: int = REQUEST_TIMEOUT,
) -> str:
    """Obtain enterprise v3 token via grecaptcha.enterprise.execute()."""
    from playwright.sync_api import sync_playwright

    from queud_aio.headless_tmpt import playwright_proxy

    proxy_cfg = playwright_proxy(proxy_line) if proxy_line else None
    timeout_ms = timeout_s * 1000

    with sync_playwright() as p:
        browser = None
        context = None
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
            except Exception:
                continue
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
        page = context.new_page()
        origin_url = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}/"
        page.goto(origin_url, wait_until="domcontentloaded", timeout=timeout_ms)
        token = None
        last_err: Exception | None = None
        for _ in range(3):
            try:
                token = page.evaluate(
                    """async ({siteKey, action}) => {
                        if (!window.grecaptcha) {
                            await new Promise((resolve, reject) => {
                                const script = document.createElement('script');
                                script.src =
                                    'https://www.google.com/recaptcha/enterprise.js?render='
                                    + siteKey;
                                script.onload = resolve;
                                script.onerror = () =>
                                    reject(new Error('enterprise.js load failed'));
                                document.head.appendChild(script);
                            });
                        }
                        await new Promise((r) => grecaptcha.enterprise.ready(r));
                        return grecaptcha.enterprise.execute(siteKey, { action });
                    }""",
                    {"siteKey": site_key, "action": action},
                )
                break
            except Exception as exc:
                last_err = exc
                if "Execution context was destroyed" not in str(exc):
                    raise
                page.wait_for_load_state("domcontentloaded", timeout=5000)
        if token is None:
            raise RuntimeError(
                f"Playwright reCAPTCHA failed after retries: {last_err}"
            )
        context.close()
        browser.close()

    if not token or len(str(token)) < 100:
        raise RuntimeError("Playwright reCAPTCHA returned empty token")
    return str(token)


def _seed_epsf(session: Any, base_url: str, page_url: str) -> None:
    session.get(page_url, allow_redirects=False, timeout=REQUEST_TIMEOUT)
    session.get(f"{base_url}/eps-mgr", timeout=REQUEST_TIMEOUT)
    fpjs = hashlib.md5(str(random.random()).encode()).hexdigest()
    session.get(
        f"{base_url}/eps/log?hasPublicKeyCredential=true"
        f"&hasConditionalMediation=true&conditionalMediationAvailable=true"
        f"&platformAuthenticator=true&err=&fpjs={fpjs}",
        timeout=REQUEST_TIMEOUT,
    )


class HttpTmptSolver:
    """Obtain tmpt using Playwright reCAPTCHA + HTTP GEC."""

    def __init__(
        self,
        session: Any,
        base_url: str,
        site_key: str = DEFAULT_SITE_KEY,
        proxy_line: str = "",
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.hostname = urlparse(self.base_url).hostname or ""
        self.site_key = site_key
        self.proxy_line = proxy_line

    def refresh(
        self,
        page_url: str,
        action: str = DEFAULT_ACTION,
        site_key: str | None = None,
    ) -> None:
        site_key = site_key or self.site_key
        _log("Seeding EPSF session...")
        _seed_epsf(self.session, self.base_url, page_url)

        _log("Getting reCAPTCHA token (headless)...")
        captcha_token = _recaptcha_token_playwright(
            page_url, site_key, action, self.proxy_line
        )
        _log(f"reCAPTCHA token acquired ({len(captcha_token)} chars)")

        body = json.dumps(
            {"hostname": self.hostname, "key": site_key, "token": captcha_token}
        )
        headers = {
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": page_url,
        }
        gec = self.session.post(
            f"{self.base_url}/epsf/gec/v3/{action}",
            headers=headers,
            data=body,
            timeout=REQUEST_TIMEOUT,
        )
        if gec.status_code >= 400:
            raise RuntimeError(f"GEC POST failed: HTTP {gec.status_code}")

        if not _has_tmpt(self.session, self.hostname):
            raise RuntimeError("GEC succeeded but tmpt cookie missing")
        _log("tmpt cookie set")


def refresh_tmpt(
    session: Any,
    base_url: str,
    page_url: str,
    action: str = DEFAULT_ACTION,
    site_key: str = DEFAULT_SITE_KEY,
    proxy_line: str = "",
) -> None:
    """Convenience wrapper."""
    HttpTmptSolver(
        session, base_url, site_key=site_key, proxy_line=proxy_line
    ).refresh(page_url, action, site_key)