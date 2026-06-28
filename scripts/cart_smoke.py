"""Smoke test: lock + PUT commit + basket count."""
from __future__ import annotations

from rugby_sa.availability import (
    area_id_map,
    csrf_token_from_html,
    fetch_event_config,
    parse_availability,
    fetch_availability,
)
from rugby_sa.browser_request import BrowserRequestClient
from rugby_sa.cart import (
    basket_item_count,
    cart_api_headers,
    commit_locked_seats,
    lock_best_available_pair,
    purge_seat_locks,
)
from rugby_sa.proxy import resolve_browser_proxy
from rugby_sa.settings import Settings


def main() -> int:
    settings = Settings.load()
    target = settings.event_targets[0]
    page_url = target.page_url(settings.base_url)

    with BrowserRequestClient(settings, proxy_line=resolve_browser_proxy(settings)) as client:
        resp, _ = client.ensure_event_page(page_url)
        csrf = csrf_token_from_html(client.page.content())
        config = fetch_event_config(client, target, settings)
        areas = area_id_map(config)
        availability = fetch_availability(client, target, config, settings)
        pairs, _ = parse_availability(availability, settings.tickets_required)
        pair = next(p for p in pairs if p.section == "Block 109" and p.seat_count >= 2)
        area_id = areas[pair.section]
        headers = cart_api_headers(settings, page_url, csrf)

        purge_seat_locks(client, config, settings, page_url, target.event_id, csrf)
        ok, lock_data, detail = lock_best_available_pair(
            client,
            target,
            config,
            settings,
            page_url,
            csrf,
            pair.price_level,
            area_id=area_id,
        )
        print("lock ok:", ok, detail[:200] if detail else "")
        if not ok or not lock_data:
            return 1

        ok2, detail2 = commit_locked_seats(
            client,
            target,
            config,
            settings,
            page_url,
            csrf,
            area_id,
            lock_data,
            pair.price_level,
        )
        count = basket_item_count(client, settings, page_url)
        print("commit ok:", ok2, detail2[:200] if detail2 else "")
        print("basket:", count)
        return 0 if count >= settings.tickets_required else 1


if __name__ == "__main__":
    raise SystemExit(main())