"""Build queud extension checkout links (cookie + optional proxy inject)."""

from __future__ import annotations

import base64
import html
import json
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from rugby_sa.adonis import build_adonis_payload, proxy_line_to_url

# Stable ID from extensions/queud/manifest.json public key
QUEUD_EXTENSION_ID = "cinkmcgingnfflllnhdfckdfcfcnocjk"
QUEUD_CHECKOUT_PAGE = f"chrome-extension://{QUEUD_EXTENSION_ID}/checkout.html"


def decode_queud_payload(session_b64: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(session_b64).decode("utf-8"))


def build_queud_checkout_url(
    raw_cookies: list[dict[str, Any]],
    checkout_url: str,
    *,
    proxy_line: str = "",
) -> str:
    """Link opened in Chrome with queud extension installed."""
    payload = build_adonis_payload(raw_cookies)
    if not payload["cookies"]:
        return checkout_url

    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    parts = [
        QUEUD_CHECKOUT_PAGE,
        f"?session={quote(encoded, safe='')}",
        f"&endUrl={quote(checkout_url, safe='')}",
    ]
    proxy_url = proxy_line_to_url(proxy_line)
    if proxy_url:
        parts.append(f"&proxy={quote(proxy_url, safe='')}")
    return "".join(parts)


def build_queud_reserve_urls(
    raw_cookies: list[dict[str, Any]],
    checkout_url: str,
    *,
    proxy_line: str = "",
) -> tuple[str, str]:
    reserve = build_queud_checkout_url(raw_cookies, checkout_url, proxy_line="")
    proxy = build_queud_checkout_url(raw_cookies, checkout_url, proxy_line=proxy_line)
    return reserve, proxy


def build_queud_webhook_text(
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


def parse_queud_checkout_url(checkout_url: str) -> tuple[str, str, str]:
    """Extract session, endUrl, proxy from a queud checkout link."""
    parsed = urlparse(checkout_url)
    qs = parse_qs(parsed.query)
    session = unquote(qs.get("session", [""])[0])
    end_url = unquote(qs.get("endUrl", [""])[0])
    proxy = unquote(qs.get("proxy", [""])[0])
    return session, end_url, proxy


def queud_discord_launcher_html(
    session_b64: str,
    end_url: str,
    *,
    proxy: str = "",
) -> str:
    """
    Minimal carrier page for Discord CDN links.
    queud extension reads #queud-data and redirects — no page UI required.
    """
    payload = json.dumps(
        {"session": session_b64, "endUrl": end_url, "proxy": proxy},
        separators=(",", ":"),
    )
    safe_payload = payload.replace("</", "<\\/")
    return (
        "<!DOCTYPE html><html><head>"
        f'<script id="queud-data" type="application/json">{safe_payload}</script>'
        "</head><body></body></html>"
    )


def queud_launcher_html(checkout_url: str) -> str:
    """Double-click opens Chrome via chrome-extension checkout page."""
    safe = html.escape(checkout_url, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>queud checkout</title>
  <meta http-equiv="refresh" content="0;url={safe}" />
  <script>window.location.replace({json.dumps(checkout_url)});</script>
</head>
<body style="background:#0a1628;color:#fff;font-family:system-ui,sans-serif;text-align:center;padding:3rem">
  <p>Opening checkout with <strong>queud</strong>…</p>
  <p><a href="{safe}" style="color:#ff8c42">Click here</a> if you are not redirected.</p>
</body>
</html>
"""
