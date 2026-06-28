"""Export queud extension checkout files."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import unquote

from rugby_sa.browser_request import BrowserRequestClient
from rugby_sa.log_util import log
from rugby_sa.proxy import resolve_browser_proxy
from rugby_sa.queud import (
    build_queud_reserve_urls,
    build_queud_webhook_text,
    decode_queud_payload,
    queud_launcher_html,
)
from rugby_sa.settings import Settings

QUEUD_EXT_DIR = Path(__file__).resolve().parent.parent / "extensions" / "queud"


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
) -> Path:
    """Write checkout.txt + queud launcher HTML from cookie list."""
    out_dir = settings.http_session_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    target = settings.event_targets[0]

    reserve_url, proxy_url = build_queud_reserve_urls(
        raw_cookies, basket_url, proxy_line=proxy_line
    )
    checkout_txt = out_dir / "checkout.txt"
    proxy_html = out_dir / "queud_proxy.html"
    reserve_html = out_dir / "queud_reserve.html"

    checkout_txt.write_text(
        build_queud_webhook_text(
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
        )
        + "\n",
        encoding="utf-8",
    )
    proxy_html.write_text(queud_launcher_html(proxy_url), encoding="utf-8")
    reserve_html.write_text(queud_launcher_html(reserve_url), encoding="utf-8")
    return checkout_txt


def export_queud_checkout(settings: Settings) -> Path:
    """Write checkout.txt + queud_proxy.html from live browser session."""
    out_dir = settings.http_session_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)
    basket_url = f"{settings.base_url}/Checkout/Basket"

    proxy_line = resolve_browser_proxy(settings)
    with BrowserRequestClient(settings, proxy_line=proxy_line) as client:
        client.ensure_event_page(event_url)
        log(f"Opening basket: {basket_url}")
        client.page.goto(basket_url, wait_until="domcontentloaded", timeout=120_000)
        time.sleep(2)
        raw = client._context.cookies() if client._context else []
        raw = [c for c in raw if c.get("value")]
        log(f"Collected {len(raw)} cookies for queud link")

        reserve_url, proxy_url = build_queud_reserve_urls(
            raw, basket_url, proxy_line=client.proxy_line
        )

    session_b64 = unquote(proxy_url.split("session=")[1].split("&endUrl=")[0])
    payload = decode_queud_payload(session_b64)
    cookie_count = len(payload.get("cookies") or [])
    log(f"queud payload OK — {cookie_count} cookies")

    checkout_txt = out_dir / "checkout.txt"
    proxy_html = out_dir / "queud_proxy.html"
    reserve_html = out_dir / "queud_reserve.html"

    checkout_txt.write_text(
        build_queud_webhook_text(
            reserve_url=reserve_url,
            proxy_url=proxy_url,
            store="Springboks TM Tickets",
            price="—",
            product=f"Event {target.event_id}",
            email=settings.sarugby_email or "—",
            quantity=settings.tickets_required,
            section="—",
            row="—",
            seat_start="—",
            seat_end="—",
        )
        + "\n",
        encoding="utf-8",
    )
    proxy_html.write_text(queud_launcher_html(proxy_url), encoding="utf-8")
    reserve_html.write_text(queud_launcher_html(reserve_url), encoding="utf-8")

    log("")
    log("=== queud extension checkout ===")
    log(f"1. Chrome → chrome://extensions → Load unpacked → {QUEUD_EXT_DIR}")
    log("2. Use a normal Chrome window (not Incognito)")
    log(f"3. Double-click: {proxy_html}")
    log(f"4. Or copy Proxy URL from: {checkout_txt}")
    log("")

    return proxy_html


def send_checkout_to_discord(settings: Settings) -> bool:
    """Attach checkout.txt to Discord webhook."""
    from rugby_sa.notify import send_queud_checkout_discord  # Adonis-style embed

    checkout_txt = settings.http_session_file.parent / "checkout.txt"
    if not checkout_txt.exists():
        log("No checkout.txt — run: python run.py --export-queud")
        return False
    send_queud_checkout_discord(checkout_txt, settings)
    log("Sent Adonis-style queud checkout embed to Discord")
    return True