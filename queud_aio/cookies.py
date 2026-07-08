"""HTTP session cookie persistence (OAuth tokens — not browser Akamai)."""

from __future__ import annotations

import json
from typing import Any

from queud_aio.config import AKAMAI_COOKIE_NAMES, BLOCK_MARKERS
from queud_aio.settings import Settings


def cookies_to_dict(session: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for cookie in session.cookies.jar:
        if cookie.name in AKAMAI_COOKIE_NAMES:
            continue
        items.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain or "",
                "path": cookie.path or "/",
            }
        )
    return items


def raw_cookies_for_queud(session: Any) -> list[dict[str, str]]:
    """All session cookies for queud extension export (includes Akamai)."""
    return [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain or "",
            "path": cookie.path or "/",
        }
        for cookie in session.cookies.jar
        if cookie.value
    ]


def apply_cookie_jar(
    session: Any,
    cookies: list[dict[str, str]],
    *,
    include_akamai: bool = False,
) -> None:
    for item in cookies:
        if not include_akamai and item["name"] in AKAMAI_COOKIE_NAMES:
            continue
        session.cookies.set(
            item["name"],
            item["value"],
            domain=item.get("domain") or None,
            path=item.get("path") or "/",
        )


def load_cookies(session: Any, settings: Settings) -> None:
    path = settings.http_session_file
    if not path.exists():
        legacy = path.parent / "cookies.json"
        if legacy.exists():
            path = legacy
        else:
            return
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for item in saved:
        if item["name"] in AKAMAI_COOKIE_NAMES:
            continue
        session.cookies.set(
            item["name"],
            item["value"],
            domain=item.get("domain") or None,
            path=item.get("path") or "/",
        )


def has_cookie(session: Any, name: str, domain: str = "") -> bool:
    host = domain.lstrip(".")
    for cookie in session.cookies.jar:
        if cookie.name != name:
            continue
        if not host:
            return True
        cookie_host = (cookie.domain or "").lstrip(".")
        if (
            cookie_host == host
            or host.endswith(cookie_host)
            or cookie_host.endswith(host)
        ):
            return True
    return False


def save_cookies(session: Any, settings: Settings) -> None:
    path = settings.http_session_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cookies_to_dict(session), indent=2),
        encoding="utf-8",
    )


def is_epsf_blocked(html: str) -> bool:
    return any(marker in html for marker in BLOCK_MARKERS)