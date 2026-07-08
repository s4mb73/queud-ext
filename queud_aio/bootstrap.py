"""HTTP session bootstrap — login + cookie export via wreq."""

from __future__ import annotations

from queud_aio.availability import is_event_page
from queud_aio.client import TmptClient
from queud_aio.log_util import log
from queud_aio.proxy import pick_proxy_line, save_session_proxy
from queud_aio.session import ensure_page_access
from queud_aio.settings import Settings


def save_session_meta(settings: Settings, proxy_line: str) -> None:
    save_session_proxy(settings, proxy_line)


def bootstrap(settings: Settings, proxy_line: str = "") -> int:
    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)
    if not proxy_line:
        proxy_line = pick_proxy_line(settings)

    client = TmptClient(settings, proxy_line=proxy_line)
    try:
        log(f"Opening {event_url}")
        resp, final_url = ensure_page_access(client, event_url, settings)
        if not is_event_page(resp.text):
            if not settings.credentials_ok():
                log("Set SARUGBY_EMAIL and SARUGBY_PASSWORD")
            log(f"Failed to reach event page: {final_url}")
            return 1

        log(f"Event page OK — exporting cookies to {settings.http_session_file}")
        client.persist()
        save_session_meta(settings, proxy_line)
    finally:
        client.close()

    log(f"Session saved. Use same proxy: {proxy_line or 'direct'}")
    log("Run: python run.py cart-test")
    return 0