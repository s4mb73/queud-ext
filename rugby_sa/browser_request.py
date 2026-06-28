"""Browser-backed HTTP client — real Chrome session, request-based API calls."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import APIResponse, BrowserContext, Page, sync_playwright

from rugby_sa.bootstrap import save_session_meta, wait_for_event_page
from rugby_sa.headless_tmpt import playwright_proxy
from rugby_sa.http_response import HttpLikeResponse
from rugby_sa.log_util import log, warn
from rugby_sa.proxy import parse_proxy
from rugby_sa.settings import Settings


def _event_page_ready(page: Page) -> bool:
    try:
        title = page.title() or ""
        content = page.content()
    except Exception:
        return False
    if "Browsing Activity Has Been Paused" in content:
        return False
    if "Let's Get Your Identity Verified" in content:
        return False
    return "Event Information Screen" in title or "ism-module" in content


def _wrap(resp: APIResponse) -> HttpLikeResponse:
    try:
        body = resp.text()
    except Exception:
        body = ""
    return HttpLikeResponse(
        status_code=resp.status,
        text=body,
        url=resp.url,
        headers=dict(resp.headers),
    )


class BrowserRequestClient:
    """
    Persistent Playwright profile for Akamai/login; cart/availability via HTTP APIs.

    Navigation (page.goto) is only used to establish session. Add-to-cart uses
    context.request POST/PUT — no UI clicking.
    """

    def __init__(self, settings: Settings, proxy_line: str = "") -> None:
        self.settings = settings
        self.proxy_line = proxy_line
        self.base_url = settings.base_url.rstrip("/")
        self.hostname = urlparse(self.base_url).hostname or ""
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._request = None

    def __enter__(self) -> BrowserRequestClient:
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def start(self) -> None:
        if self._context is not None:
            return
        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        proxy_cfg = playwright_proxy(self.proxy_line) if self.proxy_line else None
        if self.proxy_line:
            host, _, _ = parse_proxy(self.proxy_line)
            sid = self.proxy_line.split("-session-", 1)[-1].split(":", 1)[0]
            log(f"Browser requests: ZA proxy {host} (session {sid[:12]}...)")
        else:
            log("Browser requests: direct connection")

        self._playwright = sync_playwright().start()
        headless = os.environ.get("SPRINGBOKS_HEADLESS", "0") == "1"
        context = None
        for channel in ("chrome", None):
            try:
                kwargs: dict[str, Any] = {
                    "user_data_dir": str(self.settings.profile_dir),
                    "headless": headless,
                    "viewport": {"width": 1400, "height": 900},
                    "locale": "en-GB",
                    "proxy": proxy_cfg,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if channel:
                    kwargs["channel"] = channel
                context = self._playwright.chromium.launch_persistent_context(**kwargs)
                log(f"Browser requests: {channel or 'chromium'} profile")
                break
            except Exception as exc:
                log(f"Browser launch failed ({channel}): {exc}")
        if context is None:
            context = self._playwright.chromium.launch_persistent_context(
                str(self.settings.profile_dir),
                headless=headless,
                viewport={"width": 1400, "height": 900},
                proxy=proxy_cfg,
            )

        self._context = context
        self._request = context.request
        self._page = context.pages[0] if context.pages else context.new_page()

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        self._request = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("BrowserRequestClient not started")
        return self._page

    def ensure_event_page(self, page_url: str) -> tuple[HttpLikeResponse, str]:
        """Navigate browser to authenticated event page (session only)."""
        self.start()
        page = self.page
        if not _event_page_ready(page):
            log(f"Browser: opening {page_url[:90]}")
            page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)
        if not wait_for_event_page(page, self.settings):
            warn(f"Browser: event page not ready — {page.title()}")
        elif self.proxy_line:
            save_session_meta(self.settings, self.proxy_line)
        html = page.content()
        return (
            HttpLikeResponse(status_code=200, text=html, url=page.url),
            page.url,
        )

    def _fetch_via_page(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: str | None,
    ) -> HttpLikeResponse:
        """Same-origin fetch from the live page — full browser cookie jar."""
        result = self.page.evaluate(
            """async ({method, url, headers, body}) => {
                const opts = { method, headers, credentials: 'include' };
                if (body != null) opts.body = body;
                const r = await fetch(url, opts);
                return { status: r.status, text: await r.text(), url: r.url };
            }""",
            {"method": method, "url": url, "headers": headers, "body": body},
        )
        return HttpLikeResponse(
            status_code=int(result["status"]),
            text=result["text"],
            url=result.get("url", url),
        )

    def _timeout_ms(self) -> float:
        return float(self.settings.request_timeout * 1000)

    def get(self, url: str, **kwargs: Any) -> HttpLikeResponse:
        self.start()
        headers = dict(kwargs.pop("headers", None) or {})
        kwargs.pop("allow_redirects", True)
        if _event_page_ready(self.page):
            try:
                return self._fetch_via_page("GET", url, headers, None)
            except Exception as exc:
                warn(f"Browser page fetch GET failed, using context.request: {exc}")
        resp = self._request.get(
            url,
            headers=headers,
            timeout=self._timeout_ms(),
            **kwargs,
        )
        return _wrap(resp)

    def post(self, url: str, **kwargs: Any) -> HttpLikeResponse:
        self.start()
        headers = dict(kwargs.pop("headers", None) or {})
        kwargs.pop("allow_redirects", True)
        json_body = kwargs.pop("json", None)
        data = kwargs.pop("data", None)
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")
            data = json.dumps(json_body)
        body = None if isinstance(data, dict) else data
        if _event_page_ready(self.page):
            try:
                return self._fetch_via_page("POST", url, headers, body)
            except Exception as exc:
                warn(f"Browser page fetch POST failed, using context.request: {exc}")
        if isinstance(data, dict):
            resp = self._request.post(
                url,
                form=data,
                headers=headers,
                timeout=self._timeout_ms(),
                **kwargs,
            )
        else:
            resp = self._request.post(
                url,
                data=data,
                headers=headers,
                timeout=self._timeout_ms(),
                **kwargs,
            )
        return _wrap(resp)

    def delete(self, url: str, **kwargs: Any) -> HttpLikeResponse:
        self.start()
        headers = dict(kwargs.pop("headers", None) or {})
        if _event_page_ready(self.page):
            try:
                result = self.page.evaluate(
                    """async ({url, headers}) => {
                        const r = await fetch(url, {
                            method: 'DELETE',
                            credentials: 'include',
                            headers,
                        });
                        return { status: r.status, text: await r.text(), url: r.url };
                    }""",
                    {"url": url, "headers": headers},
                )
                return HttpLikeResponse(
                    status_code=int(result["status"]),
                    text=result["text"],
                    url=result.get("url", url),
                )
            except Exception as exc:
                warn(f"Browser page fetch DELETE failed: {exc}")
        resp = self._request.delete(
            url,
            headers=headers,
            timeout=self._timeout_ms(),
            **kwargs,
        )
        return _wrap(resp)

    def put(self, url: str, **kwargs: Any) -> HttpLikeResponse:
        self.start()
        headers = dict(kwargs.pop("headers", None) or {})
        json_body = kwargs.pop("json", None)
        if json_body is not None:
            headers.setdefault("Content-Type", "application/json")
            data = json.dumps(json_body)
        else:
            data = kwargs.pop("data", None)
        if _event_page_ready(self.page):
            try:
                return self._fetch_via_page("PUT", url, headers, data)
            except Exception as exc:
                warn(f"Browser page fetch PUT failed, using context.request: {exc}")
        resp = self._request.put(
            url,
            data=data,
            headers=headers,
            timeout=self._timeout_ms(),
            **kwargs,
        )
        return _wrap(resp)

    def refresh_tmpt(self, page_url: str) -> None:
        """Re-navigate browser to refresh Akamai session (no curl_cffi)."""
        self.start()
        self.page.goto(page_url, wait_until="domcontentloaded", timeout=120_000)
        wait_for_event_page(self.page, self.settings)

    def persist(self) -> None:
        """Profile dir persists cookies automatically."""