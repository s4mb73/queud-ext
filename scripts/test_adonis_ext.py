#!/usr/bin/env python3
"""Open Adonis URL in Chrome with extension loaded; report basket result."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
EXT_PATH = DATA / "adonisExtension"
EXT_FALLBACK = Path(r"C:\Users\sammy\Downloads\adonisExtension (2)")
PROFILE = DATA / "adonis_test_profile"
CHECKOUT_TXT = DATA / "checkout.txt"


def _url_from_checkout(prefix: str) -> str:
    text = CHECKOUT_TXT.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip("{}")
    raise RuntimeError(f"{prefix} not found in checkout.txt — run: python run.py --export-adonis")


def _payload_from_url(url: str) -> dict:
    from rugby_sa.adonis import decode_adonis_payload

    b64 = url.split("extension=")[1].split("&endUrl=")[0]
    return decode_adonis_payload(b64)


def _playwright_cookies_from_adonis(payload: dict) -> list[dict]:
    out: list[dict] = []
    for c in payload.get("cookies") or []:
        domain = (c.get("domain") or "").lstrip(".")
        if not domain:
            continue
        out.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": domain,
                "path": c.get("path") or "/",
                "httpOnly": bool(c.get("httponly")),
                "secure": bool(c.get("secure")),
                "sameSite": "Lax",
            }
        )
    return out


def _resolve_extension_dir() -> Path:
    if EXT_PATH.is_dir():
        return EXT_PATH
    if EXT_FALLBACK.is_dir():
        return EXT_FALLBACK
    raise FileNotFoundError(
        f"Adonis extension not found at {EXT_PATH} or {EXT_FALLBACK}"
    )


def _launch_context(pw, *, profile: Path, ext_dir: Path):
    profile.mkdir(parents=True, exist_ok=True)
    ext_arg = str(ext_dir.resolve())
    launch_kwargs: dict = {
        "user_data_dir": str(profile),
        "headless": False,
        "ignore_default_args": ["--disable-extensions"],
        "args": [
            f"--disable-extensions-except={ext_arg}",
            f"--load-extension={ext_arg}",
            "--disable-blink-features=AutomationControlled",
        ],
        "viewport": {"width": 1400, "height": 900},
    }
    try:
        ctx = pw.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
        print("Browser: system Chrome")
    except Exception as exc:
        print(f"Chrome channel unavailable ({exc}); falling back to Playwright Chromium")
        ctx = pw.chromium.launch_persistent_context(**launch_kwargs)
    return ctx


def _wait_for_basket(page, *, seconds: int = 45) -> str:
    for i in range(seconds):
        time.sleep(1)
        url = page.url
        if i % 5 == 0:
            print(f"  [{i}s] {url[:100]}...")
        if "springboks.tmtickets.co.za" in url and "adonisbots.com" not in url:
            return url
    return page.url


def _report(page, context) -> int:
    title = page.title()
    url = page.url
    body = page.content().lower()

    on_basket = "/checkout/basket" in url.lower()
    has_login = "web-identity" in url or "login.sarugby" in url
    empty_basket = "your basket is empty" in body or "basket is empty" in body
    has_tickets = "remove" in body or "ticket" in body or "block" in body

    print(f"Final URL: {url[:120]}...")
    print(f"Title: {title}")
    print(f"On basket page: {on_basket}")
    print(f"Login required: {has_login}")
    print(f"Empty basket: {empty_basket}")
    print(f"Likely has tickets: {has_tickets}")

    cookies = context.cookies()
    tm_cookies = [c for c in cookies if "tmtickets" in c.get("domain", "")]
    print(f"TM cookies in browser: {len(tm_cookies)}")

    if on_basket and not has_login and not empty_basket:
        print("RESULT: PASS — reached basket with items")
        return 0
    if on_basket and not has_login:
        print("RESULT: PARTIAL — on basket but may be empty or unknown state")
        return 2
    print("RESULT: FAIL — did not land on logged-in basket")
    return 1


def test_extension(url: str, *, label: str, ext_dir: Path) -> int:
    print(f"\n=== Extension test ({label}) ===")
    print(f"URL length: {len(url)}")

    with sync_playwright() as pw:
        context = _launch_context(pw, profile=PROFILE, ext_dir=ext_dir)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto("chrome://extensions", timeout=30_000)
                time.sleep(1)
                ext_loaded = "Adonis" in page.inner_text("body")
                print(f"Extension visible on chrome://extensions: {ext_loaded}")
            except Exception as exc:
                print(f"chrome://extensions check skipped: {exc}")

            sw = context.service_workers
            print(f"Service workers: {len(sw)}")

            page = context.pages[0] if context.pages else context.new_page()
            print("Navigating to Adonis URL...")
            page.goto(url, wait_until="domcontentloaded", timeout=120_000)
            _wait_for_basket(page)
            return _report(page, context)
        finally:
            context.close()


def test_manual_cookies(url: str) -> int:
    """Control: inject cookies like Adonis would, then open basket (no extension)."""
    print("\n=== Manual cookie inject (control) ===")
    payload = _payload_from_url(url)
    end_url = unquote(url.split("endUrl=")[1].split("&proxy=")[0].split("&userAgent=")[0])
    cookies = _playwright_cookies_from_adonis(payload)
    print(f"Injecting {len(cookies)} cookies → {end_url}")

    profile = DATA / "adonis_manual_profile"
    with sync_playwright() as pw:
        profile.mkdir(parents=True, exist_ok=True)
        context = pw.chromium.launch_persistent_context(
            str(profile),
            channel="chrome",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            context.add_cookies(cookies)
            page.goto(end_url, wait_until="domcontentloaded", timeout=120_000)
            time.sleep(5)
            return _report(page, context)
        finally:
            context.close()


def main() -> int:
    if not CHECKOUT_TXT.exists():
        print("Missing checkout.txt — run: python run.py --export-adonis")
        return 1

    ext_dir = _resolve_extension_dir()
    print(f"Extension: {ext_dir}")
    print(f"Profile: {PROFILE}")

    reserve_url = _url_from_checkout("Successful reserve {")
    proxy_url = _url_from_checkout("Proxy URL {")

    # Control first — proves cookies/session still valid
    manual_rc = test_manual_cookies(reserve_url)

    # Extension: try reserve (no proxy) then proxy URL
    ext_rc = test_extension(reserve_url, label="reserve, no proxy", ext_dir=ext_dir)
    if ext_rc != 0:
        ext_rc = test_extension(proxy_url, label="proxy URL", ext_dir=ext_dir)

    print("\n=== Summary ===")
    print(f"Manual cookie inject: {'PASS' if manual_rc == 0 else 'FAIL/PARTIAL' if manual_rc == 2 else 'FAIL'}")
    print(f"Adonis extension:     {'PASS' if ext_rc == 0 else 'FAIL/PARTIAL' if ext_rc == 2 else 'FAIL'}")
    if manual_rc == 0 and ext_rc != 0:
        print("")
        print("Link payload is valid (manual inject reached basket).")
        print("Extension did not run in this automated Chrome profile.")
        print("Manual test: chrome://extensions → Load unpacked →", ext_dir)
        print("Then double-click:", DATA / "adonis_proxy.html")
    return ext_rc if manual_rc == 0 else manual_rc


if __name__ == "__main__":
    sys.exit(main())