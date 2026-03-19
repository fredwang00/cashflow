import sqlite3

from cashflow.parsers.expense_report import ExpenseRow


def match_expense_report(
    conn: sqlite3.Connection, rows: list[ExpenseRow]
) -> tuple[int, int]:
    """Match expense report rows to transactions by date + amount.

    Returns (matched, unmatched).
    """
    matched = 0
    unmatched = 0
    for row in rows:
        txn = conn.execute(
            "SELECT id FROM transactions "
            "WHERE date = ? AND ABS(amount - ?) < 0.005 "
            "AND canonical_id IS NULL AND is_reimbursed = 0",
            (row.date.isoformat(), row.amount),
        ).fetchone()
        if txn:
            conn.execute(
                "UPDATE transactions SET is_reimbursed = 1 WHERE id = ?",
                (txn["id"],),
            )
            matched += 1
        else:
            unmatched += 1
    conn.commit()
    return matched, unmatched
