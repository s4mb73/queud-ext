"""Paths and constants — prefer Settings.load() for runtime values."""

from __future__ import annotations

import re

from queud_aio.settings import DATA_DIR, PROJECT_ROOT, Settings

# Lazy singleton
_settings: Settings | None = None


def load_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def reload_settings() -> Settings:
    global _settings
    _settings = Settings.load()
    return _settings


# Backward-compatible module-level accessors (read from current settings)
def __getattr__(name: str):
    s = load_settings()
    mapping = {
        "BASE_URL": s.base_url,
        "IDENTITY_HOST": s.identity_host,
        "SARUGBY_EMAIL": s.sarugby_email,
        "SARUGBY_PASSWORD": s.sarugby_password,
        "EVENT_TARGETS": list(s.event_targets),
        "TICKETS_REQUIRED": s.tickets_required,
        "EXACT_PAIRS_ONLY": s.exact_pairs_only,
        "AUTO_CART": s.auto_cart,
        "COOKIE_FILE": s.http_session_file,
        "SESSION_META_FILE": s.session_meta_file,
        "STATE_FILE": s.state_file,
        "PROFILE_DIR": s.profile_dir,
        "PROXY_LINE": s.proxy_line,
        "PROXY_FILE": s.proxy_file,
        "PROXY_MAX_RETRIES": s.proxy_max_retries,
        "DEFAULT_PROXIES": list(s.default_proxies),
        "NTFY_TOPIC": s.ntfy_topic,
        "NTFY_URL": s.ntfy_url,
        "DISCORD_WEBHOOK_URL": s.discord_webhook_url,
        "DISCORD_WEBHOOK_FILE": s.discord_webhook_file,
        "CHECK_INTERVAL_SECONDS": s.check_interval_seconds,
        "REQUEST_TIMEOUT": s.request_timeout,
        "IMPERSONATE": s.impersonate,
        "TMPT_SOLVER": s.tmpt_solver,
        "CAPSOLVER_API_KEY": s.capsolver_api_key,
        "RECAPTCHA_SITE_KEY": s.recaptcha_site_key,
        "RECAPTCHA_PAGE_ACTION": s.recaptcha_page_action,
    }
    if name in mapping:
        return mapping[name]
    raise AttributeError(name)


BLOCK_MARKERS = (
    "Your Browsing Activity Has Been Paused",
    "Let's Get Your Identity Verified",
    "Restricted access",
)
AVAILABLE_SEAT_SYMBOL = "A"
AKAMAI_COOKIE_NAMES = frozenset({"_abck", "bm_sz", "tmpt"})

SOLD_OUT_RE = re.compile(r"sold\s*out|unavailable|no longer available", re.I)
AVAILABLE_RE = re.compile(r"\badd\b|\bbuy\b|\bselect\b|in stock", re.I)
PRICE_RE = re.compile(r"(?:R|ZAR)\s*[\d,]+(?:\.\d{2})?|\b[\d,]+\.\d{2}\b")