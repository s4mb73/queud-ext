"""Monitor loop, snapshots, state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from queud_aio.availability import (
    fetch_availability,
    fetch_event_config,
    parse_availability,
    parse_event_metadata,
    parse_event_page,
    price_labels_from_config,
)
from queud_aio.cart import cart_best_pair
from queud_aio.checkout_session import capture_basket, merge_parsed_meta
from queud_aio.basket_meta import save_cart_meta
from queud_aio.queud_export import write_queud_checkout_files
from queud_aio.client import TmptClient
from queud_aio.log_util import log
from queud_aio.models import EventSnapshot, EventTarget
from queud_aio.notify import send_stock_alert
from queud_aio.proxy import pick_proxy_line
from queud_aio.session import ensure_page_access
from queud_aio.settings import Settings
from queud_aio.wreq_adapter import PROXY_ERRORS


def _load_event_data(
    client: TmptClient,
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
            carted = cart_best_pair(
                client,
                target,
                pairs,
                event_config,
                settings,
                page_html,
                price_labels,
            )
    except Exception as exc:
        log(f"Event {target.event_id} availability error: {exc}")
    return pairs, total_available, carted, price_labels


def fetch_event_snapshot(
    client: TmptClient,
    target: EventTarget,
    settings: Settings,
) -> EventSnapshot:
    page_url = target.page_url(settings.base_url)
    resp, final_url = ensure_page_access(client, page_url, settings)
    title, blocked, needs_login = parse_event_page(resp.text)

    pairs = []
    total_available = 0
    carted = False
    price_labels: dict[int, str] = {}

    if not blocked and not needs_login and "web-identity" not in final_url:
        pairs, total_available, carted, price_labels = _load_event_data(
            client, target, settings, resp.text
        )
        if carted:
            try:
                snap = capture_basket(client, settings, require_items=False)
                pair = getattr(client, "_last_carted_pair", None) or (
                    pairs[0] if pairs else None
                )
                meta = merge_parsed_meta(snap.parsed, {})
                if pair:
                    if meta["section"] == "—":
                        meta["section"] = pair.section
                    if meta["row"] == "—":
                        meta["row"] = pair.row
                    if meta["seat_start"] == "—":
                        meta["seat_start"] = pair.seat_start
                    if meta["seat_end"] == "—":
                        meta["seat_end"] = pair.seat_end
                    if meta["price"] == "—":
                        meta["price"] = price_labels.get(pair.price_level, "—")
                    if meta["size"] == "—":
                        meta["size"] = pair.section
                write_queud_checkout_files(
                    settings,
                    snap.raw_cookies,
                    basket_url=snap.basket_url,
                    proxy_line=snap.proxy_line,
                    **{k: meta[k] for k in ("section", "row", "seat_start", "seat_end", "price", "size")},
                )
                save_cart_meta(
                    settings.http_session_file.parent,
                    {**meta, "product": f"Event {target.event_id}", "quantity": settings.tickets_required},
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
        settings=snapshot.settings,
    )


def fetch_all_snapshots(
    client: TmptClient,
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
    client: TmptClient | None = None,
    *,
    notify: bool = False,
    targets: tuple[EventTarget, ...] | None = None,
) -> tuple[int, list[EventSnapshot]]:
    targets = targets or settings.event_targets
    tried: set[str] = set()
    snapshots: list[EventSnapshot] | None = None
    last_error: Exception | None = None

    if client is None:
        for attempt in range(1, settings.proxy_max_retries + 1):
            proxy_line = pick_proxy_line(settings, exclude=tried)
            if proxy_line:
                tried.add(proxy_line)
            client = TmptClient(settings, proxy_line=proxy_line)
            try:
                snapshots = fetch_all_snapshots(client, targets, settings)
                client.persist()
                break
            except PROXY_ERRORS as exc:
                last_error = exc
                log(f"Proxy failed (attempt {attempt}/{settings.proxy_max_retries}): {exc}")
                client.close()
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