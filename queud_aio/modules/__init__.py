"""Site and signup modules — one adapter per venue/platform."""

from queud_aio.modules.registry import SiteModule, detect_site, get_site, list_sites
from queud_aio.modules.signups import SignupModule, SignupResult, detect_signup, list_signups

__all__ = [
    "SiteModule",
    "SignupModule",
    "SignupResult",
    "detect_site",
    "detect_signup",
    "get_site",
    "list_signups",
    "list_sites",
]