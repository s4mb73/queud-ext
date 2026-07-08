"""Smoke test: lock + PUT commit + basket count."""
from __future__ import annotations

from queud_aio.availability import (
    area_id_map,
    csrf_token_from_html,
    fetch_event_config,
    parse_availability,
    fetch_availability,
)
from queud_aio.client import TmptClient
from queud_aio.cart import (
    basket_item_count,
    cart_api_headers,
    commit_locked_seats,
    lock_best_available_pair,
    purge_seat_locks,
)
from queud_aio.proxy import pick_proxy_line
from queud_aio.session import ensure_page_access
from queud_aio.settings import Settings


def main() -> int:
    settings = Settings.load()
    target = settings.event_targets[0]
    page_url = target.page_url(settings.base_url)

    client = TmptClient(settings, proxy_line=pick_proxy_line(settings))
    try:
        resp, _ = ensure_page_access(client, page_url, settings)
        csrf = csrf_token_from_html(resp.text)
        config = fetch_event_config(client, target, settings)
        areas = area_id_map(config)
        availability = fetch_availability(client, target, config, settings)
        pairs, _ = parse_availability(availability, settings.tickets_required)
        pair = next(p for p in pairs if p.section == "Block 109" and p.seat_count >= 2)
        area_id = areas[pair.section]

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
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())