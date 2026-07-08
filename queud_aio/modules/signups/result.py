"""Signup result types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignupResult:
    ok: bool
    status_code: int
    message: str
    module_id: str
    form_url: str