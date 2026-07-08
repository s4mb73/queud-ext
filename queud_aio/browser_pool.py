"""Reuse one BrowserRequestClient per process (same profile + proxy)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from queud_aio.browser_request import BrowserRequestClient
from queud_aio.proxy import resolve_browser_proxy
from queud_aio.settings import Settings

_pool: BrowserRequestClient | None = None
_pool_key: tuple[str, str] | None = None


def _pool_identity(settings: Settings, proxy_line: str) -> tuple[str, str]:
    return (str(settings.profile_dir.resolve()), proxy_line)


def borrow_browser(
    settings: Settings,
    *,
    proxy_line: str | None = None,
) -> BrowserRequestClient:
    """Return a started client; reuse if profile and proxy match."""
    global _pool, _pool_key
    proxy_line = proxy_line if proxy_line is not None else resolve_browser_proxy(settings)
    key = _pool_identity(settings, proxy_line)
    if _pool is not None and _pool_key == key and _pool._context is not None:
        return _pool
    if _pool is not None:
        _pool.close()
    _pool = BrowserRequestClient(settings, proxy_line=proxy_line)
    _pool.start()
    _pool_key = key
    return _pool


def release_browser(*, close: bool = True) -> None:
    global _pool, _pool_key
    if _pool is None:
        return
    if close:
        _pool.close()
        _pool = None
        _pool_key = None


@contextmanager
def browser_session(
    settings: Settings,
    *,
    proxy_line: str | None = None,
    close: bool = True,
) -> Iterator[BrowserRequestClient]:
    client = borrow_browser(settings, proxy_line=proxy_line)
    try:
        yield client
    finally:
        if close:
            release_browser(close=True)