"""Export queud extension checkout files."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from queud_aio.checkout_session import capture_basket, merge_parsed_meta
from queud_aio.client import TmptClient
from queud_aio.log_util import log
from queud_aio.queud import (
    build_queud_reserve_urls,
    build_queud_webhook_text,
    decode_queud_payload,
    queud_launcher_html,
)
from queud_aio.basket_meta import load_cart_meta, save_cart_meta
from queud_aio.proxy import pick_proxy_line
from queud_aio.settings import Settings

QUEUD_EXT_DIR = Path(__file__).resolve().parent.parent / "extensions" / "queud"


def _out_dir(settings: Settings) -> Path:
    return settings.http_session_file.parent


def write_queud_checkout_files(
    settings: Settings,
    raw_cookies: list,
    *,
    basket_url: str,
    proxy_line: str = "",
    section: str = "—",
    row: str = "—",
    seat_start: str = "—",
    seat_end: str = "—",
    price: str = "—",
    size: str = "—",
) -> Path:
    out_dir = _out_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = settings.event_targets[0]
    reserve_url, proxy_url = build_queud_reserve_urls(
        raw_cookies, basket_url, proxy_line=proxy_line
    )
    checkout_txt = out_dir / "checkout.txt"
    text = build_queud_webhook_text(
        reserve_url=reserve_url,
        proxy_url=proxy_url,
        store="Springboks TM Tickets",
        price=price,
        product=f"Event {target.event_id}",
        email=settings.sarugby_email or "—",
        quantity=settings.tickets_required,
        section=section,
        row=row,
        seat_start=seat_start,
        seat_end=seat_end,
        size=size if size != "—" else section,
    )
    checkout_txt.write_text(text + "\n", encoding="utf-8")
    (out_dir / "queud_proxy.html").write_text(
        queud_launcher_html(proxy_url), encoding="utf-8"
    )
    (out_dir / "queud_reserve.html").write_text(
        queud_launcher_html(reserve_url), encoding="utf-8"
    )
    return checkout_txt


def _write_from_snapshot(
    settings: Settings, snap, *, product: str | None = None
) -> Path:
    out_dir = _out_dir(settings)
    saved = load_cart_meta(out_dir) or {}
    meta = merge_parsed_meta(snap.parsed, saved)
    target = settings.event_targets[0]
    checkout_txt = write_queud_checkout_files(
        settings,
        snap.raw_cookies,
        basket_url=snap.basket_url,
        proxy_line=snap.proxy_line,
        section=meta["section"],
        row=meta["row"],
        seat_start=meta["seat_start"],
        seat_end=meta["seat_end"],
        price=meta["price"],
        size=meta["size"],
    )
    save_cart_meta(
        out_dir,
        {
            **meta,
            "product": product or saved.get("product", f"Event {target.event_id}"),
            "quantity": settings.tickets_required,
        },
    )
    log(
        f"checkout.txt — {meta['section']} row {meta['row']} "
        f"seats {meta['seat_start']}-{meta['seat_end']} @ {meta['price']}"
    )
    return checkout_txt


def _client_for_export(settings: Settings, client: TmptClient | None) -> TmptClient:
    if client is not None:
        return client
    proxy_line = pick_proxy_line(settings)
    return TmptClient(settings, proxy_line=proxy_line)


def refresh_checkout_metadata(
    settings: Settings,
    *,
    client: TmptClient | None = None,
) -> Path:
    out_dir = _out_dir(settings)
    checkout_txt = out_dir / "checkout.txt"
    if not checkout_txt.exists():
        raise FileNotFoundError("checkout.txt missing — cart or run --export-queud first")

    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)
    active = _client_for_export(settings, client)
    owned = client is None

    try:
        snap = capture_basket(active, settings, event_url=event_url, require_items=False)
    except RuntimeError as exc:
        if "empty" in str(exc).lower():
            log(f"{exc} — keeping existing checkout session")
            return checkout_txt
        raise
    finally:
        if owned:
            active.close()
    return _write_from_snapshot(settings, snap)


def export_queud_checkout(
    settings: Settings,
    *,
    client: TmptClient | None = None,
) -> Path:
    out_dir = _out_dir(settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)

    active = _client_for_export(settings, client)
    owned = client is None
    try:
        snap = capture_basket(
            active, settings, event_url=event_url, require_items=True
        )
    finally:
        if owned:
            active.close()

    session_b64 = unquote(snap.proxy_url.split("session=")[1].split("&endUrl=")[0])
    log(f"queud payload OK — {len(decode_queud_payload(session_b64).get('cookies') or [])} cookies")

    proxy_html = _out_dir(settings) / "queud_proxy.html"
    _write_from_snapshot(settings, snap)
    log("")
    log("=== queud extension checkout ===")
    log(f"1. Load extension: {QUEUD_EXT_DIR}")
    log(f"2. Double-click: {proxy_html}")
    log("")
    return proxy_html


def send_checkout_to_discord(settings: Settings) -> bool:
    from queud_aio.notify import send_queud_checkout_discord

    out_dir = _out_dir(settings)
    checkout_txt = out_dir / "checkout.txt"
    if not checkout_txt.exists():
        log("No checkout.txt — run: python run.py --export-queud")
        return False

    meta = load_cart_meta(out_dir) or {}
    has_seats = meta.get("section") not in ("—", "", None)
    if not has_seats:
        try:
            refresh_checkout_metadata(settings)
            checkout_txt = out_dir / "checkout.txt"
            meta = load_cart_meta(out_dir) or {}
        except Exception as exc:
            log(f"Could not refresh basket ({exc}) — using checkout.txt as-is")
    elif meta.get("seat_start") in ("—", "", None):
        log("WARNING: No seat data — run --cart-test before sending")

    send_queud_checkout_discord(checkout_txt, settings, data_dir=out_dir)
    log("Sent queud checkout embed to Discord")
    return True