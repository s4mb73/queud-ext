from pathlib import Path

import pytest

from queud_aio.modules.signups.profiles import (
    load_signup_profiles_csv,
    pick_signup_profile,
    resolve_profile_module,
)
from queud_aio.modules.signups.registry import detect_signup, get_signup, list_signups, resolve_form_url
from queud_aio.modules.signups.uk_umg import (
    DEFAULT_FORM_URL,
    build_body,
    classify_response,
    parse_form_html,
    parse_form_url,
    response_ok,
)
from queud_aio.proxy import load_proxy_file

SAMPLE_FORM = """
<form action="https://zaphod.vvhp.net/inbound/UMGUK74309-1377317" method="post">
  <input type="hidden" name="return_data" value="no" />
  <input type="hidden" name="dm_this" value="1" />
  <input type="text" name="email" />
</form>
"""

FORM_URL = "https://uk-umg.com/um-forms/74309-1377317.html"


def test_parse_form_url_accepts_umg_link():
    assert parse_form_url(FORM_URL) == FORM_URL


def test_parse_form_url_rejects_ticket_link():
    with pytest.raises(ValueError, match="um-forms"):
        parse_form_url("https://springboks.tmtickets.co.za/EDP/Event/Index/42")


def test_parse_form_html_extracts_action_and_hidden_fields():
    form = parse_form_html(FORM_URL, SAMPLE_FORM)
    assert form.form_id == "74309-1377317"
    assert form.action_url.endswith("UMGUK74309-1377317")
    assert form.hidden_fields["return_data"] == "no"
    assert form.hidden_fields["dm_this"] == "1"


def test_build_body_matches_browser_field_order():
    form = parse_form_html(FORM_URL, SAMPLE_FORM)
    body = build_body(form, email="a@test.com", country="GB", town="London")
    assert body.startswith("return_data=no&return_URL=")
    assert "email=a%40test.com" in body
    assert "countrycode=GB" in body
    assert body.count("dob_year=0004") == 2
    assert "parent_conf=CONF" in body


def test_classify_response_extracts_known_phrases():
    html = "<html><body>Thank you for registering your details @media</body></html>"
    assert classify_response(html) == "Thank you for registering your details"

    error = "<pre>The email you have entered is not valid.</pre>"
    assert classify_response(error) == "The email you have entered is not valid"


def test_response_ok_detects_validation_errors():
    assert response_ok(200, "<pre>Welcome aboard</pre>") is True
    assert response_ok(400, "not valid") is False
    assert response_ok(200, "mandatory for sign-up") is False


def test_signup_registry_lists_uk_umg():
    modules = list_signups()
    assert any(m.id == "uk-umg" for m in modules)
    module = get_signup("uk-umg")
    assert module.name == "UK UMG Newsletter"
    assert module.default_form_url == DEFAULT_FORM_URL
    assert detect_signup(FORM_URL).id == "uk-umg"
    assert detect_signup(hint="uk-umg").id == "uk-umg"
    assert resolve_form_url("", module) == DEFAULT_FORM_URL


def test_load_signup_profiles_email_only_csv(tmp_path: Path):
    csv_path = tmp_path / "signups.csv"
    csv_path.write_text(
        "Email\nsignup@test.com\nsecond@test.com\n",
        encoding="utf-8",
    )
    profiles = load_signup_profiles_csv(csv_path)
    assert len(profiles) == 2
    assert profiles[0].email == "signup@test.com"
    module, form_url = resolve_profile_module(profiles[0])
    assert module.id == "uk-umg"
    assert form_url == DEFAULT_FORM_URL


def test_load_signup_profiles_with_optional_url(tmp_path: Path):
    csv_path = tmp_path / "signups.csv"
    csv_path.write_text(
        "URL,Email,Country,Town,Module\n"
        f"{FORM_URL},signup@test.com,GB,Manchester,uk-umg\n",
        encoding="utf-8",
    )
    profile = pick_signup_profile(csv_path)
    assert profile.module == "uk-umg"
    _, form_url = resolve_profile_module(profile)
    assert form_url == FORM_URL


def test_load_proxy_file(tmp_path: Path):
    proxy_path = tmp_path / "proxies.txt"
    proxy_path.write_text(
        "# pool\n"
        "1.2.3.4:8080:user:pass\n"
        "5.6.7.8:8080:user2:pass2\n",
        encoding="utf-8",
    )
    lines = load_proxy_file(proxy_path)
    assert len(lines) == 2
    assert lines[0].startswith("1.2.3.4")