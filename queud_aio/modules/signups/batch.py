"""Run signup batches from CSV + proxy file."""

from __future__ import annotations

from pathlib import Path

from queud_aio import ui
from queud_aio.log_util import log
from queud_aio.modules.signups.profiles import (
    pick_signup_profiles,
    resolve_profile_module,
)
from queud_aio.proxy import load_proxy_file, parse_proxy
from queud_aio.settings import Settings


def run_signup_batch(
    settings: Settings,
    *,
    csv_path: str | Path,
    proxy_file: str | Path = "",
    module_hint: str = "",
    csv_row: int | None = None,
) -> int:
    path = Path(csv_path)
    if not path.exists():
        log("Set --csv with signup emails")
        return 1

    proxy_path = Path(proxy_file or settings.proxy_file)
    try:
        proxy_lines = load_proxy_file(proxy_path)
    except (FileNotFoundError, ValueError) as exc:
        log(str(exc))
        return 1

    profiles = pick_signup_profiles(path, row=csv_row)
    total = len(profiles)
    log(
        ui.bold(f"Signup batch — {total} email(s), ")
        + ui.dim(f"{len(proxy_lines)} proxies · {proxy_path.name}")
    )

    ok_count = 0
    for index, profile in enumerate(profiles):
        module, form_url = resolve_profile_module(profile, module_hint=module_hint)
        proxy_line = proxy_lines[index % len(proxy_lines)]
        _, proxy_url, _ = parse_proxy(proxy_line)

        ui.print_task_header(index + 1, total, profile.email)
        ui.print_task_line("proxy", proxy_line.split(":", 1)[0])
        ui.print_task_line("module", module.id)
        ui.print_task_line("form", form_url)

        result = module.submit(
            form_url=form_url,
            email=profile.email,
            proxy_url=proxy_url,
            impersonate=settings.impersonate,
            country=profile.country,
            town=profile.town,
            universal_recommends=profile.universal_recommends,
        )
        if result.ok:
            ok_count += 1
            ui.print_task_ok(result.message)
        else:
            ui.print_task_fail(f"({result.status_code}) {result.message}")

    print()
    if ok_count == total:
        log(ui.success(f"Done — {ok_count}/{total} succeeded"))
    else:
        log(ui.fail(f"Done — {ok_count}/{total} succeeded"))
    return 0 if ok_count == len(profiles) else 1