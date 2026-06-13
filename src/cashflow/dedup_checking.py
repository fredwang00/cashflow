import sqlite3


def link_checking_duplicates(conn: sqlite3.Connection) -> int:
    """Link duplicate checking transactions across overlapping statement exports.

    BofA exports from different checking accounts (or overlapping date ranges)
    can produce the same transaction with different source_ids because the raw
    description text varies (e.g. masked vs unmasked account numbers). This
    finds same-date, same-amount, same-merchant pairs within the Checking
    account and links the newer row to the older one via canonical_id.

    Returns the number of newly linked transactions.
    """
    checking_acct = conn.execute(
        "SELECT id FROM accounts WHERE name = 'Checking'"
    ).fetchone()
    if not checking_acct:
        return 0
    checking_id = checking_acct["id"]

    dupes = conn.execute(
        "SELECT date, merchant, amount, MIN(id) as keep_id, GROUP_CONCAT(id) as all_ids "
        "FROM transactions "
        "WHERE account_id = ? AND canonical_id IS NULL "
        "GROUP BY date, merchant, amount "
        "HAVING COUNT(*) > 1",
        (checking_id,),
    ).fetchall()

    linked = 0
    for row in dupes:
        keep_id = row["keep_id"]
        all_ids = [int(x) for x in row["all_ids"].split(",")]
        for dup_id in all_ids:
            if dup_id == keep_id:
                continue
            conn.execute(
                "UPDATE transactions SET canonical_id = ? WHERE id = ?",
                (keep_id, dup_id),
            )
            linked += 1
    conn.commit()
    return linked
