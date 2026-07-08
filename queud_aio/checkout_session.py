"""Basket capture over HTTP (wreq)."""

from __future__ import annotations

from dataclasses import dataclass
from queud_aio.basket_meta import basket_looks_empty, parse_basket_html
from queud_aio.cart import basket_item_count
from queud_aio.cookies import raw_cookies_for_queud
from queud_aio.client import TmptClient
from queud_aio.queud import build_queud_reserve_urls
from queud_aio.session import ensure_page_access
from queud_aio.settings import Settings


@dataclass(frozen=True)
class BasketSnapshot:
    html: str
    parsed: dict[str, str]
    item_count: int
    raw_cookies: list
    reserve_url: str
    proxy_url: str
    proxy_line: str
    basket_url: str


def capture_basket(
    client: TmptClient,
    settings: Settings,
    *,
    event_url: str | None = None,
    require_items: bool = False,
) -> BasketSnapshot:
    """GET basket page once; return cookies + parsed metadata."""
    target = settings.event_targets[0]
    event_url = event_url or target.page_url(settings.base_url)
    basket_url = f"{settings.base_url}/Checkout/Basket"

    ensure_page_access(client, event_url, settings)
    item_count = basket_item_count(client, settings, event_url)
    resp = client.get(
        basket_url,
        headers={"Referer": event_url},
        allow_redirects=True,
    )
    html = resp.text
    parsed = parse_basket_html(html)

    if require_items and item_count < settings.tickets_required and basket_looks_empty(html):
        raise RuntimeError(
            f"Basket empty ({item_count}/{settings.tickets_required}) — cart first"
        )
    if not require_items and item_count < 1 and basket_looks_empty(html):
        raise RuntimeError(f"Basket empty ({item_count} items)")

    raw = raw_cookies_for_queud(client.session)
    reserve_url, proxy_url = build_queud_reserve_urls(
        raw, basket_url, proxy_line=client.proxy_line
    )
    return BasketSnapshot(
        html=html,
        parsed=parsed,
        item_count=item_count,
        raw_cookies=raw,
        reserve_url=reserve_url,
        proxy_url=proxy_url,
        proxy_line=client.proxy_line,
        basket_url=basket_url,
    )


def merge_parsed_meta(
    parsed: dict[str, str], saved: dict[str, str] | None
) -> dict[str, str]:
    saved = saved or {}
    out = dict(parsed)
    for key in ("section", "row", "seat_start", "seat_end", "price", "size"):
        if out.get(key) in ("—", "", None) and saved.get(key):
            out[key] = saved[key]
    if out.get("size") in ("—", "", None):
        out["size"] = out.get("section") or "—"
    return out