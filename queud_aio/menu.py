"""Interactive CLI — AIO-style menu."""

from __future__ import annotations

from pathlib import Path

from queud_aio import ui
from queud_aio.log_util import log, set_interactive_mode
from queud_aio.modules.registry import list_sites
from queud_aio.modules.signups.profiles import load_signup_profiles_csv
from queud_aio.modules.signups.registry import list_signups
from queud_aio.profiles import load_profiles_csv
from queud_aio.settings import Settings, env_profiles_csv
from queud_aio.webhook_util import mask_webhook


TICKET_COMMANDS: tuple[tuple[str, str], ...] = (
    ("monitor", "Watch + alert + auto-cart (24/7)"),
    ("checkout", "Cart once + queud + Discord"),
    ("bootstrap", "Refresh HTTP login session"),
)

SIGNUP_COMMANDS: tuple[tuple[str, str], ...] = (
    ("signup", "Submit newsletter / pre-sale signup"),
    ("list-signups", "List signup CSV profiles"),
)


def _pick_int(label: str, max_n: int, default: int = 1) -> int:
    while True:
        raw = ui.prompt(label, str(default))
        try:
            n = int(raw)
        except ValueError:
            log(ui.warn("Enter a number"))
            continue
        if 1 <= n <= max_n:
            return n
        log(ui.warn(f"Choose 1–{max_n}"))


def _optional_int(label: str, max_n: int) -> int | None:
    raw = ui.prompt(f"{label} (blank = all)", "")
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        log(ui.warn("Enter a number or leave blank"))
        return _optional_int(label, max_n)
    if 1 <= n <= max_n:
        return n
    log(ui.warn(f"Choose 1–{max_n}"))
    return _optional_int(label, max_n)


def _pick_from_menu(title: str, items: tuple[tuple[str, str], ...]) -> int:
    ui.print_section(title)
    for i, (cmd, desc) in enumerate(items, start=1):
        ui.print_menu_item(i, cmd, desc)
    print()
    return _pick_int("Select", len(items), 1) - 1


def run_menu() -> int:
    from queud_aio.cli import dispatch_command

    set_interactive_mode(True)
    settings = Settings.load()

    ui.print_banner()
    ui.print_panel("System", ui.build_status_lines(settings))

    ui.print_section("Modules")
    for site in list_sites():
        ui.print_kv(site.id, site.name)
    for module in list_signups():
        ui.print_kv(module.id, module.name)

    ui.print_section("Mode")
    ui.print_menu_item(1, "Tickets", "monitor · checkout · bootstrap")
    ui.print_menu_item(2, "Signups", "newsletter / pre-sale forms")
    print()
    mode = _pick_int("Select mode", 2, 1)

    argv: list[str] = []
    row: int | None = None

    if mode == 1:
        idx = _pick_from_menu("Ticket commands", TICKET_COMMANDS)
        command = TICKET_COMMANDS[idx][0]
        argv = [command]

        csv_raw = env_profiles_csv()
        if not csv_raw:
            csv_raw = ui.prompt("Profiles CSV path (blank = .env only)", "")
        if csv_raw:
            csv_path = Path(csv_raw)
            argv.extend(["--csv", str(csv_path)])
            if csv_path.exists():
                profiles = load_profiles_csv(csv_path)
                if profiles:
                    ui.print_section("Profiles")
                    for i, p in enumerate(profiles, start=1):
                        wh = mask_webhook(p.webhook)
                        print(
                            f"  {ui.info(f'[{i}]')} {p.email} x{p.quantity} "
                            f"{ui.dim(f'webhook {wh}')}"
                        )
                    print()
                    row = _pick_int("Profile number", len(profiles), 1)

    else:
        idx = _pick_from_menu("Signup commands", SIGNUP_COMMANDS)
        command = SIGNUP_COMMANDS[idx][0]
        argv = [command]

        csv_path = Path(ui.prompt("Signup CSV path", "data/signups.csv"))
        argv.extend(["--csv", str(csv_path)])
        if csv_path.exists():
            profiles = load_signup_profiles_csv(csv_path)
            if profiles:
                ui.print_section("Emails")
                for i, profile in enumerate(profiles, start=1):
                    print(f"  {ui.info(f'[{i}]')} {profile.email} {ui.dim(f'row {profile.row}')}")
                print()
                if command == "signup":
                    row = _optional_int("Email number", len(profiles))
            else:
                log(ui.warn(f"No filled rows in {csv_path}"))
        if command == "signup":
            proxy_path = ui.prompt("Proxy file", str(settings.proxy_file))
            argv.extend(["--proxy-file", proxy_path])

    if row is not None:
        argv.extend(["--row", str(row)])

    ui.print_running("python run.py " + " ".join(argv))
    return dispatch_command(argv)