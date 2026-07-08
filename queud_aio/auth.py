"""SA Rugby OAuth login."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from queud_aio.client import TmptClient
from queud_aio.cookies import has_cookie
from queud_aio.log_util import log, warn
from queud_aio.settings import Settings

OAUTH_PARAM_KEYS = {
    "client_id",
    "redirect_uri",
    "response_type",
    "scope",
    "state",
    "code_challenge",
    "code_challenge_method",
    "nonce",
    "max_age",
}


def oauth_params_from_url(url: str) -> dict[str, str]:
    query = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in query.items() if k in OAUTH_PARAM_KEYS and v}


def submit_oidc_form(client: TmptClient, html: str, page_url: str):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        return None
    action = form.get("action") or page_url
    action = urljoin(page_url, action)
    fields = {
        inp.get("name"): inp.get("value", "")
        for inp in form.find_all("input")
        if inp.get("name")
    }
    if "code" not in fields:
        return None
    return client.post(
        action,
        data=fields,
        headers={"Referer": page_url},
        allow_redirects=True,
    )


def complete_sarugby_oauth(
    client: TmptClient, oauth_url: str, settings: Settings
) -> Any | None:
    if not settings.credentials_ok():
        warn("SARUGBY credentials not set — skipping login")
        return None

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://login.sarugby.co.za",
        "Referer": oauth_url,
    }
    login = client.post(
        "https://login.sarugby.co.za/api/login",
        json={
            "username": settings.sarugby_email,
            "password": settings.sarugby_password,
            "clientId": "SARU",
            "deviceId": str(uuid.uuid4()),
        },
        headers=headers,
    ).json()
    if login.get("status") != "success":
        log(f"SA Rugby login failed: {login}")
        return None
    log("SA Rugby login OK")

    auth = client.post(
        "https://login.sarugby.co.za/api/authorize",
        json=oauth_params_from_url(oauth_url),
        headers=headers,
    ).json()
    if auth.get("status") != "success":
        log(f"SA Rugby authorize failed: {auth}")
        return None

    redirect_uri = oauth_params_from_url(oauth_url)["redirect_uri"]
    callback_url = (
        f"{redirect_uri}?{urlencode({'code': auth['data']['code'], 'state': auth['data']['state']})}"
    )
    resp = client.get(callback_url, allow_redirects=True)

    for _ in range(6):
        if f"{settings.base_url}/EDP/Event/Index/" in str(resp.url):
            log("Authenticated on event page")
            return resp
        if "<form" not in resp.text.lower():
            break
        nxt = submit_oidc_form(client, resp.text, str(resp.url))
        if nxt is None:
            break
        resp = nxt

    if f"{settings.base_url}/EDP/Event" in str(resp.url):
        return resp
    log(f"OAuth finished at {str(resp.url)[:120]}")
    return None


def ensure_identity_tmpt(
    client: TmptClient, identity_url: str, settings: Settings
) -> None:
    probe = client.get(identity_url, allow_redirects=False)
    if "Let's Get Your Identity Verified" not in probe.text:
        return
    log("Refreshing tmpt on identity host...")
    identity_host = urlparse(settings.identity_host).hostname or ""
    identity_client = TmptClient(settings, proxy_line=client.proxy_line)
    identity_client.refresh_tmpt(identity_url)
    for cookie in identity_client.session.cookies.jar:
        client.session.cookies.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path,
        )
    if not has_cookie(client.session, "tmpt", identity_host):
        warn("Identity tmpt not visible on shared jar")