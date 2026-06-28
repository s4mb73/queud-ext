"""Immutable runtime settings — single source of truth."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class EventTarget:
    event_id: int
    position: int

    def page_url(self, base_url: str | None = None) -> str:
        if base_url is None:
            base_url = Settings.load().base_url
        return f"{base_url}/EDP/Event/Index/{self.event_id}?position={self.position}"

    def key(self) -> str:
        return str(self.event_id)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("RUGBY_SA_DATA_DIR", str(PROJECT_ROOT / "data")))

DEFAULT_PROXIES = [
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-HPzb8Rl96fBK:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-OSwOULKTTKll:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-R6IX2ubCotd2:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-fT6T4znLX4sm:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-HFz8gQJz8ETl:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-PvFkk08KVEoD:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-wRXhqETg6VK8:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-Xn2x5ELyrXtt:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-sfqkFH5l4z0m:6th33k6w",
    "evo-pro.wiredproxies.com:62345:PP_P3KRZ9X-country-ZA-session-tDs0brG8hTlQ:6th33k6w",
]


def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _parse_sections(raw: str) -> frozenset[str]:
    if not raw.strip():
        return frozenset()
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


def _parse_event_targets() -> tuple[EventTarget, ...]:
    raw = os.environ.get("SPRINGBOKS_EVENTS", "").strip()
    if raw:
        targets: list[EventTarget] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" in part:
                eid_s, pos_s = part.split(":", 1)
                targets.append(EventTarget(int(eid_s), int(pos_s)))
            else:
                targets.append(EventTarget(int(part), 0))
        return tuple(targets)
    if os.environ.get("SPRINGBOKS_EVENT_ID"):
        return (
            EventTarget(
                int(os.environ["SPRINGBOKS_EVENT_ID"]),
                int(os.environ.get("SPRINGBOKS_POSITION", "0")),
            ),
        )
    return (EventTarget(42, 7),)


def _env_bool(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    base_url: str
    identity_host: str
    sarugby_email: str
    sarugby_password: str
    event_targets: tuple[EventTarget, ...]
    tickets_required: int
    exact_pairs_only: bool
    auto_cart: bool
    cart_dry_run: bool
    cart_max_price_zar: float | None
    cart_allowed_sections: frozenset[str]
    cart_retry_delay: float
    cart_max_attempts: int
    capsolver_api_key: str
    recaptcha_site_key: str
    recaptcha_page_action: str
    http_session_file: Path
    session_meta_file: Path
    state_file: Path
    profile_dir: Path
    proxy_line: str
    proxy_file: Path
    proxy_max_retries: int
    default_proxies: tuple[str, ...]
    ntfy_topic: str
    discord_webhook_url: str
    discord_webhook_file: Path
    discord_embed_color: int
    discord_footer_text: str
    discord_footer_icon: str
    check_interval_seconds: int
    capsolver_poll_interval: float
    capsolver_max_wait: int
    request_timeout: int
    impersonate: str
    tmpt_solver: str
    tmpt_pool_workers: int
    tmpt_pool_cache_ttl: int
    tmpt_headless_timeout: int
    tmpt_workers_dir: Path
    tmpt_auto_fallback: bool
    tmpt_headless_use_profile: bool
    use_browser_requests: bool
    session_max_steps: int
    queue_wait_seconds: int
    queud_api_base: str
    queud_api_key: str

    @classmethod
    def load(cls) -> Settings:
        _load_dotenv()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        max_price_raw = os.environ.get("RUGBY_SA_CART_MAX_PRICE", "").strip()
        max_price = float(max_price_raw) if max_price_raw else None
        ntfy = os.environ.get("SPRINGBOKS_NTFY_TOPIC", "springboks-stock-CHANGE-ME")
        proxy = os.environ.get("SPRINGBOKS_PROXY", "")
        return cls(
            base_url=os.environ.get(
                "SPRINGBOKS_BASE_URL", "https://springboks.tmtickets.co.za"
            ),
            identity_host=os.environ.get(
                "SPRINGBOKS_IDENTITY_HOST", "https://web-identity.tmtickets.co.uk"
            ),
            sarugby_email=os.environ.get("SARUGBY_EMAIL", ""),
            sarugby_password=os.environ.get("SARUGBY_PASSWORD", ""),
            event_targets=_parse_event_targets(),
            tickets_required=int(os.environ.get("SPRINGBOKS_TICKETS_REQUIRED", "2")),
            exact_pairs_only=_env_bool("SPRINGBOKS_EXACT_PAIRS"),
            auto_cart=_env_bool("SPRINGBOKS_AUTO_CART"),
            cart_dry_run=_env_bool("RUGBY_SA_CART_DRY_RUN"),
            cart_max_price_zar=max_price,
            cart_allowed_sections=_parse_sections(
                os.environ.get("RUGBY_SA_CART_SECTIONS", "")
            ),
            cart_retry_delay=float(os.environ.get("SPRINGBOKS_CART_DELAY_SEC", "3")),
            cart_max_attempts=int(os.environ.get("SPRINGBOKS_CART_MAX_ATTEMPTS", "5")),
            capsolver_api_key=os.environ.get("CAPSOLVER_API_KEY", ""),
            recaptcha_site_key=os.environ.get(
                "SPRINGBOKS_RECAPTCHA_SITE_KEY",
                "6LcvL3UrAAAAAO_9u8Seiuf-I6F_tP_jSS-zndXV",
            ),
            recaptcha_page_action=os.environ.get(
                "SPRINGBOKS_RECAPTCHA_ACTION", "Event"
            ),
            http_session_file=Path(
                os.environ.get(
                    "SPRINGBOKS_COOKIE_FILE", str(DATA_DIR / "http_session.json")
                )
            ),
            session_meta_file=Path(
                os.environ.get(
                    "SPRINGBOKS_SESSION_META_FILE", str(DATA_DIR / "session_meta.json")
                )
            ),
            state_file=Path(
                os.environ.get(
                    "SPRINGBOKS_STATE_FILE", str(DATA_DIR / "monitor_state.json")
                )
            ),
            profile_dir=Path(
                os.environ.get("SPRINGBOKS_PROFILE_DIR", str(DATA_DIR / "profile"))
            ),
            proxy_line=proxy,
            proxy_file=Path(
                os.environ.get("SPRINGBOKS_PROXY_FILE", str(DATA_DIR / "proxies.txt"))
            ),
            proxy_max_retries=int(os.environ.get("SPRINGBOKS_PROXY_RETRIES", "5")),
            default_proxies=tuple(DEFAULT_PROXIES),
            ntfy_topic=ntfy,
            discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
            discord_webhook_file=Path(
                os.environ.get(
                    "DISCORD_WEBHOOK_FILE", str(DATA_DIR / "discord_webhook")
                )
            ),
            discord_embed_color=int(os.environ.get("DISCORD_EMBED_COLOR", "5763719")),
            discord_footer_text=os.environ.get(
                "DISCORD_FOOTER_TEXT", "Powered by innovite"
            ),
            discord_footer_icon=os.environ.get(
                "DISCORD_FOOTER_ICON",
                "https://i.postimg.cc/vZ1bx7Sk/E0285-EC4-8437-4-A0-A-B001-B97-D2-C993-C0-D.jpg",
            ),
            check_interval_seconds=int(
                os.environ.get("SPRINGBOKS_INTERVAL_SEC", str(5 * 60))
            ),
            capsolver_poll_interval=float(
                os.environ.get("CAPSOLVER_POLL_INTERVAL", "3")
            ),
            capsolver_max_wait=int(os.environ.get("CAPSOLVER_MAX_WAIT", "180")),
            request_timeout=int(os.environ.get("SPRINGBOKS_TIMEOUT_SEC", "60")),
            impersonate=os.environ.get("SPRINGBOKS_IMPERSONATE", "chrome124"),
            tmpt_solver=os.environ.get("TMPT_SOLVER", "http").lower(),
            tmpt_pool_workers=int(os.environ.get("RUGBY_SA_TMPT_POOL_WORKERS", "3")),
            tmpt_pool_cache_ttl=int(os.environ.get("RUGBY_SA_TMPT_CACHE_TTL", "240")),
            tmpt_headless_timeout=int(
                os.environ.get("RUGBY_SA_TMPT_HEADLESS_TIMEOUT", "120")
            ),
            tmpt_workers_dir=Path(
                os.environ.get(
                    "RUGBY_SA_TMPT_WORKERS_DIR", str(DATA_DIR / "tmpt_workers")
                )
            ),
            tmpt_auto_fallback=_env_bool("RUGBY_SA_TMPT_AUTO_FALLBACK", "1"),
            tmpt_headless_use_profile=_env_bool("RUGBY_SA_HEADLESS_USE_PROFILE"),
            use_browser_requests=_env_bool("RUGBY_SA_BROWSER_REQUESTS", "1"),
            session_max_steps=int(os.environ.get("RUGBY_SA_SESSION_MAX_STEPS", "12")),
            queue_wait_seconds=int(os.environ.get("RUGBY_SA_QUEUE_WAIT_SEC", "5")),
            queud_api_base=os.environ.get("QUEUD_API_BASE", "").strip().rstrip("/"),
            queud_api_key=os.environ.get("QUEUD_API_KEY", "").strip(),
        )

    @property
    def ntfy_url(self) -> str:
        return f"https://ntfy.sh/{self.ntfy_topic}"

    @property
    def proxy_is_fixed(self) -> bool:
        return self.proxy_line.lower() not in ("", "direct", "none", "off")

    def with_auto_cart(self, enabled: bool = True) -> Settings:
        return replace(self, auto_cart=enabled)

    def credentials_ok(self) -> bool:
        return bool(self.sarugby_email and self.sarugby_password)