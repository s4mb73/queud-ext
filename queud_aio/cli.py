"""CLI — subcommands, CSV profiles, interactive menu."""

from __future__ import annotations

import argparse
import os
import sys
import time

from queud_aio.bootstrap import bootstrap
from queud_aio.queud_export import export_queud_checkout, send_checkout_to_discord
from queud_aio.client import TmptClient
from queud_aio.log_util import log
from queud_aio.models import EventSnapshot, SeatPair
from queud_aio.monitor import run_check
from queud_aio.notify import send_stock_alert
from queud_aio.headless_tmpt import HeadlessTmptSolver, get_tmpt_pool
from queud_aio.proxy import load_proxy_pool, pick_proxy_line
from queud_aio.settings import Settings
from queud_aio.wreq_adapter import PROXY_ERRORS

COMMANDS = frozenset(
    {
        "monitor",
        "check",
        "checkout",
        "cart-test",
        "bootstrap",
        "export-queud",
        "send-discord",
        "queud-api",
        "solve-tmpt",
        "warm-tmpt",
        "test-alert",
        "list-profiles",
        "signup",
        "list-signups",
        "menu",
    }
)

# Legacy --flag → subcommand
_FLAG_TO_COMMAND = {
    "monitor": "monitor",
    "check": "check",
    "checkout": "checkout",
    "cart_test": "cart-test",
    "bootstrap": "bootstrap",
    "export_queud": "export-queud",
    "send_queud_discord": "send-discord",
    "queud_api": "queud-api",
    "solve_tmpt": "solve-tmpt",
    "warm_tmpt": "warm-tmpt",
    "test_alert": "test-alert",
    "list_profiles": "list-profiles",
    "signup": "signup",
    "list_signups": "list-signups",
    "menu": "menu",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Queud AIO — multi-site ticket monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python run.py                      interactive menu
  python run.py monitor              24/7 poll + auto-cart
  python run.py checkout --csv profiles.csv --row 1
  python run.py signup --csv signups.csv --proxy-file data/proxies.txt
  python run.py signup --csv signups.csv --row 1 --proxy-file data/proxies.txt
  python run.py --csv profiles.csv list-profiles

Ticket CSV: URL, Email, Password, Quantity, Webhook [, Site]
Signup CSV: Email [, URL, Country, Town, Module, UniversalRecommends, Webhook]
Proxy file: host:port:user:pass per line (# comments OK)
Webhook: Discord URL, path to webhook file, or blank for .env default
        """.strip(),
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Profile CSV (URL, Email, Password, Quantity, Webhook)",
    )
    parser.add_argument(
        "--row",
        "--profile",
        type=int,
        dest="row",
        metavar="N",
        help="CSV row number (1-based; signup default: all rows)",
    )
    parser.add_argument(
        "--proxy-file",
        metavar="PATH",
        help="Proxy list file for signup (host:port:user:pass per line)",
    )
    parser.add_argument(
        "--site",
        metavar="ID",
        help="Force site module (springboks)",
    )
    parser.add_argument(
        "--module",
        metavar="ID",
        help="Force signup module (uk-umg)",
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=sorted(COMMANDS),
        help="Command to run (omit for interactive menu)",
    )

    for flag, cmd in _FLAG_TO_COMMAND.items():
        if cmd == "menu":
            continue
        parser.add_argument(
            f"--{flag.replace('_', '-')}",
            action="store_true",
            help=argparse.SUPPRESS,
        )
    return parser


def _resolve_command(args: argparse.Namespace) -> str | None:
    if args.command:
        return args.command
    for flag, cmd in _FLAG_TO_COMMAND.items():
        if getattr(args, flag, False):
            return cmd
    return None


def _resolve_settings(args: argparse.Namespace) -> Settings | None:
    from pathlib import Path

    from queud_aio.profiles import apply_profile, list_profiles, parse_event_url, pick_profile
    from queud_aio.modules.registry import detect_site, get_site
    from queud_aio.webhook_util import mask_webhook

    settings = Settings.load()
    from queud_aio.settings import env_profiles_csv

    csv_path = args.csv or env_profiles_csv()

    command = _resolve_command(args)
    if command == "list-profiles":
        if not csv_path:
            log("Set --csv or QUEUD_AIO_PROFILES_CSV (RUGBY_SA_PROFILES_CSV still works)")
            return None
        log(list_profiles(Path(csv_path)))
        return None

    if command == "list-signups":
        from queud_aio.modules.signups.profiles import list_signup_profiles

        if not csv_path:
            log("Set --csv or QUEUD_AIO_PROFILES_CSV (RUGBY_SA_PROFILES_CSV still works)")
            return None
        log(list_signup_profiles(Path(csv_path)))
        return None

    if command == "signup":
        return settings

    if not csv_path:
        if args.site:
            site = get_site(args.site)
            settings = Settings.load()
            from dataclasses import replace

            settings = replace(
                settings,
                base_url=site.base_url,
                identity_host=site.identity_host,
            )
        return settings

    csv_path = Path(csv_path)
    profile = pick_profile(csv_path, row=args.row)
    site = detect_site(profile.url, args.site or profile.site)
    _, target = parse_event_url(profile.url)
    log(
        f"{site.name} — {profile.email} x{profile.quantity} "
        f"event {target.event_id} webhook {mask_webhook(profile.webhook)}"
    )
    return apply_profile(settings, profile)


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


def _run_cart_flow(settings: Settings, *, discord: bool) -> int:
    settings = settings.with_auto_cart(True)
    if not settings.credentials_ok():
        log("Set SARUGBY_EMAIL and SARUGBY_PASSWORD in .env or CSV")
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
                if discord:
                    export_queud_checkout(settings, client=client)
                    if not send_checkout_to_discord(settings):
                        return 1
                    log("Checkout complete — cart, queud files, and Discord sent")
                else:
                    send_checkout_to_discord(settings)
                    log("Cart test OK (wreq)")
                return 0
            if not snapshot.has_target_stock():
                log("No pairs or not logged in — run: python run.py bootstrap")
                return 1
            log("Pair found but cart failed")
            return 1
        except PROXY_ERRORS as exc:
            log(f"Proxy failed: {exc}")
            if settings.proxy_is_fixed or attempt >= settings.proxy_max_retries:
                raise
        finally:
            client.close()
    return 1


def cmd_cart_test(settings: Settings) -> int:
    return _run_cart_flow(settings, discord=False)


def cmd_bootstrap(settings: Settings) -> int:
    return bootstrap(settings, proxy_line=pick_proxy_line(settings))


def cmd_export_queud(settings: Settings) -> int:
    export_queud_checkout(settings)
    return 0


def cmd_checkout(settings: Settings) -> int:
    return _run_cart_flow(settings, discord=True)


def cmd_send_queud_discord(settings: Settings) -> int:
    return 0 if send_checkout_to_discord(settings) else 1


def cmd_signup(
    settings: Settings,
    *,
    module_hint: str = "",
    csv_row: int | None = None,
    csv_path: str = "",
    proxy_file: str = "",
) -> int:
    from queud_aio.modules.signups.batch import run_signup_batch

    return run_signup_batch(
        settings,
        csv_path=csv_path,
        proxy_file=proxy_file,
        module_hint=module_hint,
        csv_row=csv_row,
    )


def cmd_queud_api() -> int:
    from queud_api.server import main as run_api

    log("queud basket API — set QUEUD_API_BASE in .env to your public URL")
    run_api()
    return 0


def cmd_monitor(settings: Settings) -> int:
    ids = ", ".join(str(t.event_id) for t in settings.event_targets)
    log(
        f"Monitor events [{ids}] x{settings.tickets_required} adjacent "
        f"every {settings.check_interval_seconds}s (wreq HTTP)"
    )
    proxy_line = pick_proxy_line(settings)
    client = TmptClient(settings, proxy_line=proxy_line)
    try:
        while True:
            try:
                run_check(settings, client, notify=True)
            except KeyboardInterrupt:
                log("Stopped")
                return 0
            except Exception as exc:
                log(f"Error: {exc}")
            time.sleep(settings.check_interval_seconds)
    finally:
        client.close()


def run_command(
    command: str,
    settings: Settings,
    *,
    args: argparse.Namespace | None = None,
) -> int:
    dispatch = {
        "monitor": cmd_monitor,
        "check": lambda s: run_check(s, notify=False)[0],
        "checkout": cmd_checkout,
        "cart-test": cmd_cart_test,
        "bootstrap": cmd_bootstrap,
        "export-queud": cmd_export_queud,
        "send-discord": cmd_send_queud_discord,
        "queud-api": lambda _: cmd_queud_api(),
        "solve-tmpt": cmd_solve_tmpt,
        "warm-tmpt": cmd_warm_tmpt,
        "test-alert": cmd_test_alert,
        "signup": lambda s: cmd_signup(
            s,
            module_hint=(args.module if args else "") or "",
            csv_row=(args.row if args else None),
            csv_path=(args.csv if args else "") or "",
            proxy_file=(args.proxy_file if args else "") or "",
        ),
    }
    handler = dispatch.get(command)
    if handler is None:
        log(f"Unknown command: {command}")
        return 1
    return int(handler(settings))


def dispatch_command(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = _resolve_command(args)
    if command is None or command == "menu":
        from queud_aio.log_util import set_interactive_mode
        from queud_aio.menu import run_menu

        set_interactive_mode(True)
        return run_menu()
    settings = _resolve_settings(args)
    if settings is None:
        return 0
    return run_command(command, settings, args=args)


def main(argv: list[str] | None = None) -> int:
    return dispatch_command(argv)


if __name__ == "__main__":
    sys.exit(main())