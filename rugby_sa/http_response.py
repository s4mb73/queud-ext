"""Normalized HTTP response wrapper."""

from __future__ import annotations

import json
from typing import Any


class HttpLikeResponse:
    """Common response shape for curl_cffi and Playwright request clients."""

    def __init__(
        self,
        *,
        status_code: int,
        text: str,
        url: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text[:200]}")