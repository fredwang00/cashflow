import sqlite3
from datetime import timedelta

from cashflow.parsers.expense_report import ExpenseRow

_DATE_WINDOW = 7  # days of tolerance for card posting delay
_REPAYMENT_LOOKBACK_DAYS = 90


def link_recorded_reimbursements(conn: sqlite3.Connection) -> int:
    """Link checking credits that repay a reimbursement already recorded by hand.

    `cashflow reimburse` nets a repayment against the original charge, so when the
    repayment later arrives as a deposit, counting the deposit too would double it.
    Only a unique exact-amount match on a charge from the prior 90 days is linked.

    Returns the number of newly linked credits.
    """
    credits = conn.execute(
        "SELECT t.id, t.date, t.amount FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE a.name = 'Checking' AND t.amount < 0 AND t.canonical_id IS NULL ORDER BY t.date, t.id"
    ).fetchall()
    linked = 0
    for credit in credits:
        matches = conn.execute(
            "SELECT id FROM transactions WHERE canonical_id IS NULL AND amount > 0 "
            "AND ABS(reimbursed_amount - ?) < 0.005 AND date <= ? AND date >= date(?, ?) "
            "AND id NOT IN (SELECT canonical_id FROM transactions WHERE canonical_id IS NOT NULL AND amount < 0)",
            (-credit["amount"], credit["date"], credit["date"], f"-{_REPAYMENT_LOOKBACK_DAYS} days"),
        ).fetchall()
        if len(matches) == 1:
            conn.execute("UPDATE transactions SET canonical_id = ? WHERE id = ?", (matches[0]["id"], credit["id"]))
            linked += 1
    conn.commit()
    return linked


def _find_transaction(conn, row):
    """Return a unique exact-date candidate, or a unique posting-window candidate."""
    # Exact date match
    candidates = conn.execute(
        "SELECT id, is_reimbursed FROM transactions "
        "WHERE date = ? AND ABS(amount - ?) < 0.005 "
        "AND canonical_id IS NULL",
        (row.date.isoformat(), row.amount),
    ).fetchall()
    if candidates:
        return candidates[0] if len(candidates) == 1 else None

    # Fuzzy date match: card may post days before or after expense
    start = (row.date - timedelta(days=_DATE_WINDOW)).isoformat()
    end = (row.date + timedelta(days=_DATE_WINDOW)).isoformat()
    candidates = conn.execute(
        "SELECT id, is_reimbursed FROM transactions "
        "WHERE date BETWEEN ? AND ? AND ABS(amount - ?) < 0.005 "
        "AND canonical_id IS NULL",
        (start, end, row.amount),
    ).fetchall()
    return candidates[0] if len(candidates) == 1 else None


def match_expense_report(
    conn: sqlite3.Connection, rows: list[ExpenseRow]
) -> tuple[int, int, int]:
    """Match expense report rows to transactions by date + amount.

    Tries exact date first, then falls back to a +/- 7 day window
    to handle card posting delays (common with Uber, hotels, etc.).
    Ambiguous candidates remain unmatched for manual review.

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
                "UPDATE transactions SET is_reimbursed = 1, reimbursed_amount = amount WHERE id = ?",
                (txn["id"],),
            )
            matched += 1
        else:
            unmatched += 1
    conn.commit()
    return matched, already, unmatched
