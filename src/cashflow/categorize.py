import sqlite3


def categorize_by_rules(conn: sqlite3.Connection) -> tuple[int, int]:
    """Apply merchant_rules to pending uncategorized transactions.

    Returns (matched_count, unmatched_count).
    Matched transactions get status='confirmed' and the rule's category_id.
    """
    rules = conn.execute(
        "SELECT id, pattern, category_id, confidence FROM merchant_rules"
    ).fetchall()

    pending = conn.execute(
        "SELECT id, merchant FROM transactions "
        "WHERE status = 'pending' AND category_id IS NULL AND canonical_id IS NULL"
    ).fetchall()

    matched = 0
    unmatched = 0

    for txn in pending:
        txn_merchant = txn["merchant"].lower()
        rule_hit = None

        for rule in rules:
            if rule["pattern"].lower() in txn_merchant:
                rule_hit = rule
                break

        if rule_hit:
            conn.execute(
                "UPDATE transactions SET category_id = ?, status = 'confirmed', "
                "confidence = ? WHERE id = ?",
                (rule_hit["category_id"], rule_hit["confidence"], txn["id"]),
            )
            conn.execute(
                "UPDATE merchant_rules SET match_count = match_count + 1 WHERE id = ?",
                (rule_hit["id"],),
            )
            matched += 1
        else:
            unmatched += 1

    conn.commit()
    return matched, unmatched
