"""Extract seat/price metadata from checkout basket HTML."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from queud_aio.config import PRICE_RE

_BLOCK_RE = re.compile(r"Block\s+(\d+|[A-Za-z]+)", re.I)
_ROW_RE = re.compile(r"\bRow\s+([A-Za-z0-9]+)", re.I)
_SEAT_RE = re.compile(r"\bSeats?\s+(\d+)(?:\s*[-–]\s*(\d+))?", re.I)


_EMPTY_BASKET_PHRASES = (
    "your basket is empty",
    "basket is empty",
    "no items in your basket",
    "there are no items",
    "0 items",
)


def basket_looks_empty(html: str) -> bool:
    """True when basket page has no ticket lines."""
    lower = html.lower()
    if any(phrase in lower for phrase in _EMPTY_BASKET_PHRASES):
        return True
    meta = parse_basket_html(html)
    return (
        meta["section"] == "—"
        and meta["row"] == "—"
        and meta["seat_start"] == "—"
        and meta["price"] == "—"
    )


def parse_basket_html(html: str) -> dict[str, str]:
    """Best-effort parse of /Checkout/Basket page."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    meta: dict[str, str] = {
        "section": "—",
        "row": "—",
        "seat_start": "—",
        "seat_end": "—",
        "price": "—",
        "size": "—",
    }

    block = _BLOCK_RE.search(text)
    if block:
        meta["section"] = f"Block {block.group(1)}"
        meta["size"] = meta["section"]

    row = _ROW_RE.search(text)
    if row:
        meta["row"] = row.group(1)

    seat = _SEAT_RE.search(text)
    if seat:
        meta["seat_start"] = seat.group(1)
        meta["seat_end"] = seat.group(2) or seat.group(1)

    prices = PRICE_RE.findall(text)
    if prices:
        meta["price"] = prices[0] if prices[0].startswith(("R", "ZAR")) else f"R{prices[0]}"

    for sel in (
        ".basket-item",
        ".checkout-item",
        ".ticket-item",
        "[data-seat]",
        "tr.basket",
    ):
        for node in soup.select(sel):
            chunk = node.get_text(" ", strip=True)
            if not chunk:
                continue
            b = _BLOCK_RE.search(chunk)
            r = _ROW_RE.search(chunk)
            s = _SEAT_RE.search(chunk)
            p = PRICE_RE.search(chunk)
            if b:
                meta["section"] = f"Block {b.group(1)}"
                meta["size"] = meta["section"]
            if r:
                meta["row"] = r.group(1)
            if s:
                meta["seat_start"] = s.group(1)
                meta["seat_end"] = s.group(2) or s.group(1)
            if p:
                val = p.group(0)
                meta["price"] = val if val.startswith(("R", "ZAR")) else f"R{val}"

    return meta


def cart_meta_path(data_dir: Path) -> Path:
    return data_dir / "cart_meta.json"


def save_cart_meta(data_dir: Path, meta: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    cart_meta_path(data_dir).write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )


def load_cart_meta(data_dir: Path) -> dict[str, str] | None:
    path = cart_meta_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return {k: str(v) for k, v in data.items() if v not in (None, "")}