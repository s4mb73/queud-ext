import base64
import json
from urllib.parse import parse_qs, urlparse

from rugby_sa.adonis import (
    adonis_internet_shortcut,
    adonis_launcher_html,
    build_adonis_checkout_url,
    build_adonis_reserve_urls,
    build_adonis_webhook_text,
    decode_adonis_payload,
    filter_checkout_cookies,
    playwright_cookies_to_adonis,
    proxy_line_to_url,
)


def test_playwright_cookies_to_adonis_uses_httponly_key():
    raw = [
        {
            "name": "SID",
            "value": "abc",
            "domain": ".springboks.tmtickets.co.za",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        }
    ]
    out = playwright_cookies_to_adonis(raw)
    assert out[0]["httponly"] is True
    assert "httpOnly" not in out[0]


def test_filter_checkout_cookies_drops_google_noise():
    raw = [
        {
            "name": "_GRECAPTCHA",
            "value": "x",
            "domain": "www.google.com",
            "path": "/",
        },
        {
            "name": "SID",
            "value": "y",
            "domain": ".springboks.tmtickets.co.za",
            "path": "/",
        },
    ]
    out = filter_checkout_cookies(raw)
    assert len(out) == 1
    assert out[0]["name"] == "SID"


def test_build_adonis_checkout_url_matches_adonis_payload_shape():
    raw = [
        {
            "name": "SID",
            "value": "abc",
            "domain": "springboks.tmtickets.co.za",
            "path": "/",
            "httpOnly": False,
            "secure": True,
        }
    ]
    proxy_line = "evo-pro.wiredproxies.com:61234:user-session-test:secret"
    checkout = "https://springboks.tmtickets.co.za/Checkout/Basket"
    url = build_adonis_checkout_url(raw, checkout, proxy_line=proxy_line)

    assert url.startswith("https://adonisbots.com/?extension=")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    payload = json.loads(base64.b64decode(params["extension"][0]))
    assert set(payload.keys()) == {"cookies", "local_storage", "session_storage"}
    assert payload["local_storage"] is None
    assert payload["session_storage"] is None
    assert payload["cookies"][0]["name"] == "SID"
    assert payload["cookies"][0]["domain"] == ".springboks.tmtickets.co.za"
    assert params["endUrl"][0] == checkout
    assert "user-session-test" in params["proxy"][0]
    assert proxy_line_to_url(proxy_line).startswith("http://")


def test_adonis_launcher_html_redirects_to_checkout_url():
    checkout = "https://adonisbots.com/?extension=abc&endUrl=https%3A%2F%2Fexample"
    page = adonis_launcher_html(checkout)
    assert "window.location.replace" in page
    assert checkout in page


def test_decode_adonis_payload_round_trip():
    raw = [
        {
            "name": "SID",
            "value": "abc",
            "domain": "springboks.tmtickets.co.za",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        }
    ]
    url = build_adonis_checkout_url(raw, "https://springboks.tmtickets.co.za/Checkout/Basket")
    ext = url.split("extension=")[1].split("&endUrl=")[0]
    payload = decode_adonis_payload(ext)
    assert payload["cookies"][0]["httponly"] is True
    assert payload["local_storage"] is None


def test_build_adonis_reserve_urls_splits_proxy():
    raw = [
        {
            "name": "SID",
            "value": "abc",
            "domain": ".springboks.tmtickets.co.za",
            "path": "/",
            "httpOnly": False,
            "secure": True,
        }
    ]
    checkout = "https://springboks.tmtickets.co.za/Checkout/Basket"
    proxy_line = "evo-pro.wiredproxies.com:61234:user:secret"
    reserve, proxy = build_adonis_reserve_urls(raw, checkout, proxy_line=proxy_line)
    assert "proxy=" not in reserve
    assert "proxy=" in proxy


def test_build_adonis_webhook_text_format():
    text = build_adonis_webhook_text(
        reserve_url="http://links.adonisbots.com/abc/",
        proxy_url="http://links.adonisbots.com/abc/?proxy=http://x",
        store="Springboks TM Tickets",
        price="R3,300.00",
        product="Springboks vs All Blacks",
        email="test@example.com",
        quantity=2,
        section="Block 109",
        row="B",
        seat_start="1",
        seat_end="2",
    )
    assert "Successful reserve {http://links.adonisbots.com/abc/}" in text
    assert "Proxy URL {http://links.adonisbots.com/abc/?proxy=http://x}" in text


def test_adonis_internet_shortcut_format():
    shortcut = adonis_internet_shortcut("https://adonisbots.com/?extension=abc")
    assert shortcut.startswith("[InternetShortcut]")
    assert "URL=https://adonisbots.com/?extension=abc" in shortcut