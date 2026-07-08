"""Session flow: tmpt → identity EPSF → OAuth → event page."""

from __future__ import annotations

from urllib.parse import urlparse

from queud_aio.auth import complete_sarugby_oauth, ensure_identity_tmpt
from queud_aio.availability import is_event_page, parse_event_page
from queud_aio.client import TmptClient
from queud_aio.cookies import has_cookie, is_epsf_blocked
from queud_aio.log_util import log, warn
from queud_aio.settings import Settings


def has_browser_session(client: TmptClient, settings: Settings) -> bool:
    """Imported Akamai cookies — skip automatic tmpt refresh when still valid."""
    host = urlparse(settings.base_url).hostname or ""
    return has_cookie(client.session, "_abck", host) and has_cookie(
        client.session, "tmpt", host
    )


def needs_tmpt_refresh(client: TmptClient, resp, settings: Settings) -> bool:
    if has_browser_session(client, settings):
        return False
    if resp.status_code == 200 and is_event_page(resp.text):
        return False
    hostname = urlparse(settings.base_url).hostname or ""
    has_tmpt = has_cookie(client.session, "tmpt", hostname)
    title, _, needs_login = parse_event_page(resp.text)
    if needs_login or "Login - eTickets" in title:
        return False
    if not has_tmpt:
        return (
            resp.status_code in (401, 403)
            or "Let's Get Your Identity Verified" in resp.text
        )
    return resp.status_code == 401


def ensure_page_access(
    client: TmptClient, page_url: str, settings: Settings
) -> tuple[object, str]:
    """Load event page through EPSF / identity / OAuth as needed."""
    if has_browser_session(client, settings):
        log("Using browser session cookies (_abck + tmpt)")

    resp = client.get(page_url, allow_redirects=True)
    if has_browser_session(client, settings) and is_epsf_blocked(resp.text):
        warn(
            "Session blocked or expired — re-run: python run.py bootstrap"
        )

    if needs_tmpt_refresh(client, resp, settings):
        client.refresh_tmpt(page_url)
        resp = client.get(page_url, allow_redirects=True)

    final_url = str(resp.url)

    if "Let's Get Your Identity Verified" in resp.text and "web-identity" in final_url:
        ensure_identity_tmpt(client, final_url, settings)
        resp = client.get(final_url, allow_redirects=True)
        final_url = str(resp.url)

    if "login.sarugby.co.za" in final_url or (
        "web-identity" in final_url and "account/login" in final_url.lower()
    ):
        if settings.credentials_ok():
            authed = complete_sarugby_oauth(client, final_url, settings)
            if authed is not None:
                resp = authed
                final_url = str(authed.url)
        else:
            warn("Login required but SARUGBY credentials not set")
    elif "web-identity" in final_url and settings.credentials_ok():
        ensure_identity_tmpt(client, final_url, settings)
        resp = client.get(final_url, allow_redirects=True)
        final_url = str(resp.url)
        if "login.sarugby.co.za" in final_url:
            authed = complete_sarugby_oauth(client, final_url, settings)
            if authed is not None:
                resp = authed
                final_url = str(authed.url)

    return resp, final_url