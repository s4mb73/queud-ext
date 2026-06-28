"""Monitor loop, snapshots, state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from curl_cffi.requests.exceptions import ProxyError

from rugby_sa.availability import (
    fetch_availability,
    fetch_event_config,
    parse_availability,
    parse_event_metadata,
    parse_event_page,
    price_labels_from_config,
)
from rugby_sa.cart import cart_best_pair
from rugby_sa.browser_request import BrowserRequestClient
from rugby_sa.cookie_export import collect_checkout_cookies_from_client
from rugby_sa.basket_meta import parse_basket_html, save_cart_meta
from rugby_sa.queud_export import write_queud_checkout_files
from rugby_sa.client import TmptClient
from rugby_sa.log_util import log
from rugby_sa.models import EventSnapshot, EventTarget
from rugby_sa.notify import send_stock_alert
from rugby_sa.proxy import pick_proxy_line, resolve_browser_proxy
from rugby_sa.session import ensure_page_access
from rugby_sa.settings import Settings


def _load_event_data(
    client: TmptClient | BrowserRequestClient,
    target: EventTarget,
    settings: Settings,
    page_html: str,
) -> tuple[list, int, bool, dict[int, str]]:
    pairs: list = []
    total_available = 0
    carted = False
    price_labels: dict[int, str] = {}
    try:
        event_config = fetch_event_config(client, target, settings)
        availability = fetch_availability(client, target, event_config, settings)
        pairs, total_available = parse_availability(
            availability, settings.tickets_required
        )
        price_labels = price_labels_from_config(event_config)
        if pairs and settings.auto_cart:
            cart_html = page_html
            if isinstance(client, BrowserRequestClient):
                cart_html = client.page.content()
            carted = cart_best_pair(
                client,
                target,
                pairs,
                event_config,
                settings,
                cart_html,
                price_labels,
            )
    except Exception as exc:
        log(f"Event {target.event_id} availability error: {exc}")
    return pairs, total_available, carted, price_labels


def fetch_event_snapshot(
    client: TmptClient | BrowserRequestClient,
    target: EventTarget,
    settings: Settings,
) -> EventSnapshot:
    page_url = target.page_url(settings.base_url)
    if isinstance(client, BrowserRequestClient):
        resp, final_url = client.ensure_event_page(page_url)
    else:
        resp, final_url = ensure_page_access(client, page_url, settings)
    title, blocked, needs_login = parse_event_page(resp.text)

    pairs = []
    total_available = 0
    carted = False
    price_labels: dict[int, str] = {}

    checkout_cookies = None
    if not blocked and not needs_login and "web-identity" not in final_url:
        pairs, total_available, carted, price_labels = _load_event_data(
            client, target, settings, resp.text
        )
        if carted and isinstance(client, BrowserRequestClient):
            try:
                checkout_cookies = collect_checkout_cookies_from_client(
                    client, settings
                )
                log(f"Collected {len(checkout_cookies)} cookies for webhook export")
                raw = client._context.cookies() if client._context else []
                raw = [c for c in raw if c.get("value")]
                pair = getattr(client, "_last_carted_pair", None) or (
                    pairs[0] if pairs else None
                )
                basket_html = client.page.content()
                parsed = parse_basket_html(basket_html)
                section = parsed["section"]
                row = parsed["row"]
                seat_start = parsed["seat_start"]
                seat_end = parsed["seat_end"]
                price = parsed["price"]
                size = parsed["size"]
                if pair:
                    if section == "—":
                        section = pair.section
                    if row == "—":
                        row = pair.row
                    if seat_start == "—":
                        seat_start = pair.seat_start
                    if seat_end == "—":
                        seat_end = pair.seat_end
                    if price == "—":
                        price = price_labels.get(pair.price_level, "—")
                    if size == "—":
                        size = pair.section
                write_queud_checkout_files(
                    settings,
                    raw,
                    basket_url=f"{settings.base_url}/Checkout/Basket",
                    proxy_line=client.proxy_line,
                    section=section,
                    row=row,
                    seat_start=seat_start,
                    seat_end=seat_end,
                    price=price,
                    size=size,
                )
                save_cart_meta(
                    settings.http_session_file.parent,
                    {
                        "section": section,
                        "row": row,
                        "seat_start": seat_start,
                        "seat_end": seat_end,
                        "price": price,
                        "size": size,
                        "product": f"Event {target.event_id}",
                        "quantity": settings.tickets_required,
                    },
                )
                log("Wrote queud checkout.txt for Discord")
            except Exception as exc:
                log(f"Cookie export for webhook failed: {exc}")

    return EventSnapshot(
        target=target,
        url=final_url,
        title=title,
        blocked=blocked,
        needs_login=needs_login or "web-identity" in final_url,
        pairs=pairs,
        total_available_seats=total_available,
        carted=carted,
        price_labels=price_labels,
        checkout_cookies=checkout_cookies,
        settings=settings,
    )


def fetch_events_index_html(client: TmptClient, settings: Settings) -> str:
    resp = client.get(f"{settings.base_url}/Events/Index", allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def enrich_snapshot_metadata(
    snapshot: EventSnapshot, events_html: str
) -> EventSnapshot:
    if not events_html:
        return snapshot
    name, date, venue, image = parse_event_metadata(
        events_html, snapshot.event_id
    )
    if name:
        log(f"Event {snapshot.event_id}: {name} @ {venue} — {date}")
    return EventSnapshot(
        target=snapshot.target,
        url=snapshot.url,
        title=snapshot.title,
        blocked=snapshot.blocked,
        needs_login=snapshot.needs_login,
        pairs=snapshot.pairs,
        total_available_seats=snapshot.total_available_seats,
        carted=snapshot.carted,
        price_labels=snapshot.price_labels,
        event_name=name or snapshot.event_name,
        event_date=date or snapshot.event_date,
        venue=venue or snapshot.venue,
        event_image=image or snapshot.event_image,
        checkout_cookies=snapshot.checkout_cookies,
        settings=snapshot.settings,
    )


def fetch_all_snapshots(
    client: TmptClient | BrowserRequestClient,
    targets: tuple[EventTarget, ...],
    settings: Settings,
) -> list[EventSnapshot]:
    snapshots: list[EventSnapshot] = []
    for target in targets:
        log(f"Checking event {target.event_id} (position={target.position})...")
        snapshots.append(fetch_event_snapshot(client, target, settings))
    try:
        events_html = fetch_events_index_html(client, settings)
        snapshots = [enrich_snapshot_metadata(s, events_html) for s in snapshots]
    except Exception as exc:
        log(f"Events list metadata unavailable: {exc}")
    return snapshots


def load_state(settings: Settings) -> dict[str, Any]:
    path = settings.state_file
    if not path.exists():
        return {"events": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"events": {}}
    if "events" not in raw and raw.get("fingerprint"):
        first = settings.event_targets[0]
        raw = {
            "events": {
                str(first.event_id): {
                    "fingerprint": raw.get("fingerprint"),
                    "updated_at": raw.get("updated_at"),
                    "summary": raw.get("summary", []),
                }
            }
        }
    raw.setdefault("events", {})
    return raw


def save_event_state(state: dict[str, Any], snapshot: EventSnapshot) -> None:
    state["events"][snapshot.target.key()] = {
        "fingerprint": snapshot.fingerprint(),
        "updated_at": datetime.now().isoformat(),
        "summary": snapshot.summary_lines(),
        "has_target_stock": snapshot.has_target_stock(),
    }


def event_changed(state: dict[str, Any], snapshot: EventSnapshot) -> bool:
    prev = state["events"].get(snapshot.target.key(), {})
    if not prev.get("fingerprint"):
        return False
    return prev["fingerprint"] != snapshot.fingerprint()


def run_check(
    settings: Settings,
    client: TmptClient | BrowserRequestClient | None = None,
    *,
    notify: bool = False,
    targets: tuple[EventTarget, ...] | None = None,
) -> tuple[int, list[EventSnapshot]]:
    targets = targets or settings.event_targets
    tried: set[str] = set()
    snapshots: list[EventSnapshot] | None = None
    last_error: Exception | None = None

    if client is None:
        if settings.use_browser_requests:
            proxy_line = resolve_browser_proxy(settings)
            browser = BrowserRequestClient(settings, proxy_line=proxy_line)
            browser.start()
            try:
                snapshots = fetch_all_snapshots(browser, targets, settings)
                browser.persist()
                return _finalize_check(settings, snapshots, notify)
            finally:
                browser.close()

        for attempt in range(1, settings.proxy_max_retries + 1):
            proxy_line = pick_proxy_line(settings, exclude=tried)
            if proxy_line:
                tried.add(proxy_line)
            client = TmptClient(settings, proxy_line=proxy_line)
            try:
                snapshots = fetch_all_snapshots(client, targets, settings)
                client.persist()
                break
            except ProxyError as exc:
                last_error = exc
                log(f"Proxy failed (attempt {attempt}/{settings.proxy_max_retries}): {exc}")
                if settings.proxy_is_fixed or attempt >= settings.proxy_max_retries:
                    raise
            except Exception:
                client.persist()
                raise
        if snapshots is None:
            raise RuntimeError(f"All proxy attempts failed: {last_error}")
    else:
        snapshots = fetch_all_snapshots(client, targets, settings)
        client.persist()

    return _finalize_check(settings, snapshots, notify)


def _finalize_check(
    settings: Settings,
    snapshots: list[EventSnapshot],
    notify: bool,
) -> tuple[int, list[EventSnapshot]]:

    state = load_state(settings)
    return _process_snapshots(settings, snapshots, state, notify)


def _process_snapshots(
    settings: Settings,
    snapshots: list[EventSnapshot],
    state: dict[str, Any],
    notify: bool,
) -> tuple[int, list[EventSnapshot]]:
    any_change = any_stock = baseline_saved = False

    for snapshot in snapshots:
        for line in snapshot.summary_lines():
            log(line)
        log("")
        if snapshot.has_target_stock():
            any_stock = True
        prev = state["events"].get(snapshot.target.key())
        if not prev or not prev.get("fingerprint"):
            save_event_state(state, snapshot)
            log(f"Event {snapshot.event_id}: baseline saved")
            baseline_saved = True
            continue
        if event_changed(state, snapshot):
            any_change = True
            log(f"Event {snapshot.event_id}: change detected")
            if notify and snapshot.has_target_stock():
                try:
                    send_stock_alert(snapshot, settings)
                    log(f"Event {snapshot.event_id}: alert sent")
                except Exception as exc:
                    log(f"Event {snapshot.event_id}: notification failed: {exc}")
            save_event_state(state, snapshot)

    settings.state_file.parent.mkdir(parents=True, exist_ok=True)
    settings.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if baseline_saved and not any_change:
        return 0, snapshots
    if any_change:
        return (2 if any_stock else 1), snapshots
    log("No changes across monitored events")
    return 0, snapshots