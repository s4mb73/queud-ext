"""HTTP session client (wreq)."""

from __future__ import annotations

from typing import Any

from queud_aio.cookies import load_cookies, save_cookies
from queud_aio.epsf import refresh_tmpt
from queud_aio.log_util import log
from queud_aio.proxy import parse_proxy
from queud_aio.settings import Settings
from queud_aio.wreq_adapter import WreqHttpSession


class TmptClient:
    """wreq session with tmpt, sticky proxy, and HTTP session cookies."""

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

    def _make_session(self) -> WreqHttpSession:
        proxy_url = ""
        if self.proxy_line:
            _, proxy_url, _ = parse_proxy(self.proxy_line)
            host, _, _ = parse_proxy(self.proxy_line)
            session_id = self.proxy_line.split("-session-", 1)[-1].split(":", 1)[0]
            log(f"Using ZA proxy {host} (session {session_id[:12]}...)")
        else:
            log("Using direct connection (no proxy)")
        return WreqHttpSession(
            self.settings.impersonate,
            proxy_url=proxy_url,
            timeout=self.settings.request_timeout,
            base_url=self.base_url,
        )

    def refresh_tmpt(self, page_url: str) -> None:
        refresh_tmpt(self, page_url)

    def get(self, url: str, **kwargs: Any):
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any):
        return self.session.post(url, **kwargs)

    def put(self, url: str, **kwargs: Any):
        return self.session.put(url, **kwargs)

    def delete(self, url: str, **kwargs: Any):
        return self.session.delete(url, **kwargs)

    def persist(self) -> None:
        save_cookies(self.session, self.settings)

    def close(self) -> None:
        self.session.close()