"""Run profiles from CSV — URL, Email, Password, Quantity, Webhook per row."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dataclasses import replace

from queud_aio.modules.registry import detect_site
from queud_aio.settings import DATA_DIR, EventTarget, Settings
from queud_aio.webhook_util import mask_webhook, resolve_webhook

_EVENT_PATH_RE = re.compile(r"/EDP/Event/Index/(\d+)", re.I)


@dataclass(frozen=True)
class RunProfile:
    url: str
    email: str
    password: str
    quantity: int
    row: int
    webhook: str = ""
    site: str = ""


def _cell(row: dict[str, str], *names: str) -> str:
    for name in names:
        for key, value in row.items():
            if key and key.strip().lower() == name.lower():
                return (value or "").strip()
    return ""


def load_profiles_csv(path: Path) -> list[RunProfile]:
    """Load non-empty profile rows from CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Profile CSV not found: {path}")

    profiles: list[RunProfile] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"Profile CSV has no header row: {path}")
        for line_no, row in enumerate(reader, start=2):
            url = _cell(row, "url", "link")
            email = _cell(row, "email")
            password = _cell(row, "password", "pass")
            qty_raw = _cell(row, "quantity", "qty", "tickets")
            webhook = _cell(row, "webhook", "discord", "discord_webhook")
            site = _cell(row, "site", "module", "venue")
            if not any((url, email, password, qty_raw, webhook)):
                continue
            if not url or not email or not password:
                raise ValueError(
                    f"{path}:{line_no} — URL, Email, and Password are required"
                )
            try:
                quantity = int(qty_raw or "2")
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_no} — invalid Quantity {qty_raw!r}"
                ) from exc
            if quantity < 1:
                raise ValueError(f"{path}:{line_no} — Quantity must be >= 1")
            profiles.append(
                RunProfile(
                    url=url,
                    email=email,
                    password=password,
                    quantity=quantity,
                    row=line_no,
                    webhook=webhook,
                    site=site,
                )
            )
    return profiles


def pick_profile(path: Path, row: int | None = None) -> RunProfile:
    """Pick profile by 1-based index among non-empty rows, or first row."""
    profiles = load_profiles_csv(path)
    if not profiles:
        raise ValueError(f"No filled profile rows in {path}")
    if row is None:
        return profiles[0]
    if row < 1 or row > len(profiles):
        raise ValueError(
            f"Profile row {row} out of range — {len(profiles)} filled row(s) in {path}"
        )
    return profiles[row - 1]


def parse_event_url(url: str) -> tuple[str, EventTarget]:
    """Parse full event URL → (site base, event target)."""
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid event URL: {url}")
    match = _EVENT_PATH_RE.search(parsed.path)
    if not match:
        raise ValueError(
            f"URL must include /EDP/Event/Index/<id> — got: {url}"
        )
    event_id = int(match.group(1))
    position = int(parse_qs(parsed.query).get("position", ["0"])[0] or "0")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, EventTarget(event_id=event_id, position=position)


def _profile_slug(email: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", email.strip().lower())
    return slug.strip("_") or "default"


def apply_profile(settings: Settings, profile: RunProfile) -> Settings:
    """Overlay CSV row onto settings; per-email browser profile + data dir."""
    site = detect_site(profile.url, profile.site)
    base_url, target = parse_event_url(profile.url)
    slug = _profile_slug(profile.email)
    profile_root = DATA_DIR / "profiles" / slug
    profile_root.mkdir(parents=True, exist_ok=True)

    webhook_url, webhook_file = resolve_webhook(
        profile.webhook,
        profile_root,
        fallback_url=settings.discord_webhook_url,
        fallback_file=settings.discord_webhook_file,
    )

    return replace(
        settings,
        base_url=base_url or site.base_url,
        identity_host=site.identity_host,
        sarugby_email=profile.email,
        sarugby_password=profile.password,
        tickets_required=profile.quantity,
        event_targets=(target,),
        profile_dir=profile_root / "browser",
        http_session_file=profile_root / "http_session.json",
        session_meta_file=profile_root / "session_meta.json",
        state_file=profile_root / "monitor_state.json",
        discord_webhook_url=webhook_url,
        discord_webhook_file=webhook_file,
        auto_cart=True,
    )


def list_profiles(path: Path) -> str:
    lines = [
        f"Profiles in {path}:",
        "Columns: URL, Email, Password, Quantity, Webhook [, Site]",
        "",
    ]
    for i, p in enumerate(load_profiles_csv(path), start=1):
        site = detect_site(p.url, p.site)
        _, target = parse_event_url(p.url)
        lines.append(
            f"  [{i}] row {p.row}: {p.email} x{p.quantity} "
            f"— {site.id} event {target.event_id} pos {target.position} "
            f"webhook {mask_webhook(p.webhook)}"
        )
    if len(lines) == 3:
        lines.append("  (no filled rows)")
    return "\n".join(lines)