from pathlib import Path
from cashflow.parsers.amazon import parse_amazon_orders

FIXTURE = Path(__file__).parent / "fixtures" / "amazon_orders_sample.txt"


def test_parse_amazon_orders_returns_orders():
    orders = parse_amazon_orders(FIXTURE)
    assert len(orders) > 0


def test_parse_amazon_orders_skips_cancelled():
    orders = parse_amazon_orders(FIXTURE)
    order_numbers = [o.order_number for o in orders]
    assert "112-2408383-4562623" not in order_numbers


def test_parse_amazon_orders_extracts_order_number():
    orders = parse_amazon_orders(FIXTURE)
    assert any(o.order_number == "114-1572664-8121843" for o in orders)


def test_parse_amazon_orders_extracts_total():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.total == 38.16


def test_parse_amazon_orders_extracts_date():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert str(creatine.order_date) == "2026-03-10"


def test_parse_amazon_orders_extracts_items():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert len(creatine.items) == 1
    assert "Creatine" in creatine.items[0].name


def test_parse_amazon_orders_multi_item():
    orders = parse_amazon_orders(FIXTURE)
    makeup = [o for o in orders if o.order_number == "113-3593273-0513822"][0]
    assert len(makeup.items) == 2
    names = [i.name for i in makeup.items]
    assert any("tarte" in n for n in names)
    assert any("BS-MALL" in n for n in names)


def test_parse_amazon_orders_detects_subscribe_save():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.items[0].is_subscribe_save is True
    assert creatine.items[0].delivery_frequency == "Every 3 months"


def test_parse_amazon_orders_non_subscribe_save():
    orders = parse_amazon_orders(FIXTURE)
    makeup = [o for o in orders if o.order_number == "113-3593273-0513822"][0]
    assert makeup.items[0].is_subscribe_save is False


def test_parse_amazon_orders_detects_wife_account():
    orders = parse_amazon_orders(FIXTURE)
    tea = [o for o in orders if o.order_number == "111-4848743-5209032"][0]
    assert tea.account == "wife"


def test_parse_amazon_orders_defaults_to_fred():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.account == "fred"


def test_parse_amazon_orders_includes_zero_total():
    orders = parse_amazon_orders(FIXTURE)
    ninja = [o for o in orders if o.order_number == "113-0558577-8378621"][0]
    assert ninja.total == 0.0
    assert len(ninja.items) == 1
