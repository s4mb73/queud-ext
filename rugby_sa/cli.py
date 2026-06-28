"""CLI entrypoints."""

from __future__ import annotations

import argparse
import os
import sys
import time

from curl_cffi.requests.exceptions import ProxyError

from rugby_sa.bootstrap import bootstrap
from rugby_sa.adonis_export import export_adonis_checkout
from rugby_sa.queud_export import export_queud_checkout, send_checkout_to_discord
from rugby_sa.cookie_export import export_checkout_cookies
from rugby_sa.browser_request import BrowserRequestClient
from rugby_sa.client import TmptClient
from rugby_sa.log_util import log
from rugby_sa.models import EventSnapshot, SeatPair
from rugby_sa.monitor import run_check
from rugby_sa.notify import send_stock_alert
from rugby_sa.headless_tmpt import HeadlessTmptSolver, get_tmpt_pool
from rugby_sa.proxy import (
    load_proxy_pool,
    pick_proxy_line,
    resolve_browser_proxy,
)
from rugby_sa.settings import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rugby SA — Springboks ticket monitor")
    parser.add_argument("--check", action="store_true", help="Single availability check")
    parser.add_argument("--monitor", action="store_true", help="Poll loop")
    parser.add_argument("--test-alert", action="store_true", help="Send test Discord alert")
    parser.add_argument("--cart-test", action="store_true", help="Check + attempt add-to-cart")
    parser.add_argument("--bootstrap", action="store_true", help="Playwright login (optional)")
    parser.add_argument(
        "--export-cookies",
        action="store_true",
        help="Export browser profile cookies for manual checkout (Cookie-Editor JSON)",
    )
    parser.add_argument(
        "--export-adonis",
        action="store_true",
        help="Export Adonis extension checkout links (legacy)",
    )
    parser.add_argument(
        "--export-queud",
        action="store_true",
        help="Export queud extension checkout links (checkout.txt + queud_proxy.html)",
    )
    parser.add_argument(
        "--send-queud-discord",
        action="store_true",
        help="Send checkout.txt to Discord webhook",
    )
    parser.add_argument(
        "--queud-api",
        action="store_true",
        help="Run queud basket API (short /basket/{uuid} links for Discord)",
    )
    parser.add_argument(
        "--solve-tmpt",
        action="store_true",
        help="Headless tmpt solve once (prints cookie status)",
    )
    parser.add_argument(
        "--warm-tmpt",
        action="store_true",
        help="Pre-fill headless tmpt pool for proxy lines",
    )
    return parser


def cmd_solve_tmpt(settings: Settings) -> int:
    proxy = pick_proxy_line(settings)
    target = settings.event_targets[0]
    page_url = target.page_url(settings.base_url)
    result = HeadlessTmptSolver(settings).solve(page_url, proxy_line=proxy)
    log(
        f"tmpt={result.has_tmpt} abck={result.has_abck} "
        f"epsf_passed={result.passed_epsf} cookies={len(result.cookies)}"
    )
    log(f"final url: {result.final_url[:120]}")
    return 0 if result.has_tmpt else 1


def cmd_warm_tmpt(settings: Settings) -> int:
    target = settings.event_targets[0]
    page_url = target.page_url(settings.base_url)
    pool = get_tmpt_pool(settings)
    proxies = load_proxy_pool(settings)[: settings.tmpt_pool_workers]
    if settings.proxy_line.strip() and settings.proxy_line.strip().lower() not in (
        "direct",
        "none",
        "off",
    ):
        proxies = [settings.proxy_line.strip(), *proxies]
    ok = pool.warm(page_url, proxies)
    return 0 if ok else 1


def cmd_test_alert(settings: Settings) -> int:
    target = settings.event_targets[0]
    demo = EventSnapshot(
        target=target,
        url=target.page_url(settings.base_url),
        title="Event Information Screen - eTickets",
        blocked=False,
        needs_login=False,
        pairs=[
            SeatPair(
                section="Block 109",
                price_level=6,
                row="B",
                seat_start="1",
                seat_end="2",
                seat_count=2,
            )
        ],
        total_available_seats=77630,
        price_labels={6: "R1,650.00"},
        event_name="Springboks vs All Blacks",
        event_date="Sat 5 September 2026, 17:00",
        venue="FNB Stadium",
        event_image=(
            "https://media.tmtickets.co.uk/za_springboks/en-gb/assets/"
            "event.42.150x60.png?etag=b2c30ca8c343a9cc435fd7588cb7e4de"
        ),
        settings=settings,
    )
    send_stock_alert(demo, settings, test=True)
    log("Test alert sent")
    return 0


def cmd_cart_test(settings: Settings) -> int:
    os.environ.setdefault("SPRINGBOKS_HEADLESS", "0")
    settings = settings.with_auto_cart(True)
    if not settings.credentials_ok():
        log("Set SARUGBY_EMAIL and SARUGBY_PASSWORD in .env")
        return 1

    if settings.use_browser_requests:
        proxy_line = resolve_browser_proxy(settings)
        with BrowserRequestClient(settings, proxy_line=proxy_line) as client:
            _, snapshots = run_check(settings, client, notify=False)
            snapshot = snapshots[0]
            for line in snapshot.summary_lines():
                log(line)
            if snapshot.carted:
                send_stock_alert(snapshot, settings)
                log("Cart test OK (browser session + request API)")
                return 0
            if not snapshot.has_target_stock():
                log("Cart test: no pairs or not logged in — run: python run.py --bootstrap")
                return 1
            log("Cart test: pair found but request-based cart failed")
            return 1

    tried: set[str] = set()
    for attempt in range(1, settings.proxy_max_retries + 1):
        proxy_line = pick_proxy_line(settings, exclude=tried)
        if proxy_line:
            tried.add(proxy_line)
        client = TmptClient(settings, proxy_line=proxy_line)
        try:
            _, snapshots = run_check(settings, client, notify=False)
            snapshot = snapshots[0]
            for line in snapshot.summary_lines():
                log(line)
            if snapshot.carted:
                send_stock_alert(snapshot, settings)
                log("Cart test OK")
                return 0
            if not snapshot.has_target_stock():
                log("Cart test: no pairs or not logged in")
                return 1
            log("Cart test: pair found but cart failed")
            return 1
        except ProxyError as exc:
            log(f"Proxy failed: {exc}")
            if settings.proxy_is_fixed or attempt >= settings.proxy_max_retries:
                raise
    return 1


def cmd_bootstrap(settings: Settings) -> int:
    return bootstrap(settings, proxy_line=resolve_browser_proxy(settings))


def cmd_export_cookies(settings: Settings) -> int:
    os.environ.setdefault("SPRINGBOKS_HEADLESS", "0")
    export_checkout_cookies(settings)
    return 0


def cmd_export_adonis(settings: Settings) -> int:
    os.environ.setdefault("SPRINGBOKS_HEADLESS", "0")
    export_adonis_checkout(settings)
    return 0


def cmd_export_queud(settings: Settings) -> int:
    os.environ.setdefault("SPRINGBOKS_HEADLESS", "0")
    export_queud_checkout(settings)
    return 0


def cmd_send_queud_discord(settings: Settings) -> int:
    return 0 if send_checkout_to_discord(settings) else 1


def cmd_queud_api() -> int:
    from queud_api.server import main as run_api

    log("queud basket API — set QUEUD_API_BASE in .env to your public URL")
    run_api()
    return 0


def cmd_monitor(settings: Settings) -> int:
    ids = ", ".join(str(t.event_id) for t in settings.event_targets)
    mode = "browser+request API" if settings.use_browser_requests else "HTTP"
    log(
        f"Monitor events [{ids}] x{settings.tickets_required} adjacent "
        f"every {settings.check_interval_seconds}s ({mode})"
    )
    if settings.use_browser_requests:
        proxy_line = resolve_browser_proxy(settings)
        with BrowserRequestClient(settings, proxy_line=proxy_line) as client:
            while True:
                try:
                    run_check(settings, client, notify=True)
                except KeyboardInterrupt:
                    log("Stopped")
                    return 0
                except Exception as exc:
                    log(f"Error: {exc}")
                time.sleep(settings.check_interval_seconds)

    while True:
        try:
            run_check(settings, notify=True)
        except KeyboardInterrupt:
            log("Stopped")
            return 0
        except Exception as exc:
            log(f"Error: {exc}")
        time.sleep(settings.check_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load()

    if args.bootstrap:
        return cmd_bootstrap(settings)
    if args.export_cookies:
        return cmd_export_cookies(settings)
    if args.export_adonis:
        return cmd_export_adonis(settings)
    if args.export_queud:
        return cmd_export_queud(settings)
    if args.send_queud_discord:
        return cmd_send_queud_discord(settings)
    if args.queud_api:
        return cmd_queud_api()
    if args.solve_tmpt:
        return cmd_solve_tmpt(settings)
    if args.warm_tmpt:
        return cmd_warm_tmpt(settings)
    if args.test_alert:
        return cmd_test_alert(settings)
    if args.cart_test:
        return cmd_cart_test(settings)
    if args.check:
        code, _ = run_check(settings, notify=False)
        return code
    if args.monitor or not any(
        [
            args.check,
            args.cart_test,
            args.test_alert,
            args.bootstrap,
            args.export_cookies,
            args.export_adonis,
            args.export_queud,
            args.send_queud_discord,
            args.queud_api,
            args.solve_tmpt,
            args.warm_tmpt,
        ]
    ):
        return cmd_monitor(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())