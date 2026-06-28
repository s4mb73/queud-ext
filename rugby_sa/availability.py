"""Seat availability parsing."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import unquote, urlencode

from bs4 import BeautifulSoup

from rugby_sa.client import TmptClient
from rugby_sa.config import AVAILABLE_SEAT_SYMBOL, BLOCK_MARKERS
from rugby_sa.settings import Settings
from rugby_sa.models import EventTarget, SeatPair


def _normalize_ticket_code(code: str) -> str:
    return code if code.startswith("0") else f"0{code}"


def _symbol_map(sections: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for section in sections:
        for item in section.get("StatusSummary", []):
            code = item["Code"]
            mapping[code] = item["Symbol"]
            mapping[_normalize_ticket_code(code)] = item["Symbol"]
            if code.startswith("0"):
                mapping[code[1:]] = item["Symbol"]
    return mapping


def _decode_section_pairs(
    section: dict[str, Any],
    symbol_map: dict[str, str],
    min_seats: int,
) -> tuple[list[SeatPair], int]:
    rows = section.get("RowNames") or []
    seat_names = section.get("SeatNames") or []
    encoded = section.get("ExtendedTicketTypes") or []
    if not rows or not seat_names or not encoded:
        return [], 0

    num_rows = len(rows)
    num_seats = len(seat_names)
    grid: list[list[str]] = [[""] * num_seats for _ in range(num_rows)]
    pos = 0
    idx = 0
    while idx < len(encoded) and pos < num_rows * num_seats:
        code, count_s = encoded[idx].split(",", 1)
        symbol = symbol_map.get(code) or symbol_map.get(_normalize_ticket_code(code), "")
        count = int(count_s)
        for _ in range(count):
            if pos >= num_rows * num_seats:
                break
            row_i = pos // num_seats
            seat_i = pos % num_seats
            grid[row_i][seat_i] = symbol
            pos += 1
        idx += 1

    pairs: list[SeatPair] = []
    available_total = 0
    section_name = str(section.get("SectionName", ""))
    price_level = int(section.get("PriceLevel", 0))

    for row_i, row in enumerate(rows):
        row_name = str(row.get("Name", ""))
        symbols = grid[row_i]
        available_total += sum(1 for sym in symbols if sym == AVAILABLE_SEAT_SYMBOL)

        run_start: int | None = None
        run_len = 0
        for seat_i, sym in enumerate(symbols):
            if sym == AVAILABLE_SEAT_SYMBOL:
                if run_start is None:
                    run_start = seat_i
                    run_len = 1
                else:
                    run_len += 1
                continue
            if run_len >= min_seats and run_start is not None:
                pairs.append(
                    SeatPair(
                        section=section_name,
                        price_level=price_level,
                        row=row_name,
                        seat_start=seat_names[run_start],
                        seat_end=seat_names[run_start + run_len - 1],
                        seat_count=run_len,
                    )
                )
            run_start = None
            run_len = 0
        if run_len >= min_seats and run_start is not None:
            pairs.append(
                SeatPair(
                    section=section_name,
                    price_level=price_level,
                    row=row_name,
                    seat_start=seat_names[run_start],
                    seat_end=seat_names[run_start + run_len - 1],
                    seat_count=run_len,
                )
            )

    return pairs, available_total


def parse_availability(
    data: dict[str, Any], min_seats: int = 2
) -> tuple[list[SeatPair], int]:
    sections = data.get("Sections") or []
    symbol_map = _symbol_map(sections)
    pairs: list[SeatPair] = []
    total_available = 0
    for section in sections:
        section_pairs, avail = _decode_section_pairs(section, symbol_map, min_seats)
        pairs.extend(section_pairs)
        total_available += avail
    pairs.sort(key=lambda p: (-p.seat_count, p.section, p.row, p.seat_start))
    return pairs, total_available


def parse_event_page(html: str) -> tuple[str, bool, bool]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    blocked = any(marker in html for marker in BLOCK_MARKERS)
    needs_login = (
        "login.sarugby.co.za" in html
        or "EventRequiresSignIn" in html
        or "PricesRestricted" in html
        or "Login - eTickets" in title
        or ("Login" in title and "logged-in" not in html)
    )
    return title, blocked, needs_login


def csrf_token_from_html(html: str) -> str:
    match = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html
    )
    return match.group(1) if match else ""


def csrf_token_from_page(page: Any) -> str:
    """Read live CSRF from DOM — same source as ISM GR() helper."""
    try:
        token = page.evaluate(
            """() => {
                const el = document.querySelector('input[name="__RequestVerificationToken"]');
                return el && el.value ? el.value : '';
            }"""
        )
        return str(token or "")
    except Exception:
        return ""


def area_id_map(config: dict[str, Any]) -> dict[str, int]:
    return {str(a["Name"]): int(a["Id"]) for a in config.get("Areas", [])}


def price_class_for_band(config: dict[str, Any], price_band_id: int) -> int:
    """Map BA PriceBandId / section PriceLevel to PUT commit PriceClassId (PriceType)."""
    prices = config.get("Prices", {})
    if isinstance(prices, dict):
        for item in prices.get("Prices", []):
            if int(item.get("PriceCategory", 0)) == price_band_id:
                price_type = item.get("PriceType")
                if price_type is not None:
                    return int(price_type)
    return price_band_id


def price_labels_from_config(config: dict[str, Any]) -> dict[int, str]:
    labels: dict[int, str] = {}
    prices = config.get("Prices", {})
    if isinstance(prices, dict):
        for item in prices.get("Prices", []):
            category = item.get("PriceCategory")
            if category is not None:
                labels[int(category)] = str(
                    item.get("PriceFormatted")
                    or item.get("TotalFaceValueFormatted")
                    or "—"
                )
    return labels


def fetch_ba_search(
    client: Any,
    target: EventTarget,
    event_config: dict[str, Any],
    settings: Settings,
    quantity: int | None = None,
) -> list[dict[str, Any]]:
    """Best-available search — areas/price bands actually lockable via BA API."""
    path = event_config.get("Urls", {}).get("GetRegularSeatsUrl", "")
    if not path:
        return []
    if not path.startswith("http"):
        path = f"{settings.base_url}{path}"
    qty = quantity or settings.tickets_required
    query = urlencode(
        {
            "EventId": target.event_id,
            "Quantity": qty,
            "AreSeatsTogether": "true",
            "MinimumPrice": 0,
            "MaximumPrice": 10_000_000,
        }
    )
    page_url = target.page_url(settings.base_url)
    resp = client.get(
        f"{path}?{query}",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url,
        },
    )
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def fetch_event_config(
    client: TmptClient, target: EventTarget, settings: Settings
) -> dict[str, Any]:
    page_url = target.page_url(settings.base_url)
    resp = client.get(
        f"{settings.base_url}/EDP/Event/Config/{target.event_id}",
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url,
        },
    )
    resp.raise_for_status()
    return resp.json()


def fetch_availability(
    client: TmptClient,
    target: EventTarget,
    event_config: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    page_url = target.page_url(settings.base_url)
    avail_path = unquote(event_config["Urls"]["AvailabilityUrl"])
    if not avail_path.startswith("http"):
        avail_path = f"{settings.base_url}{avail_path}"
    resp = client.get(
        avail_path,
        headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url,
        },
    )
    resp.raise_for_status()
    return resp.json()


def parse_event_metadata(events_html: str, event_id: int) -> tuple[str, str, str, str]:
    soup = BeautifulSoup(events_html, "html.parser")
    item = soup.select_one(f"li.eventid-{event_id}")
    root = item if item else soup
    title_el = root.select_one(".event__title") or soup.find(id=f"event_title_{event_id}")
    date_el = root.select_one(".event__date-time .date")
    venue_el = root.select_one(".event__venue")
    img_el = root.select_one("img.event__img")
    name = title_el.get_text(strip=True) if title_el else ""
    date = date_el.get_text(strip=True) if date_el else ""
    venue = venue_el.get_text(strip=True) if venue_el else ""
    image = str(img_el.get("src", "")) if img_el else ""
    return name, date, venue, image


def is_event_page(html: str) -> bool:
    return "ism-module" in html or "Event Information Screen" in html