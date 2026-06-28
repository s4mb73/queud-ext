"""Proxy pool helpers."""

from __future__ import annotations

import json
import random
import time

from rugby_sa.settings import Settings


def parse_proxy(line: str) -> tuple[str, str, str]:
    parts = line.strip().split(":")
    if len(parts) < 4:
        raise ValueError(f"Invalid proxy line: {line!r}")
    host, port = parts[0], parts[1]
    password = parts[-1]
    user = ":".join(parts[2:-1])
    proxy_url = f"http://{user}:{password}@{host}:{port}"
    capsolver_proxy = f"http:{host}:{port}:{user}:{password}"
    return host, proxy_url, capsolver_proxy


def load_proxy_pool(settings: Settings) -> list[str]:
    if settings.proxy_file.exists():
        lines = [
            ln.strip()
            for ln in settings.proxy_file.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if lines:
            return lines
    return list(settings.default_proxies)


def load_session_proxy(settings: Settings) -> str:
    if not settings.session_meta_file.exists():
        return ""
    try:
        meta = json.loads(settings.session_meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    return str(meta.get("proxy_line") or "")


def _pick_from_pool(settings: Settings, exclude: set[str] | None = None) -> str:
    pool = load_proxy_pool(settings)
    if not pool:
        return ""
    choices = [p for p in pool if p not in (exclude or set())]
    if not choices:
        choices = pool
    return random.choice(choices)


def save_session_proxy(settings: Settings, proxy_line: str) -> None:
    path = settings.session_meta_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "proxy_line": proxy_line,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def resolve_browser_proxy(settings: Settings, exclude: set[str] | None = None) -> str:
    """
    Proxy for Playwright sessions.

    Bootstrapped Chrome profiles are tied to the IP used at login — prefer the
    sticky proxy from session_meta.json. When .env says direct/empty, fall back
    to the ZA pool instead of a bare connection (Akamai often blocks direct).
    """
    explicit = settings.proxy_line.strip()
    if explicit and explicit.lower() not in ("direct", "none", "off"):
        return explicit
    sticky = load_session_proxy(settings)
    if sticky and sticky not in (exclude or set()):
        return sticky
    picked = _pick_from_pool(settings, exclude)
    if picked:
        save_session_proxy(settings, picked)
    return picked


def pick_proxy_line(settings: Settings, exclude: set[str] | None = None) -> str:
    line = settings.proxy_line.strip().lower()
    if line in ("direct", "none", "off"):
        return ""
    if settings.proxy_line.strip():
        return settings.proxy_line.strip()
    sticky = load_session_proxy(settings)
    if sticky and sticky not in (exclude or set()):
        return sticky
    return _pick_from_pool(settings, exclude)