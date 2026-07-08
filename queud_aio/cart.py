"""Best Available cart API with safety filters."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from queud_aio.availability import (
    area_id_map,
    csrf_token_from_html,
    csrf_token_from_page,
    fetch_ba_search,
    price_class_for_band,
)
from queud_aio.log_util import log, warn
from queud_aio.models import EventTarget, SeatPair
from queud_aio.settings import Settings


def cart_page_referer(target: EventTarget, settings: Settings) -> str:
    return target.page_url(settings.base_url)


def _area_id_from_lock(lock_data: dict[str, Any]) -> int | None:
    for seat in lock_data.get("LockedSeats") or []:
        area = seat.get("AreaId")
        if area is not None:
            return int(area)
    main = lock_data.get("MainSeat")
    if main and main.get("AreaId") is not None:
        return int(main["AreaId"])
    return None


def resolve_csrf_token(client: Any, page_html: str) -> str:
    if hasattr(client, "page"):
        token = csrf_token_from_page(client.page)
        if token:
            return token
    return csrf_token_from_html(page_html)


def cart_api_headers(settings: Settings, page_url: str, csrf: str) -> dict[str, str]:
    """Match ISM axios headers — extra Origin/Referer/dup CSRF keys cause HTTP 400."""
    headers = {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    if csrf:
        headers["RequestVerificationToken"] = csrf
    return headers


def purge_api_headers(csrf: str) -> dict[str, str]:
    headers = {"X-Requested-With": "XMLHttpRequest"}
    if csrf:
        headers["RequestVerificationToken"] = csrf
    return headers


def _seat_dom_id(area_id: int, y_coord: int, x_coord: int) -> str:
    return f"s_{area_id}-{y_coord}-{x_coord}"


def _coord_fields(seat: dict[str, Any]) -> tuple[int, int] | None:
    y = seat.get("YCoord", seat.get("YCoordinate"))
    x = seat.get("XCoord", seat.get("XCoordinate"))
    if y is None or x is None:
        return None
    return int(y), int(x)


def locked_seats_from_response(
    data: dict[str, Any], price_class_id: int
) -> list[dict[str, Any]]:
    raw = data.get("LockedSeats") or []
    if data.get("MainSeat"):
        raw = [data["MainSeat"], *(data.get("CompanionSeats") or [])]
    commits: list[dict[str, Any]] = []
    for seat in raw:
        area_id = int(seat.get("AreaId", 0))
        seat_id = seat.get("Id") or seat.get("id")
        if seat_id is None:
            coords = _coord_fields(seat)
            if area_id and coords:
                seat_id = _seat_dom_id(area_id, coords[0], coords[1])
        price_class = int(
            seat.get("selectedPriceClass")
            or seat.get("PriceClassId")
            or seat.get("PriceBandId")
            or price_class_id
        )
        if seat_id:
            commits.append({"Id": str(seat_id), "PriceClassId": price_class})
    return commits


def _parse_zar(price: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", price.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def pair_allowed(
    pair: SeatPair,
    settings: Settings,
    price_labels: dict[int, str],
) -> bool:
    if settings.cart_allowed_sections and pair.section not in settings.cart_allowed_sections:
        warn(f"Cart: skip {pair.section} (not in QUEUD_AIO_CART_SECTIONS)")
        return False
    if settings.cart_max_price_zar is not None:
        label = price_labels.get(pair.price_level, "")
        unit = _parse_zar(label)
        if unit is not None and unit > settings.cart_max_price_zar:
            warn(f"Cart: skip {pair.label()} — {label} > max R{settings.cart_max_price_zar:,.0f}")
            return False
    return True


def purge_seat_locks(
    client: Any,
    event_config: dict[str, Any],
    settings: Settings,
    page_url: str,
    event_id: int,
    csrf: str = "",
) -> None:
    url = event_config.get("Urls", {}).get("PurgeLocksUrl")
    if not url:
        return
    if not url.startswith("http"):
        url = f"{settings.base_url}{url}"
    purge_url = f"{url}?eventId={event_id}"
    headers = purge_api_headers(csrf)
    client.delete(purge_url, headers=headers)


def _akamai_blocked(detail: str) -> bool:
    lowered = detail.lower()
    return "403" in detail or "block" in lowered


def _fast_lock_attempts(
    pair: SeatPair,
    event_config: dict[str, Any],
    settings: Settings,
    search: list[dict[str, Any]] | None = None,
) -> list[tuple[str, int | None, int | None]]:
    """
    Minimal lock attempts for speed + low Akamai risk.

    1. Target section (area from event config — no BA search round-trip)
    2. First BA search hit for that price band (only if section unknown)
    3. Global any-area fallback
    """
    areas = area_id_map(event_config)
    section_area = areas.get(pair.section)
    price_band = pair.price_level or 6
    attempts: list[tuple[str, int | None, int | None]] = []
    seen: set[tuple[int | None, int | None]] = set()

    def add(label: str, area_id: int | None, band: int | None) -> None:
        key = (area_id, band)
        if key in seen:
            return
        seen.add(key)
        attempts.append((label, area_id, band))

    if search:
        matched = False
        if section_area:
            for item in search:
                area_id = int(item.get("AreaId", 0))
                if area_id != section_area:
                    continue
                for band in item.get("PriceBands") or []:
                    if int(band.get("PriceBandCode", 0)) == price_band:
                        add(pair.section, area_id, price_band)
                        matched = True
                        break
                if matched:
                    break
        if not matched:
            for item in search:
                area_id = int(item.get("AreaId", 0))
                for band in item.get("PriceBands") or []:
                    if int(band.get("PriceBandCode", 0)) == price_band:
                        add(f"search area {area_id}", area_id, price_band)
                        break
                if attempts:
                    break
    elif section_area:
        add(pair.section, section_area, price_band)

    add("any area", None, None)
    return attempts[: settings.cart_lock_attempts]


def _lock_request_body(
    target: EventTarget,
    settings: Settings,
    price_band_id: int | None,
    area_id: int | None,
    quantity: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "EventId": target.event_id,
        "Quantity": quantity or settings.tickets_required,
        "AreSeatsTogether": True,
        "SeatAttributeIds": [],
        "MinimumPrice": 0,
        "MaximumPrice": 10_000_000,
    }
    if price_band_id is not None:
        body["PriceBandId"] = price_band_id
    if area_id is not None:
        body["AreaId"] = area_id
    return body


def _lock_url(event_config: dict[str, Any], settings: Settings) -> str:
    path = event_config.get("Urls", {}).get("LockRegularSeatsUrl", "")
    if not path:
        return ""
    return f"{settings.base_url}{path}" if not path.startswith("http") else path


def _parse_lock_response(status: int, text: str) -> tuple[bool, dict[str, Any] | None, str]:
    if status != 200:
        return False, None, f"HTTP {status}: {text[:280]}"
    try:
        return True, json.loads(text), text[:300]
    except json.JSONDecodeError:
        return False, None, text[:300]


def pick_best_lock_result(
    results: list[tuple[int, str]],
) -> tuple[int, tuple[bool, dict[str, Any] | None, str] | None]:
    """Pick earliest successful lock by attempt order."""
    for index, (status, text) in enumerate(results):
        ok, data, detail = _parse_lock_response(status, text)
        if ok and data:
            return index, (ok, data, detail)
    return -1, None


def lock_best_available_pair(
    client: Any,
    target: EventTarget,
    event_config: dict[str, Any],
    settings: Settings,
    page_url: str,
    csrf: str,
    price_band_id: int | None,
    area_id: int | None = None,
    quantity: int | None = None,
) -> tuple[bool, dict[str, Any] | None, str]:
    url = _lock_url(event_config, settings)
    if not url or not csrf:
        return False, None, "lock url or csrf missing"
    body = _lock_request_body(target, settings, price_band_id, area_id, quantity)
    resp = client.post(url, json=body, headers=cart_api_headers(settings, page_url, csrf))
    return _parse_lock_response(resp.status_code, resp.text)


def commit_locked_seats(
    client: Any,
    target: EventTarget,
    event_config: dict[str, Any],
    settings: Settings,
    page_url: str,
    csrf: str,
    area_id: int,
    lock_data: dict[str, Any],
    price_class_id: int,
) -> tuple[bool, str]:
    path = event_config.get("Urls", {}).get("LockRegularSeatsUrl", "")
    if not path or not csrf:
        return False, "lock url or csrf missing"
    url = f"{settings.base_url}{path}" if not path.startswith("http") else path
    seats = locked_seats_from_response(lock_data, price_class_id)
    if not seats:
        return False, "no LockedSeats in lock response"
    body: dict[str, Any] = {
        "EventId": target.event_id,
        "Seats": seats,
    }
    if area_id:
        body["AreaId"] = area_id
    resp = client.put(
        url, json=body, headers=cart_api_headers(settings, page_url, csrf)
    )
    if resp.status_code == 200:
        return True, resp.text[:300]
    return False, resp.text[:300]


def basket_item_count(client: Any, settings: Settings, page_url: str) -> int:
    resp = client.get(
        f"{settings.base_url}/Checkout/Basket/ItemsCount",
        headers={"Accept": "application/json", "Referer": page_url},
    )
    try:
        return int(resp.text.strip())
    except ValueError:
        return 0


def cart_via_best_available(
    client: Any,
    target: EventTarget,
    pair: SeatPair,
    event_config: dict[str, Any],
    settings: Settings,
    page_url: str,
    csrf: str,
) -> bool:
    price_band = pair.price_level or 6
    areas = area_id_map(event_config)
    search = fetch_ba_search(client, target, event_config, settings)
    attempts = _fast_lock_attempts(pair, event_config, settings, search)
    purge_seat_locks(client, event_config, settings, page_url, target.event_id, csrf)

    lock_data: dict[str, Any] | None = None
    used_area: int | None = None
    for label, area_id, band in attempts:
        band_label = band if band is not None else "any"
        log(f"Cart: BA lock {label} (PriceBandId={band_label})")
        ok, data, detail = lock_best_available_pair(
            client,
            target,
            event_config,
            settings,
            page_url,
            csrf,
            band,
            area_id=area_id,
        )
        if ok and data:
            lock_data = data
            used_area = area_id if area_id is not None else _area_id_from_lock(data)
            break
        log(f"Cart: BA lock failed ({label}): {detail[:200]}")
        if _akamai_blocked(detail):
            warn("Cart: Akamai block — aborting")
            if hasattr(client, "__dict__"):
                client._cart_blocked = True
            return False

    if not lock_data:
        return False

    locked = lock_data.get("LockedSeats") or []
    section_area = areas.get(pair.section)
    area_label = pair.section if used_area == section_area else f"area {used_area or 'any'}"
    log(f"Cart: BA locked {len(locked)} seat(s) — {area_label}")

    if settings.cart_dry_run:
        log(f"Cart: DRY RUN — would add {pair.label()} (no basket commit)")
        return True

    commit_area = used_area if used_area is not None else _area_id_from_lock(lock_data)
    if commit_area is None:
        log("Cart: lock OK but no AreaId for PUT commit — basket may stay empty")
        return False

    lock_band = int(lock_data.get("PriceBandId") or price_band)
    commit_class = price_class_for_band(event_config, lock_band)
    commit_csrf = resolve_csrf_token(client, "")
    ok, detail = commit_locked_seats(
        client,
        target,
        event_config,
        settings,
        page_url,
        commit_csrf or csrf,
        commit_area,
        lock_data,
        commit_class,
    )
    if _akamai_blocked(detail):
        warn("Cart: Akamai block on commit — aborting")
        if hasattr(client, "__dict__"):
            client._cart_blocked = True
        return False
    count = basket_item_count(client, settings, page_url) if ok else 0
    if count >= settings.tickets_required:
        log(f"Cart: basket={count} after PUT commit")
        if hasattr(client, "__dict__"):
            client._last_carted_pair = pair
        return True
    if not ok:
        log(f"Cart: PUT commit failed: {detail[:200]}")
    else:
        log(f"Cart: PUT returned 200 but basket={count} (need {settings.tickets_required})")
    if hasattr(client, "__dict__"):
        client._cart_locked = True
    return False


def cart_adjacent_pair(
    client: Any,
    target: EventTarget,
    pair: SeatPair,
    event_config: dict[str, Any],
    settings: Settings,
    page_html: str,
) -> bool:
    cart_ref = cart_page_referer(target, settings)
    csrf = resolve_csrf_token(client, page_html)
    if not csrf:
        log("Cart: missing CSRF token — reload event page before carting")
        return False
    return cart_via_best_available(
        client, target, pair, event_config, settings, cart_ref, csrf
    )


def cart_candidates(pairs: list[SeatPair], settings: Settings) -> list[SeatPair]:
    req = settings.tickets_required
    exact = [p for p in pairs if p.seat_count == req]
    return exact if exact else [p for p in pairs if p.seat_count >= req]


def cart_best_pair(
    client: Any,
    target: EventTarget,
    pairs: list[SeatPair],
    event_config: dict[str, Any],
    settings: Settings,
    page_html: str,
    price_labels: dict[int, str],
) -> bool:
    if not settings.auto_cart:
        return False
    candidates = [
        p
        for p in cart_candidates(pairs, settings)
        if pair_allowed(p, settings, price_labels)
    ]
    for pair in candidates[: settings.cart_max_attempts]:
        log(f"Cart: attempting {pair.label()}")
        if cart_adjacent_pair(
            client, target, pair, event_config, settings, page_html
        ):
            return True
        if getattr(client, "_cart_blocked", False):
            warn("Cart: session blocked — not trying more pairs")
            break
        if settings.cart_retry_delay > 0:
            time.sleep(settings.cart_retry_delay)
    return False