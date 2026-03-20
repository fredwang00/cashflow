import sqlite3
from datetime import timedelta

from cashflow.parsers.expense_report import ExpenseRow

_DATE_WINDOW = 7  # days of tolerance for card posting delay


def _find_transaction(conn, row):
    """Find a matching transaction: exact date first, then within +/- 7 days."""
    # Exact date match
    txn = conn.execute(
        "SELECT id, is_reimbursed FROM transactions "
        "WHERE date = ? AND ABS(amount - ?) < 0.005 "
        "AND canonical_id IS NULL",
        (row.date.isoformat(), row.amount),
    ).fetchone()
    if txn:
        return txn

    # Fuzzy date match: card may post days before or after expense
    start = (row.date - timedelta(days=_DATE_WINDOW)).isoformat()
    end = (row.date + timedelta(days=_DATE_WINDOW)).isoformat()
    txn = conn.execute(
        "SELECT id, is_reimbursed FROM transactions "
        "WHERE date BETWEEN ? AND ? AND ABS(amount - ?) < 0.005 "
        "AND canonical_id IS NULL",
        (start, end, row.amount),
    ).fetchone()
    return txn


def match_expense_report(
    conn: sqlite3.Connection, rows: list[ExpenseRow]
) -> tuple[int, int, int]:
    """Match expense report rows to transactions by date + amount.

    Tries exact date first, then falls back to a +/- 7 day window
    to handle card posting delays (common with Uber, hotels, etc.).

    Returns (matched, already_reimbursed, unmatched).
    """
    matched = 0
    already = 0
    unmatched = 0
    for row in rows:
        txn = _find_transaction(conn, row)
        if txn and txn["is_reimbursed"]:
            already += 1
        elif txn:
            conn.execute(
                "UPDATE transactions SET is_reimbursed = 1 WHERE id = ?",
                (txn["id"],),
            )
            matched += 1
        else:
            unmatched += 1
    conn.commit()
    return matched, already, unmatched
