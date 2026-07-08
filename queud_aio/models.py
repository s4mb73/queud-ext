"""Domain models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from queud_aio.settings import EventTarget, Settings


@dataclass
class SeatPair:
    section: str
    price_level: int
    row: str
    seat_start: str
    seat_end: str
    seat_count: int

    def label(self) -> str:
        if self.seat_start == self.seat_end:
            return f"{self.section} row {self.row} seat {self.seat_start}"
        return (
            f"{self.section} row {self.row} seats {self.seat_start}-{self.seat_end}"
            f" (level {self.price_level})"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "price_level": self.price_level,
            "row": self.row,
            "seat_start": self.seat_start,
            "seat_end": self.seat_end,
            "seat_count": self.seat_count,
        }


@dataclass
class EventSnapshot:
    target: EventTarget
    url: str
    title: str
    blocked: bool
    needs_login: bool
    pairs: list[SeatPair] = field(default_factory=list)
    total_available_seats: int = 0
    carted: bool = False
    price_labels: dict[int, str] = field(default_factory=dict)
    event_name: str = ""
    event_date: str = ""
    venue: str = ""
    event_image: str = ""
    checkout_cookies: list[dict[str, Any]] | None = None
    checkout_adonis_url: str = ""
    checkout_adonis_reserve_url: str = ""
    checkout_proxy_line: str = ""
    settings: Settings | None = None

    @property
    def event_id(self) -> int:
        return self.target.event_id

    def _s(self) -> Settings:
        return self.settings or Settings.load()

    def matching_pairs(self) -> list[SeatPair]:
        s = self._s()
        pairs = self.pairs
        if s.exact_pairs_only:
            pairs = [p for p in pairs if p.seat_count == s.tickets_required]
        return [p for p in pairs if p.seat_count >= s.tickets_required]

    def fingerprint(self) -> str:
        matching = self.matching_pairs()
        payload = {
            "event_id": self.target.event_id,
            "position": self.target.position,
            "blocked": self.blocked,
            "needs_login": self.needs_login,
            "total_available_seats": self.total_available_seats,
            "pair_run_count": len(matching),
            "exact_pair_count": sum(
                1 for p in matching if p.seat_count == self._s().tickets_required
            ),
            "carted": self.carted,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def has_target_stock(self) -> bool:
        return bool(self.matching_pairs())

    def best_pair(self) -> SeatPair | None:
        matching = self.matching_pairs()
        if not matching:
            return None
        req = self._s().tickets_required
        exact = [p for p in matching if p.seat_count == req]
        return exact[0] if exact else matching[0]

    def price_for_pair(self, pair: SeatPair) -> str:
        return self.price_labels.get(pair.price_level, f"Level {pair.price_level}")

    def event_display_name(self) -> str:
        if self.event_name:
            return self.event_name
        if self.title and "eTickets" not in self.title:
            return self.title
        return f"Springboks Event {self.target.event_id}"

    def summary_lines(self) -> list[str]:
        s = self._s()
        lines = [
            f"Event {self.target.event_id} (position={self.target.position}): "
            f"{self.title or '(no title)'}"
        ]
        if self.blocked:
            lines.append("Status: BLOCKED (EPSF/Queue-it)")
        elif self.needs_login:
            lines.append("Status: login required")
        else:
            matching = self.matching_pairs()
            if not matching:
                lines.append(
                    f"Status: no adjacent x{s.tickets_required} unrestricted seats"
                )
            else:
                exact = [p for p in matching if p.seat_count == s.tickets_required]
                lines.append(
                    f"Pairs: {len(matching)} adjacent runs "
                    f"({len(exact)} exact x{s.tickets_required}, "
                    f"{self.total_available_seats} seats total)"
                )
                show = exact[:8] if exact else matching[:8]
                for pair in show:
                    lines.append(f"  - {pair.label()}")
                if len(show) < len(matching):
                    lines.append(f"  - ... +{len(matching) - len(show)} more")
        if self.carted:
            lines.append("Cart: seats added to basket")
        lines.append(self.target.page_url(s.base_url))
        return lines