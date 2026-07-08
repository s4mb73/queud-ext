"""CSV profiles for signup modules (lighter than ticket profiles)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from queud_aio.modules.signups.registry import (
    SignupModule,
    detect_signup,
    resolve_form_url,
)
from queud_aio.webhook_util import mask_webhook


@dataclass(frozen=True)
class SignupProfile:
    url: str
    email: str
    row: int
    country: str = "GB"
    town: str = ""
    module: str = ""
    universal_recommends: bool = False
    webhook: str = ""


def _cell(row: dict[str, str], *names: str) -> str:
    for name in names:
        for key, value in row.items():
            if key and key.strip().lower() == name.lower():
                return (value or "").strip()
    return ""


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_signup_profiles_csv(path: Path) -> list[SignupProfile]:
    if not path.exists():
        raise FileNotFoundError(f"Signup CSV not found: {path}")

    profiles: list[SignupProfile] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"Signup CSV has no header row: {path}")
        for line_no, row in enumerate(reader, start=2):
            url = _cell(row, "url", "link", "form")
            email = _cell(row, "email")
            country = _cell(row, "country", "countrycode") or "GB"
            town = _cell(row, "town", "city")
            module = _cell(row, "module", "site", "signup")
            recommends = _truthy(
                _cell(row, "universal_recommends", "recommends", "dm_otherinternal")
            )
            webhook = _cell(row, "webhook", "discord", "discord_webhook")
            if not any((url, email, country, town, module, webhook)):
                continue
            if not email:
                raise ValueError(f"{path}:{line_no} — Email is required")
            profiles.append(
                SignupProfile(
                    url=url,
                    email=email,
                    row=line_no,
                    country=country,
                    town=town,
                    module=module,
                    universal_recommends=recommends,
                    webhook=webhook,
                )
            )
    return profiles


def pick_signup_profiles(path: Path, row: int | None = None) -> list[SignupProfile]:
    profiles = load_signup_profiles_csv(path)
    if not profiles:
        raise ValueError(f"No filled signup rows in {path}")
    if row is None:
        return profiles
    if row < 1 or row > len(profiles):
        raise ValueError(
            f"Signup row {row} out of range — {len(profiles)} filled row(s) in {path}"
        )
    return [profiles[row - 1]]


def pick_signup_profile(path: Path, row: int | None = None) -> SignupProfile:
    return pick_signup_profiles(path, row=row)[0]


def resolve_profile_module(
    profile: SignupProfile,
    *,
    module_hint: str = "",
) -> tuple[SignupModule, str]:
    module = detect_signup(profile.url, module_hint or profile.module or "uk-umg")
    form_url = resolve_form_url(profile.url, module)
    return module, form_url


def list_signup_profiles(path: Path, *, module_hint: str = "") -> str:
    lines = [
        f"Signup profiles in {path}:",
        "Columns: Email [, URL, Country, Town, Module, UniversalRecommends, Webhook]",
        "",
    ]
    for i, profile in enumerate(load_signup_profiles_csv(path), start=1):
        module, form_url = resolve_profile_module(profile, module_hint=module_hint)
        lines.append(
            f"  [{i}] row {profile.row}: {profile.email} "
            f"— {module.id} {profile.country} "
            f"form {form_url} "
            f"webhook {mask_webhook(profile.webhook)}"
        )
    if len(lines) == 3:
        lines.append("  (no filled rows)")
    return "\n".join(lines)