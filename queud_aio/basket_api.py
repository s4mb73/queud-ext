"""Register short basket links on your queud API (Carbon-style)."""

from __future__ import annotations

import requests

from queud_aio.settings import Settings


def register_basket(
    settings: Settings,
    *,
    session_b64: str,
    end_url: str,
    proxy: str = "",
) -> str:
    """POST session → return full https://api…/basket/{uuid} URL."""
    base = settings.queud_api_base.rstrip("/")
    if not base:
        raise RuntimeError(
            "QUEUD_API_BASE not set — deploy queud_api/server.py on your domain "
            "and set QUEUD_API_BASE=https://api.yourdomain.com in .env"
        )
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.queud_api_key:
        headers["X-Api-Key"] = settings.queud_api_key
    resp = requests.post(
        f"{base}/basket",
        json={"session": session_b64, "endUrl": end_url, "proxy": proxy or ""},
        headers=headers,
        timeout=settings.request_timeout,
    )
    resp.raise_for_status()
    body = resp.json()
    basket_id = body.get("id") or body.get("path", "").split("/")[-1]
    if not basket_id:
        raise RuntimeError(f"Invalid basket API response: {body}")
    return f"{base}/basket/{basket_id}"


def register_checkout_pair(
    settings: Settings,
    *,
    reserve_url: str,
    proxy_url: str,
) -> tuple[str, str]:
    from queud_aio.queud import parse_queud_checkout_url

    proxy_session, end_url, proxy_cred = parse_queud_checkout_url(proxy_url)
    reserve_session, _, _ = parse_queud_checkout_url(reserve_url)
    reserve_click = register_basket(
        settings, session_b64=reserve_session, end_url=end_url, proxy=""
    )
    proxy_click = register_basket(
        settings,
        session_b64=proxy_session,
        end_url=end_url,
        proxy=proxy_cred,
    )
    return reserve_click, proxy_click