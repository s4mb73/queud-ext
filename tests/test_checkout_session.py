"""Tests for checkout_session helpers."""

from queud_aio.checkout_session import merge_parsed_meta


def test_merge_parsed_meta_fills_gaps():
    parsed = {"section": "—", "row": "—", "seat_start": "1", "seat_end": "2", "price": "—", "size": "—"}
    saved = {"section": "Block 109", "price": "R100", "size": "Block 109"}
    out = merge_parsed_meta(parsed, saved)
    assert out["section"] == "Block 109"
    assert out["price"] == "R100"
    assert out["seat_start"] == "1"