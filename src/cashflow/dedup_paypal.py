import sqlite3


def link_paypal_to_cards(conn: sqlite3.Connection) -> int:
    """Link PayPal transactions to their card counterparts.

    When you pay via PayPal with a credit card, the charge appears on both
    the PayPal export and the card statement. This links the PayPal row to
    the card row via canonical_id so it's excluded from spending totals.

    Returns the number of newly linked transactions.
    """
    paypal_acct = conn.execute(
        "SELECT id FROM accounts WHERE name = 'PayPal'"
    ).fetchone()
    if not paypal_acct:
        return 0
    paypal_id = paypal_acct["id"]

    unlinked = conn.execute(
        "SELECT id, date, amount FROM transactions "
        "WHERE account_id = ? AND canonical_id IS NULL",
        (paypal_id,),
    ).fetchall()

    linked = 0
    for p in unlinked:
        card = conn.execute(
            "SELECT id FROM transactions "
            "WHERE account_id != ? AND canonical_id IS NULL "
            "AND ABS(amount - ?) < 0.005 "
            "AND date BETWEEN date(?, '-3 days') AND date(?, '+3 days') "
            "AND LOWER(merchant) LIKE '%paypal%' "
            "ORDER BY ABS(julianday(date) - julianday(?)) "
            "LIMIT 1",
            (paypal_id, p["amount"], p["date"], p["date"], p["date"]),
        ).fetchone()
        if card:
            conn.execute(
                "UPDATE transactions SET canonical_id = ? WHERE id = ?",
                (card["id"], p["id"]),
            )
            linked += 1
    conn.commit()
    return linked
