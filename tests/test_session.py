"""Tests for session tmpt refresh heuristics."""

from types import SimpleNamespace

from rugby_sa.session import needs_tmpt_refresh


class _FakeJar:
    def __init__(self, names: set[str]) -> None:
        self._names = names

    def __iter__(self):
        for name in self._names:
            yield SimpleNamespace(
                name=name,
                value="x",
                domain="springboks.tmtickets.co.za",
                path="/",
            )


class _FakeSession:
    def __init__(self, cookie_names: set[str]) -> None:
        self.cookies = SimpleNamespace(jar=_FakeJar(cookie_names))


class _FakeClient:
    def __init__(self, cookie_names: set[str]) -> None:
        self.session = _FakeSession(cookie_names)


class _FakeSettings:
    base_url = "https://springboks.tmtickets.co.za"


def _resp(status: int, html: str):
    return SimpleNamespace(status_code=status, text=html)


def test_needs_tmpt_when_missing_cookie():
    client = _FakeClient(set())
    html = "<title>Let's Get Your Identity Verified</title>"
    assert needs_tmpt_refresh(client, _resp(403, html), _FakeSettings()) is True


def test_no_tmpt_refresh_when_cookie_present_on_epsf_page():
    client = _FakeClient({"tmpt"})
    html = (
        "<title>Let's Get Your Identity Verified</title>"
        "Browsing Activity Has Been Paused"
    )
    assert needs_tmpt_refresh(client, _resp(403, html), _FakeSettings()) is False


def test_tmpt_refresh_on_401_even_with_cookie():
    client = _FakeClient({"tmpt"})
    assert needs_tmpt_refresh(client, _resp(401, "x"), _FakeSettings()) is True