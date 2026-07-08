"""Tests for proxy resolution."""

import json
from dataclasses import replace

from queud_aio.proxy import resolve_browser_proxy
from queud_aio.settings import Settings


def _settings(**overrides) -> Settings:
    base = Settings.load()
    return replace(base, **overrides)


def test_resolve_browser_proxy_honors_explicit_proxy(tmp_path):
    settings = _settings(
        proxy_line="host:1234:user:pass",
        session_meta_file=tmp_path / "session_meta.json",
    )
    assert resolve_browser_proxy(settings) == "host:1234:user:pass"


def test_resolve_browser_proxy_uses_sticky_when_direct(tmp_path):
    meta = tmp_path / "session_meta.json"
    sticky = "evo-pro.wiredproxies.com:62345:PP_ZA-session-ABC:secret"
    meta.write_text(json.dumps({"proxy_line": sticky}), encoding="utf-8")
    settings = _settings(
        proxy_line="direct",
        session_meta_file=meta,
    )
    assert resolve_browser_proxy(settings) == sticky


def test_resolve_browser_proxy_picks_pool_when_no_sticky(tmp_path):
    settings = _settings(
        proxy_line="direct",
        session_meta_file=tmp_path / "missing.json",
        default_proxies=("pool-a:1:u:p", "pool-b:2:u:p"),
        proxy_file=tmp_path / "empty.txt",
    )
    chosen = resolve_browser_proxy(settings)
    assert chosen in settings.default_proxies