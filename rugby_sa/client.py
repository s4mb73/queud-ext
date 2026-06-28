"""HTTP session client."""

from __future__ import annotations

from typing import Any

from curl_cffi import requests as curl_requests

from rugby_sa.cookies import load_cookies, save_cookies
from rugby_sa.epsf import refresh_tmpt
from rugby_sa.log_util import log
from rugby_sa.proxy import parse_proxy
from rugby_sa.settings import Settings


class TmptClient:
    """curl_cffi session with tmpt, sticky proxy, and HTTP session cookies."""

    def __init__(
        self,
        settings: Settings,
        proxy_line: str | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = settings.base_url.rstrip("/")
        self.hostname = self.base_url.split("//", 1)[-1].split("/")[0]
        if proxy_line is not None:
            self.proxy_line = proxy_line
        elif settings.proxy_is_fixed:
            self.proxy_line = settings.proxy_line
        else:
            self.proxy_line = ""
        self.session = self._make_session()
        load_cookies(self.session, settings)

    def _make_session(self) -> curl_requests.Session:
        kwargs: dict[str, Any] = {
            "impersonate": self.settings.impersonate,
            "timeout": self.settings.request_timeout,
        }
        if self.proxy_line:
            _, proxy_url, _ = parse_proxy(self.proxy_line)
            kwargs["proxy"] = proxy_url
            host, _, _ = parse_proxy(self.proxy_line)
            session_id = self.proxy_line.split("-session-", 1)[-1].split(":", 1)[0]
            log(f"Using ZA proxy {host} (session {session_id[:12]}...)")
        else:
            log("Using direct connection (no proxy)")
        return curl_requests.Session(**kwargs)

    def refresh_tmpt(self, page_url: str) -> None:
        refresh_tmpt(self, page_url)

    def get(self, url: str, **kwargs: Any):
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.session.post(url, **kwargs)

    def put(self, url: str, **kwargs: Any):
        return self.session.put(url, **kwargs)

    def persist(self) -> None:
        save_cookies(self.session, self.settings)