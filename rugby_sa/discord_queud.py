"""Adonis-style queud checkout embeds + launcher hosting for Discord."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import requests as http_requests

from rugby_sa.basket_meta import load_cart_meta
from rugby_sa.queud import parse_queud_checkout_url, queud_discord_launcher_html
from rugby_sa.settings import Settings, DATA_DIR

QUEUD_EMBED_COLOR = 0x3498DB
QUEUD_VERSION = "1.3.5"


def parse_checkout_metadata(text: str) -> dict[str, str]:
    """Parse checkout.txt body (Adonis webhook layout)."""
    meta: dict[str, str] = {}
    label_keys = {
        "Store": "store",
        "Price": "price",
        "Size": "size",
        "Product": "product",
        "Payment Method": "payment_method",
        "Mode": "mode",
        "Email": "email",
        "Quantity": "quantity",
    }
    lines = [ln.strip() for ln in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("Successful reserve {"):
            meta["reserve_url"] = line[len("Successful reserve ") :].strip("{}")
        elif line.startswith("Proxy URL {"):
            meta["proxy_url"] = line[len("Proxy URL ") :].strip("{}")
        elif line == "Seat Data":
            block: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].startswith(("Sec:", "Row:", "Seats:")):
                block.append(lines[j])
                j += 1
            meta["seat_data"] = "\n".join(block) if block else "—"
            i = j
            continue
        elif line in label_keys and i + 1 < len(lines):
            meta[label_keys[line]] = lines[i + 1]
            i += 2
            continue
        i += 1
    return meta


def _discord_field(name: str, value: str, *, inline: bool = True) -> dict[str, Any]:
    return {"name": name, "value": (value or "—")[:1024], "inline": inline}


def build_adonis_style_queud_embed(
    meta: dict[str, str],
    *,
    reserve_click_url: str,
    proxy_click_url: str,
    settings: Settings,
    thumbnail_url: str = "",
) -> dict[str, Any]:
    """Match Adonis bot card: Successful reserve title + Proxy URL + field grid."""
    seat_data = meta.get("seat_data") or "—"
    stamp = datetime.now().strftime("%d/%m/%Y, %H:%M")
    embed: dict[str, Any] = {
        "title": "Successful reserve",
        "url": reserve_click_url,
        "description": f"[Proxy URL]({proxy_click_url})",
        "color": QUEUD_EMBED_COLOR,
        "fields": [
            _discord_field("Store", meta.get("store", "—")),
            _discord_field("Price", meta.get("price", "—")),
            _discord_field("Size", meta.get("size", "—")),
            _discord_field("Product", meta.get("product", "—")),
            _discord_field("Payment Method", meta.get("payment_method", "—")),
            _discord_field("Mode", meta.get("mode", "—")),
            _discord_field("Email", meta.get("email", "—")),
            _discord_field("Quantity", meta.get("quantity", "—")),
            _discord_field("Seat Data", seat_data, inline=False),
        ],
        "footer": {
            "text": f"queud {QUEUD_VERSION} · {stamp}",
            "icon_url": settings.discord_footer_icon,
        },
    }
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}
    return embed


def _webhook_wait_url(webhook: str) -> str:
    if "wait=true" in webhook:
        return webhook
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}wait=true"


def _discord_webhook(settings: Settings) -> str:
    from rugby_sa.notify import discord_webhook_url

    url = discord_webhook_url(settings)
    if not url:
        raise RuntimeError("No Discord webhook configured")
    return url


def host_launchers_on_discord_cdn(
    settings: Settings,
    *,
    proxy_html: bytes,
    reserve_html: bytes,
) -> tuple[str, str]:
    """One background upload; return cdn.discordapp.com URLs for both launchers."""
    webhook = _discord_webhook(settings)
    resp = http_requests.post(
        _webhook_wait_url(webhook),
        files={
            "files[0]": ("queud-checkout.html", proxy_html, "text/html"),
            "files[1]": ("queud-reserve.html", reserve_html, "text/html"),
        },
        timeout=settings.request_timeout,
    )
    resp.raise_for_status()
    by_name: dict[str, str] = {}
    for att in resp.json().get("attachments", []):
        url = att.get("url") or ""
        if "cdn.discordapp.com/attachments/" in url:
            by_name[att.get("filename", "")] = url
    proxy_click = by_name.get("queud-checkout.html", "")
    reserve_click = by_name.get("queud-reserve.html", "")
    if not proxy_click or not reserve_click:
        raise RuntimeError("Discord CDN upload did not return launcher URLs")
    return reserve_click, proxy_click


def host_launchers_external(
    *,
    proxy_html: bytes,
    reserve_html: bytes,
) -> tuple[str, str]:
    reserve_click = http_requests.post(
        "https://0x0.st",
        files={"file": ("queud-reserve.html", reserve_html, "text/html")},
        timeout=60,
    )
    reserve_click.raise_for_status()
    proxy_click = http_requests.post(
        "https://0x0.st",
        files={"file": ("queud-checkout.html", proxy_html, "text/html")},
        timeout=60,
    )
    proxy_click.raise_for_status()
    reserve_url = reserve_click.text.strip()
    proxy_url = proxy_click.text.strip()
    if not reserve_url.startswith("http") or not proxy_url.startswith("http"):
        raise RuntimeError("External launcher host returned invalid URL")
    return reserve_url, proxy_url


def build_launcher_click_urls(
    settings: Settings,
    *,
    reserve_url: str,
    proxy_url: str,
) -> tuple[str, str]:
    """Short checkout URLs — Carbon-style API when QUEUD_API_BASE is set."""
    if settings.queud_api_base:
        from rugby_sa.basket_api import register_checkout_pair

        return register_checkout_pair(
            settings, reserve_url=reserve_url, proxy_url=proxy_url
        )

    from rugby_sa.log_util import log

    log(
        "QUEUD_API_BASE not set — Discord links need your API domain. "
        "Run: python run.py --queud-api  then set QUEUD_API_BASE in .env"
    )
    proxy_session, end_url, proxy_cred = parse_queud_checkout_url(proxy_url)
    reserve_session, _, _ = parse_queud_checkout_url(reserve_url)
    proxy_html = queud_discord_launcher_html(
        proxy_session, end_url, proxy=proxy_cred
    ).encode("utf-8")
    reserve_html = queud_discord_launcher_html(reserve_session, end_url).encode(
        "utf-8"
    )
    try:
        return host_launchers_on_discord_cdn(
            settings, proxy_html=proxy_html, reserve_html=reserve_html
        )
    except Exception:
        return host_launchers_external(proxy_html=proxy_html, reserve_html=reserve_html)


def build_queud_webhook_payload(
    settings: Settings,
    checkout_text: str,
    *,
    thumbnail_url: str = "",
    cookie_editor_json: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[str, bytes, str]] | None]:
    meta = parse_checkout_metadata(checkout_text)
    saved = load_cart_meta(DATA_DIR) or {}
    if meta.get("price") in ("—", "", None) and saved.get("price"):
        meta["price"] = saved["price"]
    if meta.get("size") in ("—", "", None) and saved.get("size"):
        meta["size"] = saved["size"]
    seat_data = meta.get("seat_data", "")
    if "Sec: —" in seat_data and saved.get("section"):
        seats = (
            f"[{saved['seat_start']}]"
            if saved.get("seat_start") == saved.get("seat_end")
            else f"[{saved.get('seat_start', '—')} - {saved.get('seat_end', '—')}]"
        )
        meta["seat_data"] = "\n".join(
            [
                f"Sec: {saved.get('section', '—')}",
                f"Row: {saved.get('row', '—')}",
                f"Seats: {seats}",
            ]
        )
    reserve_url = meta.get("reserve_url", "")
    proxy_url = meta.get("proxy_url", "")
    if not reserve_url or not proxy_url:
        raise RuntimeError("checkout.txt missing reserve/proxy URLs")

    reserve_click, proxy_click = build_launcher_click_urls(
        settings, reserve_url=reserve_url, proxy_url=proxy_url
    )
    embed = build_adonis_style_queud_embed(
        meta,
        reserve_click_url=reserve_click,
        proxy_click_url=proxy_click,
        settings=settings,
        thumbnail_url=thumbnail_url,
    )
    payload: dict[str, Any] = {
        "username": "queud",
        "embeds": [embed],
    }
    files = None
    if cookie_editor_json:
        files = {
            "files[0]": (
                "cookies_checkout.json",
                json.dumps(cookie_editor_json, indent=2).encode("utf-8"),
                "application/json",
            )
        }
    return payload, files


def send_queud_checkout_discord_message(
    settings: Settings,
    checkout_text: str,
    *,
    thumbnail_url: str = "",
    cookie_editor_json: list[dict[str, Any]] | None = None,
) -> None:
    """Post Adonis-style queud embed (no HTML file attachments on this message)."""
    webhook = _discord_webhook(settings)
    payload, files = build_queud_webhook_payload(
        settings,
        checkout_text,
        thumbnail_url=thumbnail_url,
        cookie_editor_json=cookie_editor_json,
    )
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