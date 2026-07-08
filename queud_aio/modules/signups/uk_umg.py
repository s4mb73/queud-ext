"""UK Universal Music Group newsletter / pre-sale signup forms."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

from queud_aio.modules.signups.result import SignupResult
from queud_aio.wreq_adapter import WreqHttpSession

_FORM_PATH_RE = re.compile(r"/um-forms/(\d+-\d+)\.html", re.I)
_FORM_TAG_RE = re.compile(r"<form\b[^>]*>.*?</form>", re.I | re.DOTALL)
_ACTION_RE = re.compile(r"""action=["']([^"']+)["']""", re.I)
_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
_NAME_RE = re.compile(r"""name=["']([^"']+)["']""", re.I)
_VALUE_RE = re.compile(r"""value=["']([^"']*)["']""", re.I)
_MESSAGE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.I | re.DOTALL)

BASE_URL = "https://uk-umg.com"
DEFAULT_FORM_URL = "https://uk-umg.com/um-forms/74309-1377317.html"
DEFAULT_IMPERSONATE = "chrome124"


@dataclass(frozen=True)
class UkUmgForm:
    form_url: str
    action_url: str
    form_id: str
    hidden_fields: dict[str, str]


def parse_form_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid form URL: {url}")
    if not _FORM_PATH_RE.search(parsed.path):
        raise ValueError(
            f"URL must include /um-forms/<id>.html — got: {url}"
        )
    return url.strip()


def _parse_input_tag(tag: str) -> tuple[str, str] | None:
    type_match = re.search(r"""type=["']([^"']+)["']""", tag, re.I)
    if not type_match or type_match.group(1).lower() != "hidden":
        return None
    name_match = _NAME_RE.search(tag)
    if not name_match:
        return None
    value_match = _VALUE_RE.search(tag)
    return name_match.group(1), value_match.group(1) if value_match else ""


def parse_form_html(form_url: str, html: str) -> UkUmgForm:
    path_match = _FORM_PATH_RE.search(urlparse(form_url).path)
    if not path_match:
        raise ValueError(f"Could not parse form id from {form_url}")
    form_id = path_match.group(1)

    form_match = _FORM_TAG_RE.search(html)
    if not form_match:
        raise ValueError(f"No <form> found on {form_url}")

    form_html = form_match.group(0)
    action_match = _ACTION_RE.search(form_html)
    if not action_match:
        raise ValueError(f"No form action found on {form_url}")

    hidden_fields: dict[str, str] = {}
    for tag in _INPUT_RE.findall(form_html):
        parsed = _parse_input_tag(tag)
        if parsed:
            hidden_fields[parsed[0]] = parsed[1]

    return UkUmgForm(
        form_url=form_url,
        action_url=action_match.group(1),
        form_id=form_id,
        hidden_fields=hidden_fields,
    )


def build_body(
    form: UkUmgForm,
    *,
    email: str,
    country: str = "GB",
    town: str = "",
    universal_recommends: bool = False,
) -> str:
    hidden = form.hidden_fields
    pairs: list[tuple[str, str]] = [
        ("return_data", hidden.get("return_data", "no")),
        ("return_URL", hidden.get("return_URL", "")),
        ("dm_this", hidden.get("dm_this", "1")),
        ("comp_id", hidden.get("comp_id", "")),
        ("uniquecoderequired", hidden.get("uniquecoderequired", "0")),
        ("email", email),
        ("dob_show", hidden.get("dob_show", "not_show")),
        ("dob_show_mandatory", hidden.get("dob_show_mandatory", "not_show")),
        ("year_flag", hidden.get("year_flag", "0")),
        ("dob_year", "0004"),
        ("dob_day", "DD"),
        ("dob_month", "MM"),
        ("dob_year", "0004"),
        ("parent_conf", "CONF"),
        ("town", town),
        ("countrycode", country),
        (
            "privacypolicy",
            hidden.get("privacypolicy", "https://privacy.umusic.com/uk/"),
        ),
        ("chkPrivPol", "yes"),
    ]
    if universal_recommends:
        pairs.append(("dm_otherinternal", "1"))
    return urlencode(pairs)


_KNOWN_MESSAGES = (
    "Thank you for registering your details",
    "The email you have entered is not valid",
    "Valid email address or mobile number is mandatory for sign-up",
)


def classify_response(body: str) -> str:
    lowered = body.lower()
    for phrase in _KNOWN_MESSAGES:
        if phrase.lower() in lowered:
            return phrase

    match = _MESSAGE_RE.search(body)
    if match:
        text = re.sub(r"<[^>]+>", " ", match.group(1))
    else:
        text = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", text).strip()[:200]


def response_ok(status_code: int, body: str) -> bool:
    if status_code != 200:
        return False
    lowered = body.lower()
    return not any(
        phrase in lowered
        for phrase in (
            "not valid",
            "mandatory for sign-up",
            "please enter",
            "go back to the form",
        )
    )


def fetch_form(
    session: WreqHttpSession,
    form_url: str,
) -> UkUmgForm:
    resp = session.get(form_url)
    resp.raise_for_status()
    return parse_form_html(form_url, resp.text)


def submit(
    *,
    form_url: str,
    email: str,
    proxy_url: str = "",
    impersonate: str = DEFAULT_IMPERSONATE,
    country: str = "GB",
    town: str = "",
    universal_recommends: bool = False,
) -> SignupResult:
    form_url = parse_form_url(form_url)
    session = WreqHttpSession(
        impersonate,
        proxy_url=proxy_url,
        base_url=BASE_URL,
    )
    try:
        form = fetch_form(session, form_url)
        body = build_body(
            form,
            email=email,
            country=country,
            town=town,
            universal_recommends=universal_recommends,
        )
        resp = session.post_form(
            form.action_url,
            body,
            headers={
                "Origin": BASE_URL,
                "Referer": f"{BASE_URL}/",
            },
        )
        message = classify_response(resp.text)
        ok = response_ok(resp.status_code, resp.text)
        return SignupResult(
            ok=ok,
            status_code=resp.status_code,
            message=message,
            module_id="uk-umg",
            form_url=form_url,
        )
    finally:
        session.close()