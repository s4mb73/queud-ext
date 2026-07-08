"""Shared Playwright persistent-context launch for bootstrap and API client."""

from __future__ import annotations

import os
from typing import Any

from playwright.sync_api import BrowserContext, Playwright

from queud_aio.headless_tmpt import playwright_proxy
from queud_aio.log_util import log
from queud_aio.settings import Settings


def headless_enabled() -> bool:
    return os.environ.get("SPRINGBOKS_HEADLESS", "0") == "1"


def launch_persistent_context(
    playwright: Playwright,
    settings: Settings,
    *,
    proxy_line: str = "",
    log_prefix: str = "Browser",
) -> BrowserContext:
    """Launch Chrome persistent profile — shared by bootstrap and BrowserRequestClient."""
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    proxy_cfg = playwright_proxy(proxy_line) if proxy_line else None
    if proxy_line:
        sid = proxy_line.split("-session-", 1)[-1].split(":", 1)[0]
        log(f"{log_prefix}: ZA proxy session {sid[:12]}...")
    else:
        log(f"{log_prefix}: direct connection")

    headless = headless_enabled()
    context: BrowserContext | None = None
    for channel in ("chrome", None):
        try:
            kwargs: dict[str, Any] = {
                "user_data_dir": str(settings.profile_dir),
                "headless": headless,
                "viewport": {"width": 1400, "height": 900},
                "locale": "en-GB",
                "proxy": proxy_cfg,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if channel:
                kwargs["channel"] = channel
            context = playwright.chromium.launch_persistent_context(**kwargs)
            log(f"{log_prefix}: {channel or 'chromium'} profile")
            return context
        except Exception as exc:
            log(f"{log_prefix}: launch failed ({channel}): {exc}")

    return playwright.chromium.launch_persistent_context(
        str(settings.profile_dir),
        headless=headless,
        viewport={"width": 1400, "height": 900},
        proxy=proxy_cfg,
    )