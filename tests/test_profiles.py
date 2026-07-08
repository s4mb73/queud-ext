from pathlib import Path

import pytest

from queud_aio.profiles import apply_profile, load_profiles_csv, pick_profile
from queud_aio.settings import Settings
from queud_aio.webhook_util import mask_webhook, resolve_webhook


def test_load_profiles_with_webhook(tmp_path: Path):
    csv_path = tmp_path / "profiles.csv"
    csv_path.write_text(
        "URL,Email,Password,Quantity,Webhook\n"
        "https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7,"
        "a@test.com,secret,2,https://discord.com/api/webhooks/abc/def\n",
        encoding="utf-8",
    )
    profiles = load_profiles_csv(csv_path)
    assert len(profiles) == 1
    assert profiles[0].webhook.endswith("/def")
    assert profiles[0].quantity == 2


def test_apply_profile_sets_discord_webhook(tmp_path, monkeypatch):
    monkeypatch.setattr("queud_aio.profiles.DATA_DIR", tmp_path / "data")
    csv_path = tmp_path / "profiles.csv"
    csv_path.write_text(
        "URL,Email,Password,Quantity,Webhook\n"
        "https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7,"
        "a@test.com,secret,3,https://discord.com/api/webhooks/1/2\n",
        encoding="utf-8",
    )
    profile = pick_profile(csv_path)
    settings = apply_profile(Settings.load(), profile)
    assert settings.discord_webhook_url.startswith("https://discord")
    assert settings.tickets_required == 3
    assert settings.sarugby_email == "a@test.com"


def test_resolve_webhook_file_path(tmp_path: Path):
    wh_file = tmp_path / "channel_a.txt"
    wh_file.write_text("https://discord.com/api/webhooks/x/y\n", encoding="utf-8")
    url, path = resolve_webhook(str(wh_file), tmp_path / "profile")
    assert url.endswith("/y")
    assert path == wh_file


def test_mask_webhook_hides_url():
    assert mask_webhook("") == "(default .env)"
    assert mask_webhook("https://discord.com/api/webhooks/12/abcdefghijkl").startswith("…")