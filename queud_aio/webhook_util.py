"""Resolve per-profile Discord webhooks."""

from __future__ import annotations

from pathlib import Path


def mask_webhook(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "(default .env)"
    if value.startswith("http") and "/" in value:
        return "…" + value.rsplit("/", 1)[-1][:12]
    name = Path(value).name
    return name if name else value[:24]


def resolve_webhook(
    raw: str,
    profile_root: Path,
    *,
    fallback_url: str = "",
    fallback_file: Path | None = None,
) -> tuple[str, Path]:
    """
    CSV Webhook column: Discord URL, path to webhook file, or empty for .env default.
    """
    raw = (raw or "").strip()
    webhook_file = profile_root / "discord_webhook"

    if not raw:
        if fallback_url:
            return fallback_url, webhook_file
        if fallback_file and fallback_file.exists():
            return "", fallback_file
        return "", webhook_file

    if raw.startswith("http"):
        profile_root.mkdir(parents=True, exist_ok=True)
        webhook_file.write_text(raw + "\n", encoding="utf-8")
        return raw, webhook_file

    path = Path(raw)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip(), path

    if path.is_absolute() or "/" in raw or "\\" in raw:
        raise ValueError(f"Webhook file not found: {raw}")

    profile_root.mkdir(parents=True, exist_ok=True)
    webhook_file.write_text(raw + "\n", encoding="utf-8")
    return raw, webhook_file