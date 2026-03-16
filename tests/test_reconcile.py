from datetime import date
from cashflow.seed import seed_all
from cashflow.parsers.amazon import AmazonOrder, AmazonItem
from cashflow.reconcile import store_amazon_orders, reconcile_amazon


def _insert_chase_txn(db, source_id, order_number, amount, txn_date="2026-03-10"):
    desc = f"AMAZON MKTPL*TEST Amzn.com/bill WA Order Number {order_number}"
    db.execute(
        "INSERT INTO transactions "
        "(source_id, date, amount, description, merchant, account_id, "
        "status, confidence, who, source_type) "
        "VALUES (?, ?, ?, ?, 'Amazon Marketplace', 1, 'pending', 0, 'shared', 'csv')",
        (source_id, txn_date, amount, desc),
    )
    db.commit()


def test_store_amazon_orders_inserts_items(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder", is_subscribe_save=True, delivery_frequency="Every 3 months")],
        ),
    ]
    stored = store_amazon_orders(db, orders)
    assert stored == 1
    row = db.execute("SELECT * FROM amazon_items").fetchone()
    assert row["order_number"] == "114-1572664-8121843"
    assert row["item_name"] == "Creatine Powder"
    assert row["is_subscribe_save"] == 1
    assert row["delivery_frequency"] == "Every 3 months"
    assert row["account"] == "fred"


def test_store_amazon_orders_skips_duplicates(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)
    stored = store_amazon_orders(db, orders)
    assert stored == 0


def test_store_amazon_orders_multi_item(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="113-3593273-0513822",
            order_date=date(2026, 2, 12),
            total=44.52,
            account="fred",
            items=[
                AmazonItem(name="tarte face tape foundation"),
                AmazonItem(name="BS-MALL Makeup Brush Set"),
            ],
        ),
    ]
    store_amazon_orders(db, orders)
    rows = db.execute(
        "SELECT * FROM amazon_items WHERE order_number = '113-3593273-0513822'"
    ).fetchall()
    assert len(rows) == 2


def test_reconcile_matches_by_order_number(db):
    seed_all(db)
    _insert_chase_txn(db, "chase-1", "114-1572664-8121843", 38.16)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)
    matched = reconcile_amazon(db)
    assert matched == 1
    item = db.execute("SELECT * FROM amazon_items WHERE order_number = '114-1572664-8121843'").fetchone()
    assert item["transaction_id"] is not None
    txn = db.execute("SELECT * FROM transactions WHERE id = ?", (item["transaction_id"],)).fetchone()
    assert txn["source_id"] == "chase-1"


def test_reconcile_skips_already_linked(db):
    seed_all(db)
    _insert_chase_txn(db, "chase-1", "114-1572664-8121843", 38.16)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)
    reconcile_amazon(db)
    matched = reconcile_amazon(db)
    assert matched == 0


def test_reconcile_unmatched_items_stay_null(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="999-0000000-0000000",
            order_date=date(2026, 3, 10),
            total=25.00,
            account="fred",
            items=[AmazonItem(name="Mystery Item")],
        ),
    ]
    store_amazon_orders(db, orders)
    matched = reconcile_amazon(db)
    assert matched == 0
    item = db.execute("SELECT * FROM amazon_items WHERE order_number = '999-0000000-0000000'").fetchone()
    assert item["transaction_id"] is None
