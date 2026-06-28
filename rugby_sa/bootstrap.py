"""One-time Playwright login — optional cookie export."""

from __future__ import annotations

import os
import time

from playwright.sync_api import sync_playwright

from rugby_sa.client import TmptClient
from rugby_sa.cookies import save_cookies
from rugby_sa.headless_tmpt import playwright_proxy
from rugby_sa.log_util import log
from rugby_sa.settings import Settings


def save_session_meta(settings: Settings, proxy_line: str) -> None:
    from rugby_sa.proxy import save_session_proxy

    save_session_proxy(settings, proxy_line)


def try_sarugby_login(page, settings: Settings) -> bool:
    """Fill SA Rugby login form once. Returns True if a submit was attempted."""
    if not settings.credentials_ok():
        return False
    if "login.sarugby.co.za" not in page.url and "web-identity" not in page.url:
        return False
    log(f"Login: submitting credentials ({page.url[:90]})")
    filled = False
    for sel in ('input[type="email"]', 'input[name="username"]', "#username"):
        field = page.locator(sel).first
        if field.count():
            field.fill(settings.sarugby_email)
            filled = True
            break
    for sel in ('input[type="password"]', 'input[name="password"]', "#password"):
        field = page.locator(sel).first
        if field.count():
            field.fill(settings.sarugby_password)
            break
    if not filled:
        return False
    for sel in (
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Log in")',
        'button:has-text("Sign in")',
        'button:has-text("LOG IN")',
    ):
        btn = page.locator(sel).first
        if btn.count():
            btn.click()
            break
    try:
        page.wait_for_url(
            lambda url: "login.sarugby.co.za" not in url,
            timeout=120_000,
        )
    except Exception:
        pass
    return True


def _safe_page_content(page) -> str:
    for _ in range(5):
        try:
            return page.content()
        except Exception:
            time.sleep(1)
    return ""


def wait_for_event_page(page, settings: Settings, timeout_s: int = 180) -> bool:
    deadline = time.time() + timeout_s
    epsf_waits = 0
    login_attempted = False
    while time.time() < deadline:
        html = _safe_page_content(page)
        if "Let's Get Your Identity Verified" in html:
            epsf_waits += 1
            log("EPSF challenge — waiting...")
            if epsf_waits % 6 == 0:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=120_000)
                except Exception:
                    pass
            time.sleep(5)
            continue
        try:
            title = page.title()
            url = page.url
        except Exception:
            time.sleep(2)
            continue
        if "queue-it" in url.lower() or title == "Queue-it":
            log("Queue-it — waiting...")
            time.sleep(5)
            continue
        on_login = "login.sarugby" in url or (
            "web-identity" in url and "Login" in title
        )
        if on_login:
            if not login_attempted:
                login_attempted = try_sarugby_login(page, settings)
                if not login_attempted:
                    log("Login: waiting for OAuth redirect...")
            time.sleep(3)
            continue
        if "Event Information Screen" in title or "ism-module" in html:
            return True
        time.sleep(2)
    return False


def import_playwright_cookies(context, client: TmptClient) -> None:
    host = ".springboks.tmtickets.co.za"
    for c in context.cookies():
        domain = c.get("domain") or host
        client.session.cookies.set(
            c["name"],
            c["value"],
            domain=domain,
            path=c.get("path") or "/",
        )


def bootstrap(settings: Settings, proxy_line: str = "") -> int:
    target = settings.event_targets[0]
    event_url = target.page_url(settings.base_url)
    settings.profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        proxy_cfg = playwright_proxy(proxy_line) if proxy_line else None
        if proxy_line:
            log(f"Bootstrap: ZA proxy session {proxy_line.split('-session-', 1)[-1].split(':', 1)[0][:12]}...")
        else:
            log("Bootstrap: direct connection")

        context = None
        for channel in ("chrome", None):
            try:
                headless = os.environ.get("SPRINGBOKS_HEADLESS", "0") == "1"
                kwargs: dict = {
                    "user_data_dir": str(settings.profile_dir),
                    "headless": headless,
                    "viewport": {"width": 1400, "height": 900},
                    "locale": "en-GB",
                    "proxy": proxy_cfg,
                    "args": ["--disable-blink-features=AutomationControlled"],
                }
                if channel:
                    kwargs["channel"] = channel
                context = p.chromium.launch_persistent_context(**kwargs)
                log(f"Browser: {channel or 'chromium'} (profile {settings.profile_dir})")
                break
            except Exception as exc:
                log(f"Launch failed ({channel}): {exc}")
        if context is None:
            context = p.chromium.launch_persistent_context(
                str(settings.profile_dir),
                headless=True,
                viewport={"width": 1400, "height": 900},
            )

        page = context.pages[0] if context.pages else context.new_page()
        log(f"Opening {event_url}")
        page.goto(event_url, wait_until="domcontentloaded", timeout=120_000)

        if not wait_for_event_page(page, settings):
            if not settings.credentials_ok():
                log("Set SARUGBY_EMAIL and SARUGBY_PASSWORD")
            log(f"Failed to reach event page: {page.title()}")
            context.close()
            return 1

        log(f"Event page OK — exporting cookies to {settings.http_session_file}")
        client = TmptClient(settings, proxy_line=proxy_line)
        import_playwright_cookies(context, client)
        save_cookies(client.session, settings)
        save_session_meta(settings, proxy_line)
        context.close()

    log(f"Session saved. Use same proxy: {proxy_line or 'direct'}")
    log("Run: python run.py --cart-test")
    return 0