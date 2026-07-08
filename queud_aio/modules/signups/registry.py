"""Signup module registry — map form URLs / CSV Module column to handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from queud_aio.modules.signups.result import SignupResult
from queud_aio.modules.signups import uk_umg


@dataclass(frozen=True)
class SignupModule:
    id: str
    name: str
    hosts: tuple[str, ...]
    default_form_url: str
    submit: Callable[..., SignupResult]

    def host_matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == h or host.endswith(f".{h}") for h in self.hosts)


_SIGNUPS: dict[str, SignupModule] = {
    "uk-umg": SignupModule(
        id="uk-umg",
        name="UK UMG Newsletter",
        hosts=("uk-umg.com",),
        default_form_url=uk_umg.DEFAULT_FORM_URL,
        submit=uk_umg.submit,
    ),
}


def list_signups() -> tuple[SignupModule, ...]:
    return tuple(_SIGNUPS.values())


def get_signup(module_id: str) -> SignupModule:
    key = module_id.strip().lower()
    if key not in _SIGNUPS:
        known = ", ".join(sorted(_SIGNUPS))
        raise ValueError(f"Unknown signup module {module_id!r} — available: {known}")
    return _SIGNUPS[key]


def detect_signup(url: str = "", hint: str = "") -> SignupModule:
    if hint.strip():
        return get_signup(hint)
    if url.strip():
        for module in _SIGNUPS.values():
            if module.host_matches(url):
                return module
        host = urlparse(url).hostname or url
        raise ValueError(
            f"No signup module for host {host!r} — set Module column in CSV or use --module"
        )
    raise ValueError(
        "No signup module — set Module column in CSV, use --module, or include a form URL"
    )


def resolve_form_url(url: str, module: SignupModule) -> str:
    cleaned = url.strip()
    if cleaned:
        return cleaned
    if not module.default_form_url:
        raise ValueError(
            f"Module {module.id!r} needs a form URL in CSV or --form-url"
        )
    return module.default_form_url