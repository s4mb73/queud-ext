"""Site module registry — map hosts / CSV Site column to runtime defaults."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SiteModule:
    id: str
    name: str
    base_url: str
    identity_host: str
    store_label: str

    def host_matches(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        base_host = (urlparse(self.base_url).hostname or "").lower()
        return host == base_host or host.endswith(f".{base_host}") or base_host in host


_SITES: dict[str, SiteModule] = {
    "springboks": SiteModule(
        id="springboks",
        name="Springboks TM Tickets",
        base_url="https://springboks.tmtickets.co.za",
        identity_host="https://web-identity.tmtickets.co.uk",
        store_label="Springboks TM Tickets",
    ),
}


def list_sites() -> tuple[SiteModule, ...]:
    return tuple(_SITES.values())


def get_site(site_id: str) -> SiteModule:
    key = site_id.strip().lower()
    if key not in _SITES:
        known = ", ".join(sorted(_SITES))
        raise ValueError(f"Unknown site {site_id!r} — available: {known}")
    return _SITES[key]


def detect_site(url: str, hint: str = "") -> SiteModule:
    if hint.strip():
        return get_site(hint)
    for site in _SITES.values():
        if site.host_matches(url):
            return site
    host = urlparse(url).hostname or url
    raise ValueError(
        f"No site module for host {host!r} — set Site column in CSV or use --site"
    )