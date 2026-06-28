"""Tests for availability parsing."""

from rugby_sa.availability import parse_availability
from rugby_sa.models import SeatPair


def _sample_section(
    name: str = "Block 109",
    price_level: int = 6,
    rows: list[str] | None = None,
    seats: list[str] | None = None,
    encoded: list[str] | None = None,
) -> dict:
    rows = rows or [{"Name": "A"}, {"Name": "B"}]
    seats = seats or ["1", "2", "3", "4"]
    encoded = encoded or ["01,16"]
    return {
        "SectionName": name,
        "PriceLevel": price_level,
        "RowNames": rows,
        "SeatNames": seats,
        "ExtendedTicketTypes": encoded,
        "StatusSummary": [{"Code": "01", "Symbol": "A"}],
    }


def test_parse_availability_finds_adjacent_pair():
    data = {"Sections": [_sample_section(encoded=["01,4"])]}
    pairs, total = parse_availability(data, min_seats=2)
    assert total == 4
    assert len(pairs) == 1
    assert pairs[0] == SeatPair(
        section="Block 109",
        price_level=6,
        row="A",
        seat_start="1",
        seat_end="4",
        seat_count=4,
    )


def test_parse_availability_exact_pair_only():
    data = {
        "Sections": [
            _sample_section(
                encoded=["01,1", "02,1", "01,2"],
            )
        ]
    }
    pairs, total = parse_availability(data, min_seats=2)
    assert total == 3
    assert len(pairs) == 1
    assert pairs[0].seat_count == 2
    assert pairs[0].seat_start == "3"
    assert pairs[0].seat_end == "4"


def test_parse_availability_no_pairs_when_gap():
    data = {"Sections": [_sample_section(encoded=["01,1", "02,1", "01,1"])]}
    pairs, total = parse_availability(data, min_seats=2)
    assert total == 2
    assert pairs == []