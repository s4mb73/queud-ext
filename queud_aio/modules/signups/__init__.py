"""Newsletter / pre-sale signup modules."""

from queud_aio.modules.signups.registry import SignupModule, detect_signup, get_signup, list_signups
from queud_aio.modules.signups.result import SignupResult

__all__ = [
    "SignupModule",
    "SignupResult",
    "detect_signup",
    "get_signup",
    "list_signups",
]