"""Best Available cart API with safety filters."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from rugby_sa.availability import (
    area_id_map,
    csrf_token_from_html,
    csrf_token_from_page,
    fetch_ba_search,
    price_class_for_band,
)
from rugby_sa.log_util import log, warn
from rugby_sa.models import EventTarget, SeatPair
from rugby_sa.settings import Settings


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
        warn(f"Cart: skip {pair.section} (not in RUGBY_SA_CART_SECTIONS)")
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
    if hasattr(client, "delete"):
        client.delete(purge_url, headers=headers)
        return
    if hasattr(client, "page"):
        client.page.evaluate(
            """async ({url, headers}) => {
                await fetch(url, { method: 'DELETE', credentials: 'include', headers });
            }""",
            {"url": purge_url, "headers": headers},
        )


def _lock_attempts_for_pair(
    pair: SeatPair,
    event_config: dict[str, Any],
    search: list[dict[str, Any]],
) -> list[tuple[str, int | None, int | None]]:
    """Build BA lock attempts: preferred section, other search hits, then global."""
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

    for item in search:
        area_id = int(item.get("AreaId", 0))
        for band in item.get("PriceBands") or []:
            code = int(band.get("PriceBandCode", 0))
            if code != price_band:
                continue
            if section_area and area_id == section_area:
                add(pair.section, area_id, code)
            else:
                add(f"search area {area_id}", area_id, code)

    add("any area", None, None)
    return attempts


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
    qty = quantity or settings.tickets_required
    path = event_config.get("Urls", {}).get("LockRegularSeatsUrl", "")
    if not path or not csrf:
        return False, None, "lock url or csrf missing"
    url = f"{settings.base_url}{path}" if not path.startswith("http") else path
    body: dict[str, Any] = {
        "EventId": target.event_id,
        "Quantity": qty,
        "AreSeatsTogether": True,
        "SeatAttributeIds": [],
        "MinimumPrice": 0,
        "MaximumPrice": 10_000_000,
    }
    if price_band_id is not None:
        body["PriceBandId"] = price_band_id
    if area_id is not None:
        body["AreaId"] = area_id
    resp = client.post(url, json=body, headers=cart_api_headers(settings, page_url, csrf))
    if resp.status_code != 200:
        return False, None, f"HTTP {resp.status_code}: {resp.text[:280]}"
    try:
        return True, resp.json(), resp.text[:300]
    except json.JSONDecodeError:
        return False, None, resp.text[:300]


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
    search = fetch_ba_search(client, target, event_config, settings)
    attempts = _lock_attempts_for_pair(pair, event_config, search)
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
        if "403" in detail or "block" in detail:
            warn("Cart: Akamai block — stopping lock attempts")
            if hasattr(client, "__dict__"):
                client._cart_blocked = True
            break

    if not lock_data:
        return False

    locked = lock_data.get("LockedSeats") or []
    section_area = area_id_map(event_config).get(pair.section)
    area_label = pair.section if used_area == section_area else f"area {used_area or 'any'}"
    log(f"Cart: BA locked {len(locked)} seat(s) — {area_label}")

    if settings.cart_dry_run:
        log(f"Cart: DRY RUN — would add {pair.label()} (no basket commit)")
        return True

    count = basket_item_count(client, settings, page_url)
    if count >= settings.tickets_required:
        log(f"Cart: basket={count} — {settings.base_url}/Checkout/Basket")
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
    count = basket_item_count(client, settings, page_url)
    if count >= settings.tickets_required:
        log(f"Cart: basket={count} after PUT commit")
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
        if settings.cart_retry_delay > 0:
            time.sleep(settings.cart_retry_delay)
        if getattr(client, "_cart_blocked", False):
            break
    return False