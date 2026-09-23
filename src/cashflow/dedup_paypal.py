import sqlite3


def link_paypal_to_cards(conn: sqlite3.Connection) -> int:
    """Link PayPal transactions to their card counterparts.

    When you pay via PayPal with a credit card, the charge appears on both
    the PayPal export and the card statement. This links the PayPal row to
    the card row via canonical_id so it's excluded from spending totals.

    Only mutually unique matches are linked; ambiguous payments remain visible.
    Previously linked card charges cannot be used for another PayPal payment.

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

    # Resolve the whole candidate graph before writing: choosing a row in a
    # loop would make competing equal payments depend on import order.
    candidates = {}
    card_users: dict[int, list[int]] = {}
    for payment in unlinked:
        cards = conn.execute(
            "SELECT t.id FROM transactions t "
            "JOIN accounts a ON a.id = t.account_id "
            "WHERE a.type = 'credit' AND t.canonical_id IS NULL "
            "AND ABS(t.amount - ?) < 0.005 "
            "AND t.date BETWEEN date(?, '-3 days') AND date(?, '+3 days') "
            "AND LOWER(t.merchant) LIKE '%paypal%' "
            "AND NOT EXISTS (SELECT 1 FROM transactions linked "
            "WHERE linked.account_id = ? AND linked.canonical_id = t.id)",
            (payment["amount"], payment["date"], payment["date"], paypal_id),
        ).fetchall()
        candidates[payment["id"]] = [card["id"] for card in cards]
        for card in cards:
            card_users.setdefault(card["id"], []).append(payment["id"])

    linked = 0
    for payment_id, card_ids in candidates.items():
        if len(card_ids) != 1 or len(card_users[card_ids[0]]) != 1:
            continue
        conn.execute(
            "UPDATE transactions SET canonical_id = ? WHERE id = ?",
            (card_ids[0], payment_id),
        )
        linked += 1
    conn.commit()
    return linked
