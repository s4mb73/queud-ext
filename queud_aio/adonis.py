"""Build Adonis Extension checkout links (cookie + proxy inject)."""

from __future__ import annotations

import base64
import html
import json
import re
from typing import Any
from urllib.parse import quote

from queud_aio.proxy import parse_proxy

# Short links (http://links.adonisbots.com/<slug>/) 302-redirect here; extension
# only activates on this host. Slug creation is internal to Adonis bot — we emit
# the full URL directly (same end result when opened in Chrome).
ADONIS_EXTENSION_BASE = "https://adonisbots.com/?extension="

# Drop Playwright noise (Google reCAPTCHA etc.) — keep TM / Rugby / Akamai session.
_CHECKOUT_DOMAIN_RE = re.compile(
    r"(tmtickets|springboks|sarugby|akamai|queue-it|web-identity|identity\.sarugby)",
    re.I,
)


def filter_checkout_cookies(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only cookies needed for TM Tickets checkout."""
    kept: list[dict[str, Any]] = []
    for cookie in raw:
        if not cookie.get("value"):
            continue
        domain = str(cookie.get("domain") or "")
        if _CHECKOUT_DOMAIN_RE.search(domain):
            kept.append(cookie)
    return kept


def _normalize_cookie_domain(domain: str) -> str:
    """Keep Playwright domains; ensure leading dot for multi-part hosts (Adonis/TM style)."""
    domain = domain.strip()
    if not domain:
        return domain
    host = domain.lstrip(".")
    if host.count(".") >= 2 and not domain.startswith("."):
        return f".{host}"
    return domain


def playwright_cookies_to_adonis(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format Playwright cookies for Adonis extension import."""
    out: list[dict[str, Any]] = []
    for cookie in raw:
        value = cookie.get("value")
        if not value:
            continue
        domain = _normalize_cookie_domain(cookie.get("domain") or "")
        out.append(
            {
                "name": cookie.get("name", ""),
                "value": value,
                "domain": domain,
                "path": cookie.get("path") or "/",
                "httponly": bool(cookie.get("httpOnly")),
                "secure": bool(cookie.get("secure")),
            }
        )
    return out


def proxy_line_to_url(proxy_line: str) -> str:
    """host:port:user:pass → http://user:pass@host:port for Adonis."""
    if not proxy_line.strip():
        return ""
    _, proxy_url, _ = parse_proxy(proxy_line)
    return proxy_url


def build_adonis_payload(
    raw_cookies: list[dict[str, Any]],
    *,
    local_storage: list[dict[str, Any]] | None = None,
    session_storage: list[dict[str, Any]] | None = None,
    use_all_cookies: bool = True,
) -> dict[str, Any]:
    """Match Adonis bot payload: cookies + explicit null storage keys."""
    source = raw_cookies if use_all_cookies else filter_checkout_cookies(raw_cookies)
    source = [c for c in source if c.get("value")]
    payload: dict[str, Any] = {
        "cookies": playwright_cookies_to_adonis(source),
        "local_storage": local_storage,
        "session_storage": session_storage,
    }
    return payload


def decode_adonis_payload(extension_b64: str) -> dict[str, Any]:
    """Round-trip check — same decode path as the Adonis extension."""
    return json.loads(base64.b64decode(extension_b64).decode("utf-8"))


def build_adonis_reserve_urls(
    raw_cookies: list[dict[str, Any]],
    checkout_url: str,
    *,
    proxy_line: str = "",
) -> tuple[str, str]:
    """Reserve link (no proxy) + proxy link — matches Adonis bot webhook pair."""
    reserve = build_adonis_checkout_url(raw_cookies, checkout_url, proxy_line="")
    proxy = build_adonis_checkout_url(
        raw_cookies, checkout_url, proxy_line=proxy_line
    )
    return reserve, proxy


def build_adonis_webhook_text(
    *,
    reserve_url: str,
    proxy_url: str,
    store: str,
    price: str,
    product: str,
    email: str,
    quantity: int,
    section: str,
    row: str,
    seat_start: str,
    seat_end: str,
    payment_method: str = "Manual",
    mode: str = "Standard",
    size: str = "—",
) -> str:
    """Plain-text body matching Adonis bot Discord webhook layout."""
    seats = (
        f"[{seat_start}]"
        if seat_start == seat_end
        else f"[{seat_start} - {seat_end}]"
    )
    lines = [
        f"Successful reserve {{{reserve_url}}}",
        f"Proxy URL {{{proxy_url}}}",
        "Store",
        store,
        "Price",
        price,
        "Size",
        size,
        "Product",
        product,
        "Payment Method",
        payment_method,
        "Mode",
        mode,
        "Email",
        email,
        "Quantity",
        str(quantity),
        "Seat Data",
        f"Sec: {section}",
        f"Row: {row}",
        f"Seats: {seats}",
    ]
    return "\n".join(lines)


def build_adonis_checkout_url(
    raw_cookies: list[dict[str, Any]],
    checkout_url: str,
    *,
    proxy_line: str = "",
    local_storage: list[dict[str, Any]] | None = None,
    session_storage: list[dict[str, Any]] | None = None,
) -> str:
    """
    Link opened in Chrome with Adonis Extension installed.

    Extension reads base64 JSON (cookies), optional proxy, then redirects to checkout.
    """
    payload = build_adonis_payload(
        raw_cookies,
        local_storage=local_storage,
        session_storage=session_storage,
    )
    if not payload["cookies"]:
        return checkout_url

    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    parts = [f"{ADONIS_EXTENSION_BASE}{encoded}", f"endUrl={quote(checkout_url, safe='')}"]
    proxy_url = proxy_line_to_url(proxy_line)
    if proxy_url:
        parts.append(f"proxy={quote(proxy_url, safe='')}")
    return "&".join(parts)


def adonis_internet_shortcut(checkout_url: str) -> str:
    """Windows .url file — only reliable for short URLs (<2k chars)."""
    return f"[InternetShortcut]\r\nURL={checkout_url}\r\n"


def adonis_launcher_html(checkout_url: str) -> str:
    """Double-click opens Chrome and navigates to Adonis extension URL."""
    safe = html.escape(checkout_url, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Springboks Checkout</title>
  <meta http-equiv="refresh" content="0;url={safe}" />
  <script>window.location.replace({json.dumps(checkout_url)});</script>
</head>
<body>
  <p>Opening checkout with Adonis Extension…</p>
  <p><a href="{safe}">Click here</a> if you are not redirected.</p>
</body>
</html>
"""