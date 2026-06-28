from rugby_sa.cookie_export import playwright_cookies_to_editor
from rugby_sa.models import EventSnapshot, SeatPair
from rugby_sa.notify import build_discord_embed
from rugby_sa.settings import EventTarget, Settings


def test_playwright_cookies_to_editor_format():
    raw = [
        {
            "name": "SID",
            "value": "abc",
            "domain": ".springboks.tmtickets.co.za",
            "path": "/",
            "expires": -1,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }
    ]
    out = playwright_cookies_to_editor(raw)
    assert out[0]["name"] == "SID"
    assert out[0]["session"] is True


def test_discord_embed_mentions_cookie_attachment_when_carted():
    settings = Settings.load()
    target = EventTarget(42, 7)
    snapshot = EventSnapshot(
        target=target,
        url=target.page_url(settings.base_url),
        title="Event Information Screen - eTickets",
        blocked=False,
        needs_login=False,
        pairs=[SeatPair("Block 109", 6, "B", "1", "2", 2)],
        carted=True,
        checkout_cookies=[{"name": "SID", "value": "x", "domain": ".springboks.tmtickets.co.za"}],
        settings=settings,
    )
    embed = build_discord_embed(snapshot, settings)
    assert "Cookie-Editor" in embed["description"]
    assert "cookies_checkout.json" in embed["description"]
    assert embed["title"] == "Tickets Available"
    field_names = [f["name"] for f in embed["fields"]]
    assert field_names == ["Section", "Row", "Seats", "Price (ea)", "Qty", "Total"]