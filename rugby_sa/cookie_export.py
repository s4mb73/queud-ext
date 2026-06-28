"""Export Playwright profile cookies for manual browser checkout."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from rugby_sa.adonis import filter_checkout_cookies
from rugby_sa.queud import build_queud_reserve_urls, queud_launcher_html
from rugby_sa.queud_export import write_queud_checkout_files
from rugby_sa.browser_request import BrowserRequestClient
from rugby_sa.log_util import log
from rugby_sa.proxy import resolve_browser_proxy
from rugby_sa.settings import Settings


def playwright_cookies_to_editor(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format Playwright cookies for Cookie-Editor import."""
    return [_to_cookie_editor(c) for c in raw if c.get("value")]


def collect_checkout_session_from_client(
    client: BrowserRequestClient,
    settings: Settings,
) -> tuple[list[dict[str, Any]], str, str, str]:
    """Cookies, reserve link, proxy link, proxy line."""
    basket_url = f"{settings.base_url}/Checkout/Basket"
    client.page.goto(basket_url, wait_until="domcontentloaded", timeout=120_000)
    time.sleep(1)
    raw = client._context.cookies() if client._context else []
    raw = filter_checkout_cookies([c for c in raw if c.get("value")])
    editor = playwright_cookies_to_editor(raw)
    reserve_url, proxy_url = build_queud_reserve_urls(
        raw, basket_url, proxy_line=client.proxy_line
    )
    return editor, reserve_url, proxy_url, client.proxy_line


def collect_checkout_cookies_from_client(
    client: BrowserRequestClient,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Read live browser cookies after cart — Cookie-Editor JSON format."""
    basket_url = f"{settings.base_url}/Checkout/Basket"
    client.page.goto(basket_url, wait_until="domcontentloaded", timeout=120_000)
    time.sleep(1)
    raw = client._context.cookies() if client._context else []
    raw = filter_checkout_cookies([c for c in raw if c.get("value")])
    return playwright_cookies_to_editor(raw)


def _to_cookie_editor(cookie: dict[str, Any]) -> dict[str, Any]:
    expires = cookie.get("expires", -1)
    session = expires in (-1, None)
    same_site = cookie.get("sameSite")
    if same_site:
        same_site = str(same_site).lower()
        if same_site == "none":
            same_site = "no_restriction"
    domain = cookie.get("domain") or ""
    host_only = not domain.startswith(".")
    item: dict[str, Any] = {
        "domain": domain,
        "hostOnly": host_only,
        "httpOnly": bool(cookie.get("httpOnly")),
        "name": cookie.get("name", ""),
        "path": cookie.get("path") or "/",
        "sameSite": same_site or "unspecified",
        "secure": bool(cookie.get("secure")),
        "session": session,
        "storeId": "0",
        "value": cookie.get("value", ""),
    }
    if not session and expires and expires > 0:
        item["expirationDate"] = int(expires)
    return item


def _to_netscape_line(cookie: dict[str, Any]) -> str:
    domain = cookie.get("domain") or ""
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    host = domain.lstrip(".")
    path = cookie.get("path") or "/"
    secure = "TRUE" if cookie.get("secure") else "FALSE"
    expires = cookie.get("expires", -1)
    expiry = "0" if expires in (-1, None) else str(int(expires))
    name = cookie.get("name", "")
    value = cookie.get("value", "")
    return "\t".join([host, include_subdomains, path, secure, expiry, name, value])


def export_checkout_cookies(settings: Settings) -> Path:
    """Open basket in profile browser and export all cookies to data/."""
    out_dir = settings.http_session_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)
    basket_url = f"{settings.base_url}/Checkout/Basket"
    editor_path = out_dir / "cookies_checkout.json"
    simple_path = out_dir / "cookies_checkout_simple.json"
    netscape_path = out_dir / "cookies_checkout.txt"
    queud_html_path = out_dir / "queud_proxy.html"
    checkout_txt_path = out_dir / "checkout.txt"

    proxy = resolve_browser_proxy(settings)
    with BrowserRequestClient(settings, proxy_line=proxy) as client:
        client.ensure_event_page(event_url)
        log(f"Opening basket: {basket_url}")
        client.page.goto(basket_url, wait_until="domcontentloaded", timeout=120_000)
        time.sleep(2)
        raw = client._context.cookies() if client._context else []
        all_raw = [c for c in raw if c.get("value")]
        raw = filter_checkout_cookies(all_raw)
        log(f"Exported {len(raw)} checkout cookies ({len(all_raw)} total in browser)")
        reserve_url, proxy_url = build_queud_reserve_urls(
            all_raw, basket_url, proxy_line=client.proxy_line
        )

    editor = playwright_cookies_to_editor(raw)
    simple = [
        {
            "name": c.get("name", ""),
            "value": c.get("value", ""),
            "domain": c.get("domain", ""),
            "path": c.get("path") or "/",
        }
        for c in raw
    ]

    editor_path.write_text(json.dumps(editor, indent=2), encoding="utf-8")
    simple_path.write_text(json.dumps(simple, indent=2), encoding="utf-8")
    netscape_lines = ["# Netscape HTTP Cookie File", "# https://curl.haxx.se/docs/http-cookies.html", ""]
    netscape_lines.extend(_to_netscape_line(c) for c in raw)
    netscape_path.write_text("\n".join(netscape_lines) + "\n", encoding="utf-8")
    write_queud_checkout_files(
        settings,
        all_raw,
        basket_url=basket_url,
        proxy_line=client.proxy_line,
    )
    queud_html_path.write_text(queud_launcher_html(proxy_url), encoding="utf-8")

    log(f"queud checkout (double-click): {queud_html_path}")
    log(f"queud webhook text: {checkout_txt_path}")
    log(f"Cookie-Editor JSON: {editor_path}")
    log(f"Simple JSON (edit values): {simple_path}")
    log(f"Netscape/curl format: {netscape_path}")
    log(f"Checkout URL: {basket_url}")
    return queud_html_path