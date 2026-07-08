from queud_aio.models import EventSnapshot, SeatPair
from queud_aio.notify import build_discord_embed
from queud_aio.settings import EventTarget, Settings


def test_discord_embed_carted_no_cookie_attachment():
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
        settings=settings,
    )
    embed = build_discord_embed(snapshot, settings)
    assert "Cookie-Editor" not in embed["description"]
    assert "cookies_checkout.json" not in embed["description"]
    assert "Added to basket" in embed["description"]
    assert embed["title"] == "Tickets Available"