import sqlite3
from datetime import date
from pathlib import Path

from cashflow.db import create_schema, store_transactions
from cashflow.models import ParsedTransaction
from cashflow.parsers.expense_report import parse_expense_report
from cashflow.reimburse import match_expense_report
from cashflow.seed import seed_all

FIXTURE = Path(__file__).parent / "fixtures" / "expense_report_sample.xlsx"

def test_parse_expense_report():
    rows = parse_expense_report(FIXTURE)
    assert len(rows) == 3
    assert rows[0].date.isoformat() == "2025-04-12"
    assert rows[0].amount == 53.94
    assert rows[0].vendor == "Uber Technologies"

def test_parse_expense_report_amounts():
    rows = parse_expense_report(FIXTURE)
    amounts = [r.amount for r in rows]
    assert 2025.60 in amounts  # comma-formatted dollar amount parsed correctly


def _make_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    return conn


def test_match_expense_report(tmp_path):
    conn = _make_db(tmp_path)
    txns = [
        ParsedTransaction(date=date(2025, 4, 12), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 11), amount=48.31, description="MIKADO NYC", merchant="Mikado", source_id="t2", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 11), amount=2025.60, description="MINT HOUSE", merchant="Mint House", source_id="t3", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 15), amount=100.00, description="GROCERY", merchant="Kroger", source_id="t4", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)
    rows = parse_expense_report(FIXTURE)

    matched, already, unmatched = match_expense_report(conn, rows)
    assert matched == 3
    assert already == 0
    assert unmatched == 0

    # Verify flag is set
    reimbursed = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE is_reimbursed = 1").fetchone()["c"]
    assert reimbursed == 3

    # Kroger should NOT be flagged
    kroger = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 't4'").fetchone()
    assert kroger["is_reimbursed"] == 0


def test_match_expense_report_idempotent(tmp_path):
    conn = _make_db(tmp_path)
    txns = [
        ParsedTransaction(date=date(2025, 4, 12), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)
    rows = parse_expense_report(FIXTURE)

    matched1, already1, unmatched1 = match_expense_report(conn, rows)
    assert matched1 == 1

    matched2, already2, unmatched2 = match_expense_report(conn, rows)
    assert matched2 == 0
    assert already2 == 1

    reimbursed = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE is_reimbursed = 1").fetchone()["c"]
    assert reimbursed == 1


def test_match_expense_report_unmatched(tmp_path):
    conn = _make_db(tmp_path)
    # No transactions in DB — all expense rows should be unmatched
    rows = parse_expense_report(FIXTURE)
    matched, already, unmatched = match_expense_report(conn, rows)
    assert matched == 0
    assert already == 0
    assert unmatched == 3


def test_match_fuzzy_date(tmp_path):
    """Expense report date may differ from card posting date by 1-2 days."""
    conn = _make_db(tmp_path)
    from cashflow.parsers.expense_report import ExpenseRow

    # Card posted 2 days after the expense report date
    txns = [
        ParsedTransaction(date=date(2025, 4, 14), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)

    rows = [ExpenseRow(date=date(2025, 4, 12), amount=53.94, vendor="Uber Technologies", expense_type="Taxi")]
    matched, already, unmatched = match_expense_report(conn, rows)
    assert matched == 1
    assert unmatched == 0

    reimbursed = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 't1'").fetchone()
    assert reimbursed["is_reimbursed"] == 1


def test_match_fuzzy_date_prefers_exact(tmp_path):
    """If both exact and fuzzy matches exist, prefer the exact date."""
    conn = _make_db(tmp_path)
    from cashflow.parsers.expense_report import ExpenseRow

    txns = [
        ParsedTransaction(date=date(2025, 4, 12), amount=53.94, description="UBER *TRIP EXACT", merchant="Uber", source_id="exact", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 13), amount=53.94, description="UBER *TRIP FUZZY", merchant="Uber", source_id="fuzzy", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)

    rows = [ExpenseRow(date=date(2025, 4, 12), amount=53.94, vendor="Uber Technologies", expense_type="Taxi")]
    matched, already, unmatched = match_expense_report(conn, rows)
    assert matched == 1

    exact = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 'exact'").fetchone()
    fuzzy = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 'fuzzy'").fetchone()
    assert exact["is_reimbursed"] == 1
    assert fuzzy["is_reimbursed"] == 0


def test_match_fuzzy_date_no_false_match(tmp_path):
    """Fuzzy date should not match beyond 2-day window."""
    conn = _make_db(tmp_path)
    from cashflow.parsers.expense_report import ExpenseRow

    txns = [
        ParsedTransaction(date=date(2025, 4, 16), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)

    rows = [ExpenseRow(date=date(2025, 4, 12), amount=53.94, vendor="Uber Technologies", expense_type="Taxi")]
    matched, already, unmatched = match_expense_report(conn, rows)
    assert matched == 0
    assert unmatched == 1
