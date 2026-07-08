"""Tests for cart safety helpers."""

from dataclasses import replace

from queud_aio.cart import (
    _akamai_blocked,
    _area_id_from_lock,
    _fast_lock_attempts,
    cart_api_headers,
    locked_seats_from_response,
    pair_allowed,
    pick_best_lock_result,
)
from queud_aio.models import SeatPair
from queud_aio.settings import Settings


def _settings(**overrides) -> Settings:
    base = Settings.load()
    return replace(base, **overrides)


def test_area_id_from_lock():
    data = {
        "LockedSeats": [{"AreaId": 42, "YCoord": 1, "XCoord": 2, "PriceBandId": 6}],
    }
    assert _area_id_from_lock(data) == 42


def test_locked_seats_from_main_seat():
    data = {
        "MainSeat": {
            "AreaId": 12,
            "YCoord": 3,
            "XCoord": 7,
            "PriceBandId": 6,
        },
        "CompanionSeats": [
            {"AreaId": 12, "YCoord": 3, "XCoord": 8, "PriceBandId": 6},
        ],
    }
    commits = locked_seats_from_response(data, price_class_id=6)
    assert commits == [
        {"Id": "s_12-3-7", "PriceClassId": 6},
        {"Id": "s_12-3-8", "PriceClassId": 6},
    ]


def test_locked_seats_prefers_numeric_id_from_ba_lock():
    data = {
        "LockedSeats": [
            {"Id": 2503333, "AreaId": 1130, "XCoord": 37, "YCoord": 2},
            {"Id": 2503335, "AreaId": 1130, "XCoord": 38, "YCoord": 2},
        ],
        "PriceBandId": 6,
    }
    commits = locked_seats_from_response(data, price_class_id=6)
    assert commits == [
        {"Id": "2503333", "PriceClassId": 6},
        {"Id": "2503335", "PriceClassId": 6},
    ]


def test_pair_allowed_section_filter():
    pair = SeatPair("Block 109", 6, "B", "1", "2", 2)
    settings = _settings(cart_allowed_sections=frozenset({"Block 110"}))
    assert pair_allowed(pair, settings, {6: "R1,650.00"}) is False


def test_pair_allowed_max_price():
    pair = SeatPair("Block 109", 6, "B", "1", "2", 2)
    settings = _settings(cart_max_price_zar=1000.0)
    assert pair_allowed(pair, settings, {6: "R1,650.00"}) is False
    assert pair_allowed(pair, _settings(cart_max_price_zar=2000.0), {6: "R1,650.00"}) is True


def test_cart_api_headers_minimal_csrf():
    headers = cart_api_headers(
        _settings(),
        "https://springboks.tmtickets.co.za/EDP/Event/Index/42?position=7",
        "token123",
    )
    assert headers == {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "RequestVerificationToken": "token123",
    }
    assert "requestverificationtoken" not in headers
    assert "Origin" not in headers


def test_fast_lock_attempts_section_then_any():
    pair = SeatPair("Block 109", 6, "B", "1", "2", 2)
    event_config = {
        "Areas": [{"Id": 1130, "Name": "Block 109"}, {"Id": 999, "Name": "Block 118"}],
    }
    settings = _settings(cart_lock_attempts=2)
    attempts = _fast_lock_attempts(pair, event_config, settings)
    assert len(attempts) == 2
    assert attempts[0] == ("Block 109", 1130, 6)
    assert attempts[1][0] == "any area"


def test_akamai_blocked_detects_response():
    assert _akamai_blocked('{"response":"block"}') is True
    assert _akamai_blocked("HTTP 403: denied") is True
    assert _akamai_blocked("HTTP 400: bad") is False


def test_pick_best_lock_result_prefers_first_success():
    results = [
        (400, "bad"),
        (200, '{"LockedSeats":[{"AreaId":1}]}'),
        (200, '{"LockedSeats":[{"AreaId":2}]}'),
    ]
    index, parsed = pick_best_lock_result(results)
    assert index == 1
    assert parsed is not None
    assert parsed[1]["LockedSeats"][0]["AreaId"] == 1


def test_pick_best_lock_result_all_failed():
    results = [(400, "a"), (500, "b")]
    index, parsed = pick_best_lock_result(results)
    assert index == -1
    assert parsed is None


def test_pair_allowed_no_filters():
    pair = SeatPair("Block 109", 6, "B", "1", "2", 2)
    settings = _settings(cart_allowed_sections=frozenset(), cart_max_price_zar=None)
    assert pair_allowed(pair, settings, {6: "R1,650.00"}) is True