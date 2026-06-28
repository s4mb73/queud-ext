#!/usr/bin/env python3
"""Request-based tmpt solver for Ticketmaster EPSF sites.

tmpt requires a reCAPTCHA Enterprise v3 action token posted to /epsf/gec/v3/{page}.
This module obtains that token via Google's anchor + reload HTTP endpoints (no browser).

Flow:
  1. Seed EPSF session (event page, eps-mgr, eps/log)
  2. GET recaptcha enterprise anchor -> recaptcha-token
  3. POST recaptcha enterprise reload -> gRecaptchaResponse
  4. POST token to /epsf/gec/v3/{action} via curl_cffi
  5. tmpt cookie is set on the HTTP session
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

from curl_cffi import requests as curl_requests

DEFAULT_SITE_KEY = "6LcvL3UrAAAAAO_9u8Seiuf-I6F_tP_jSS-zndXV"
DEFAULT_ACTION = "Event"
DEFAULT_VERSION = "h3SgW4Y0FyJGfNrXs3pg7JAt_7bHmM0n8Oc6W2iBrzC1"
REQUEST_TIMEOUT = int(os.environ.get("SPRINGBOKS_TIMEOUT_SEC", "60"))


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [tmpt] {msg}", flush=True)


def _has_tmpt(session: curl_requests.Session, hostname: str = "") -> bool:
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


def _b64_origin(page_url: str) -> str:
    parsed = urlparse(page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}:443"
    return base64.b64encode(origin.encode()).decode().rstrip("=")


def _fetch_recaptcha_version(session: curl_requests.Session, page_url: str) -> str:
    resp = session.get(page_url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
    versions = re.findall(r"releases/([^/]+)/recaptcha", resp.text)
    if versions:
        return versions[0]
    return DEFAULT_VERSION


def _anchor_token(
    session: curl_requests.Session,
    page_url: str,
    site_key: str,
    version: str,
    action: str,
) -> str:
    co = _b64_origin(page_url)
    params: dict[str, str] = {
        "ar": "1",
        "k": site_key,
        "co": co,
        "hl": "en",
        "v": version,
        "size": "invisible",
        "cb": str(random.randint(10**12, 10**13 - 1)),
    }
    if action:
        params["sa"] = action
    url = "https://www.google.com/recaptcha/enterprise/anchor?" + "&".join(
        f"{k}={quote(str(v), safe='')}" for k, v in params.items()
    )
    resp = session.get(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": page_url,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    match = re.search(r'id="recaptcha-token"\s+value="([^"]+)"', resp.text)
    if not match:
        raise RuntimeError("reCAPTCHA anchor: recaptcha-token not found")
    return match.group(1)


def _reload_token(
    session: curl_requests.Session,
    page_url: str,
    site_key: str,
    version: str,
    anchor_token: str,
    action: str,
) -> str:
    co = _b64_origin(page_url)
    payload = (
        f"v={version}&reason=q&c={quote(anchor_token, safe='')}"
        f"&k={quote(site_key, safe='')}&co={quote(co, safe='')}"
        f"&hl=en&size=invisible&chr=&vh=&bg="
        f"&sa={quote(action, safe='')}"
    )
    url = f"https://www.google.com/recaptcha/enterprise/reload?k={quote(site_key)}"
    resp = session.post(
        url,
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "https://www.google.com",
            "Referer": (
                f"https://www.google.com/recaptcha/enterprise/anchor?k={site_key}"
            ),
        },
        data=payload.encode(),
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.text
    match = re.search(r'\["rresp","([^"]+)"', text)
    if not match:
        if text.startswith('["rresp",null'):
            raise RuntimeError("reCAPTCHA reload returned null token")
        raise RuntimeError(f"reCAPTCHA reload: token not found ({text[:200]})")
    return match.group(1)


def _seed_epsf(session: curl_requests.Session, base_url: str, page_url: str) -> None:
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
    """Obtain tmpt using pure HTTP reCAPTCHA Enterprise + GEC."""

    def __init__(
        self,
        session: curl_requests.Session,
        base_url: str,
        site_key: str = DEFAULT_SITE_KEY,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.hostname = urlparse(self.base_url).hostname or ""
        self.site_key = site_key

    def refresh(
        self,
        page_url: str,
        action: str = DEFAULT_ACTION,
        site_key: str | None = None,
    ) -> None:
        site_key = site_key or self.site_key
        _log("Seeding EPSF session...")
        _seed_epsf(self.session, self.base_url, page_url)

        version = _fetch_recaptcha_version(self.session, page_url)
        _log(f"reCAPTCHA version {version}")

        anchor = _anchor_token(self.session, page_url, site_key, version, action)
        _log(f"anchor token ({len(anchor)} chars)")

        captcha_token = _reload_token(
            self.session, page_url, site_key, version, anchor, action
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
    session: curl_requests.Session,
    base_url: str,
    page_url: str,
    action: str = DEFAULT_ACTION,
    site_key: str = DEFAULT_SITE_KEY,
) -> None:
    """Convenience wrapper."""
    HttpTmptSolver(session, base_url, site_key=site_key).refresh(page_url, action, site_key)