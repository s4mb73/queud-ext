"""Tests for headless tmpt pool helpers (no browser)."""

import time

from rugby_sa.headless_tmpt import HeadlessTmptPool, TmptSolveResult, _cache_key


def _result(proxy: str = "", age: float = 0.0) -> TmptSolveResult:
    now = time.time()
    return TmptSolveResult(
        cookies=({"name": "tmpt", "value": "x", "domain": "", "path": "/"},),
        proxy_line=proxy,
        page_url="https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7",
        final_url="https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7",
        solved_at=now - age,
        has_tmpt=True,
        has_abck=True,
        passed_epsf=True,
    )


class _FakeSettings:
    tmpt_pool_workers = 2
    tmpt_pool_cache_ttl = 60
    tmpt_headless_timeout = 30
    tmpt_workers_dir = None  # unused in cache tests


def test_cache_key_stable():
    url = "https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7"
    assert _cache_key("proxy-a", url) == _cache_key("proxy-a", url)
    assert _cache_key("proxy-a", url) != _cache_key("proxy-b", url)
    assert _cache_key("", url) == _cache_key("direct", url)


def test_pool_cache_hit():
    pool = HeadlessTmptPool(_FakeSettings())  # type: ignore[arg-type]
    result = _result(proxy="p1")
    pool._cache[result.cache_key] = result
    assert pool._fresh(result) is True
    assert pool._fresh(_result(proxy="p1", age=120)) is False