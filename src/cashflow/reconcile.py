import re
import sqlite3
from cashflow.parsers.amazon import AmazonOrder

ORDER_NUMBER_RE = re.compile(r"(\d{3}-\d{7}-\d{7})")
DIGITAL_ORDER_RE = re.compile(r"(D\d{2}-\d{7}-\d{7})")


def store_amazon_orders(conn: sqlite3.Connection, orders: list[AmazonOrder]) -> int:
    """Store parsed Amazon orders as amazon_items rows.

    Returns count of newly stored items. Skips duplicates
    (same order_number + item_name combination).
    """
    inserted = 0
    for order in orders:
        for item in order.items:
            existing = conn.execute(
                "SELECT id FROM amazon_items WHERE order_number = ? AND item_name = ?",
                (order.order_number, item.name),
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO amazon_items "
                "(order_number, item_name, price, order_date, account, "
                "is_subscribe_save, delivery_frequency) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    order.order_number,
                    item.name,
                    order.total if len(order.items) == 1 else 0.0,
                    order.order_date.isoformat(),
                    order.account,
                    item.is_subscribe_save,
                    item.delivery_frequency,
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def reconcile_amazon(conn: sqlite3.Connection) -> int:
    """Match unlinked amazon_items to transactions via order number.

    Scans transaction descriptions for order numbers and links matching
    amazon_items by setting their transaction_id.

    Returns count of newly matched items.
    """
    unlinked = conn.execute(
        "SELECT id, order_number FROM amazon_items WHERE transaction_id IS NULL"
    ).fetchall()

    if not unlinked:
        return 0

    order_items: dict[str, list[int]] = {}
    for item in unlinked:
        order_items.setdefault(item["order_number"], []).append(item["id"])

    transactions = conn.execute(
        "SELECT id, description FROM transactions WHERE canonical_id IS NULL"
    ).fetchall()

    matched = 0
    for txn in transactions:
        match = ORDER_NUMBER_RE.search(txn["description"])
        if not match:
            match = DIGITAL_ORDER_RE.search(txn["description"])
        if not match:
            continue

        order_num = match.group(1)
        item_ids = order_items.get(order_num)
        if not item_ids:
            continue

        for item_id in item_ids:
            conn.execute(
                "UPDATE amazon_items SET transaction_id = ? WHERE id = ?",
                (txn["id"], item_id),
            )
            matched += 1

        del order_items[order_num]

    conn.commit()
    return matched
