from queud_aio.basket_meta import parse_basket_html


def test_parse_basket_html_extracts_block_row_seats_price():
    html = """
    <div class="basket-item">
      Block 109 Row B Seats 1-2
      <span>R1,650.00</span>
    </div>
    """
    meta = parse_basket_html(html)
    assert meta["section"] == "Block 109"
    assert meta["row"] == "B"
    assert meta["seat_start"] == "1"
    assert meta["seat_end"] == "2"
    assert "1,650" in meta["price"]
    assert meta["size"] == "Block 109"