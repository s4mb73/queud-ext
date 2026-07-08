"""Terminal UI helpers — banner, colors, panels (AIO-style CLI)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from queud_aio import __version__

# ANSI palette
_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_MAGENTA = "\033[35m"
_WHITE = "\033[37m"


def ui_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("QUEUD_AIO_PLAIN", "").strip().lower() in ("1", "true", "yes"):
        return False
    return sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if not ui_enabled():
        return text
    return f"{code}{text}{_RESET}"


def success(text: str) -> str:
    return _c(text, _GREEN)


def fail(text: str) -> str:
    return _c(text, _RED)


def warn(text: str) -> str:
    return _c(text, _YELLOW)


def info(text: str) -> str:
    return _c(text, _CYAN)


def dim(text: str) -> str:
    return _c(text, _DIM)


def bold(text: str) -> str:
    return _c(text, _BOLD)


def brand(text: str) -> str:
    return _c(text, _MAGENTA + _BOLD)


def print_banner() -> None:
    lines = [
        "╔══════════════════════════════════════════╗",
        "║              QUEUD  AIO                    ║",
        "║      tickets · signups · checkout          ║",
        f"║                 v{__version__:<18}║",
        "╚══════════════════════════════════════════╝",
    ]
    print()
    for line in lines:
        print(brand(line))
    print()


def print_section(title: str) -> None:
    print()
    print(bold(f"  ▸ {title}"))
    print(dim(f"  {'─' * 42}"))


def print_kv(label: str, value: str, *, width: int = 12) -> None:
    print(f"  {dim(label.ljust(width))} {value}")


def print_panel(title: str, lines: list[str]) -> None:
    print()
    print(bold(f"  ┌─ {title} {'─' * max(0, 34 - len(title))}"))
    for line in lines:
        print(f"  │ {line}")
    print(bold("  └" + "─" * 38))


def print_menu_item(index: int, label: str, detail: str = "") -> None:
    num = info(f"[{index}]")
    if detail:
        print(f"  {num} {bold(label):<14} {dim(detail)}")
    else:
        print(f"  {num} {bold(label)}")


def print_task_header(current: int, total: int, label: str) -> None:
    print()
    print(bold(f"  [TASK {current}/{total}] ") + label)


def print_task_line(prefix: str, text: str) -> None:
    print(f"    {dim(prefix.ljust(7))} {text}")


def print_task_ok(message: str) -> None:
    print(f"    {dim('result')}  {success('✓')} {message}")


def print_task_fail(message: str) -> None:
    print(f"    {dim('result')}  {fail('✗')} {message}")


def print_running(command: str) -> None:
    print()
    print(info("  ▶ Running:"), dim(command))
    print()


def prompt(label: str, default: str = "") -> str:
    suffix = dim(f" [{default}]") if default else ""
    try:
        value = input(f"  {bold('?')} {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return value or default


def file_status(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "missing", dim("not found")
    if path.is_dir():
        count = sum(1 for _ in path.rglob("*") if _.is_file())
        return "ok", f"{count} files"
    try:
        lines = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if path.suffix.lower() == ".csv":
            return "ok", f"{max(0, len(lines) - 1)} rows" if lines else "empty"
        return "ok", f"{len(lines)} lines" if lines else "empty"
    except OSError:
        return "ok", "present"


def build_status_lines(settings) -> list[str]:
    from queud_aio.proxy import load_proxy_file
    from queud_aio.settings import env_profiles_csv
    from queud_aio.webhook_util import mask_webhook

    lines: list[str] = []

    proxy_state, proxy_detail = file_status(settings.proxy_file)
    if proxy_state == "ok":
        try:
            proxy_detail = f"{len(load_proxy_file(settings.proxy_file))} loaded"
        except (FileNotFoundError, ValueError):
            proxy_detail = "empty"
    lines.append(f"Proxies     {proxy_detail:<22} {dim(str(settings.proxy_file))}")

    csv_path = env_profiles_csv()
    if csv_path:
        p_state, p_detail = file_status(Path(csv_path))
        lines.append(f"Profiles    {p_detail:<22} {dim(csv_path)}")
    else:
        lines.append(f"Profiles    {dim('not set'):<22} {dim('QUEUD_AIO_PROFILES_CSV')}")

    s_state, s_detail = file_status(Path("data/signups.csv"))
    lines.append(f"Signups     {s_detail:<22} {dim('data/signups.csv')}")

    webhook = mask_webhook(settings.discord_webhook_url or str(settings.discord_webhook_file))
    lines.append(f"Webhook     {webhook}")

    lines.append(f"TMPT        {settings.tmpt_solver} · {settings.impersonate}")
    return lines