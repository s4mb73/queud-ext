"""Discord and ntfy notifications."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests as http_requests

from rugby_sa.log_util import log
from rugby_sa.models import EventSnapshot
from rugby_sa.settings import Settings


def discord_webhook_url(settings: Settings) -> str:
    if settings.discord_webhook_url:
        return settings.discord_webhook_url
    if settings.discord_webhook_file.exists():
        return settings.discord_webhook_file.read_text(encoding="utf-8").strip()
    return ""


def _discord_field(name: str, value: str, inline: bool = True) -> dict[str, Any]:
    text = (value or "—").strip() or "—"
    return {"name": name, "value": text[:1024], "inline": inline}


def _parse_zar_amount(price: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", price.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _format_zar(amount: float) -> str:
    return f"R{amount:,.2f}"


def build_discord_embed(
    snapshot: EventSnapshot,
    settings: Settings,
    *,
    test: bool = False,
) -> dict[str, Any]:
    pair = snapshot.best_pair()
    qty = settings.tickets_required
    section = row = seats = price = total_price = "—"
    if pair:
        qty = min(pair.seat_count, settings.tickets_required)
        section = pair.section
        row = pair.row
        seats = (
            pair.seat_start
            if pair.seat_start == pair.seat_end
            else f"{pair.seat_start}–{pair.seat_end}"
        )
        price = snapshot.price_for_pair(pair)
        unit = _parse_zar_amount(price)
        if unit is not None:
            total_price = _format_zar(unit * qty)

    game = snapshot.event_display_name()
    description = f"**{game}**\n{snapshot.venue or 'Venue TBC'} · {snapshot.event_date or 'Date TBC'}"
    if snapshot.carted:
        description += (
            f"\n\n✅ **Added to basket** — [Open cart]({settings.base_url}/Checkout/Basket)"
        )
        if snapshot.checkout_cookies:
            description += (
                "\n\n📎 **Cookie-Editor:** import attached `cookies_checkout.json` "
                f"while on `{settings.base_url}`, then open the basket link."
            )

    if test:
        description = f"**[TEST]** {description}"

    embed: dict[str, Any] = {
        "title": "Tickets Available",
        "description": description[:4096],
        "color": settings.discord_embed_color,
        "url": snapshot.target.page_url(settings.base_url),
        "fields": [
            _discord_field("Section", section),
            _discord_field("Row", row),
            _discord_field("Seats", seats),
            _discord_field("Price (ea)", price),
            _discord_field("Qty", str(qty)),
            _discord_field("Total", total_price),
        ],
        "footer": {
            "text": f"{settings.discord_footer_text} · Event {snapshot.target.event_id}",
            "icon_url": settings.discord_footer_icon,
        },
    }
    if snapshot.event_image:
        embed["thumbnail"] = {"url": snapshot.event_image}
    return embed


def send_discord_embed(
    embed: dict[str, Any],
    settings: Settings,
    *,
    cookie_editor_json: list[dict[str, Any]] | None = None,
    extra_files: list[tuple[str, bytes, str]] | None = None,
    extra_embeds: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any]] | None = None,
) -> None:
    webhook = discord_webhook_url(settings)
    if not webhook:
        return
    payload: dict[str, Any] = {"embeds": [embed, *(extra_embeds or [])]}
    if components:
        payload["components"] = components
    files: dict[str, tuple[str, bytes, str]] = {}
    if cookie_editor_json:
        files["files[0]"] = (
            "cookies_checkout.json",
            json.dumps(cookie_editor_json, indent=2).encode("utf-8"),
            "application/json",
        )
    if extra_files:
        start = len(files)
        for i, file_tuple in enumerate(extra_files):
            files[f"files[{start + i}]"] = file_tuple
    if files:
        http_requests.post(
            webhook,
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=settings.request_timeout,
        ).raise_for_status()
        return
    http_requests.post(
        webhook, json=payload, timeout=settings.request_timeout
    ).raise_for_status()


def send_queud_checkout_discord(checkout_txt_path: Path, settings: Settings) -> None:
    """Send Adonis-style queud embed (Successful reserve + Proxy URL + fields)."""
    from rugby_sa.discord_queud import send_queud_checkout_discord_message

    text = checkout_txt_path.read_text(encoding="utf-8")
    thumbnail = (
        "https://media.tmtickets.co.uk/za_springboks/en-gb/assets/"
        "event.42.150x60.png?etag=b2c30ca8c343a9cc435fd7588cb7e4de"
    )
    send_queud_checkout_discord_message(settings, text, thumbnail_url=thumbnail)


def send_ntfy_notification(title: str, message: str, settings: Settings) -> None:
    if settings.ntfy_topic.endswith("CHANGE-ME"):
        return
    http_requests.post(
        settings.ntfy_url,
        data=message.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "ticket"},
        timeout=settings.request_timeout,
    ).raise_for_status()


def send_stock_alert(
    snapshot: EventSnapshot,
    settings: Settings | None = None,
    *,
    test: bool = False,
) -> None:
    settings = settings or snapshot.settings or Settings.load()
    sent = False
    if discord_webhook_url(settings):
        cookies = snapshot.checkout_cookies if snapshot.carted else None
        checkout_file = settings.http_session_file.parent / "checkout.txt"
        if snapshot.carted and checkout_file.exists():
            try:
                from rugby_sa.discord_queud import send_queud_checkout_discord_message

                send_queud_checkout_discord_message(
                    settings,
                    checkout_file.read_text(encoding="utf-8"),
                    thumbnail_url=snapshot.event_image or "",
                    cookie_editor_json=cookies,
                )
                sent = True
            except Exception as exc:
                log(f"queud Discord embed failed: {exc}")

        if not sent:
            send_discord_embed(
                build_discord_embed(snapshot, settings, test=test),
                settings,
                cookie_editor_json=cookies,
            )
            sent = True
    if not settings.ntfy_topic.endswith("CHANGE-ME"):
        send_ntfy_notification(
            f"Springboks event {snapshot.event_id} — adjacent seats",
            "\n".join(snapshot.summary_lines()),
            settings,
        )
        sent = True
    if not sent:
        log("No notification channel configured — skipping alert")