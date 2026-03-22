import sqlite3
from datetime import date
from pathlib import Path

from cashflow.db import create_schema, store_transactions
from cashflow.dedup_paypal import link_paypal_to_cards
from cashflow.models import ParsedTransaction
from cashflow.parsers.paypal import parse_paypal_csv
from cashflow.seed import seed_all

FIXTURE = Path(__file__).parent / "fixtures" / "paypal_sample.csv"


def test_parse_paypal_csv_returns_debits_only():
    txns = parse_paypal_csv(FIXTURE)
    assert len(txns) == 2  # 2 debits, 2 credits in fixture


def test_parse_paypal_csv_amounts_positive():
    txns = parse_paypal_csv(FIXTURE)
    assert all(t.amount > 0 for t in txns)


def test_parse_paypal_csv_merchant_from_name():
    txns = parse_paypal_csv(FIXTURE)
    merchants = [t.merchant for t in txns]
    assert "Walsworth Publishing Company, Inc." in merchants
    assert "Ashby Orthodontics" in merchants


def test_parse_paypal_csv_dates():
    txns = parse_paypal_csv(FIXTURE)
    assert txns[0].date.isoformat() == "2025-01-08"
    assert txns[1].date.isoformat() == "2025-01-15"


def test_parse_paypal_csv_source_id_unique():
    txns = parse_paypal_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_paypal_csv_account_and_source_type():
    txns = parse_paypal_csv(FIXTURE)
    assert all(t.account_name == "PayPal" for t in txns)
    assert all(t.source_type == "csv" for t in txns)


def _make_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    return conn


def test_link_paypal_to_cards(tmp_path):
    conn = _make_db(tmp_path)

    # Card charge from Chase showing "PAYPAL *ASHBY ORTHO"
    chase_txn = ParsedTransaction(
        date=date(2025, 1, 16), amount=77.78, description="PAYPAL *ASHBY ORTHO",
        merchant="PAYPAL *ASHBY ORTHO", source_id="chase-1", source_type="csv",
        account_name="Chase Prime Visa",
    )
    # PayPal charge for Ashby Orthodontics
    paypal_txn = ParsedTransaction(
        date=date(2025, 1, 15), amount=77.78, description="Ashby Orthodontics",
        merchant="Ashby Orthodontics", source_id="paypal-1", source_type="csv",
        account_name="PayPal",
    )
    store_transactions(conn, [chase_txn, paypal_txn])

    linked = link_paypal_to_cards(conn)
    assert linked == 1

    # PayPal row should have canonical_id pointing to Chase row
    paypal_row = conn.execute(
        "SELECT canonical_id FROM transactions WHERE source_id = 'paypal-1'"
    ).fetchone()
    chase_row = conn.execute(
        "SELECT id FROM transactions WHERE source_id = 'chase-1'"
    ).fetchone()
    assert paypal_row["canonical_id"] == chase_row["id"]


def test_link_paypal_skips_balance_funded(tmp_path):
    """PayPal transactions funded by balance (no card charge) should not link."""
    conn = _make_db(tmp_path)

    paypal_txn = ParsedTransaction(
        date=date(2025, 1, 15), amount=25.00, description="Douglas Brown",
        merchant="Douglas Brown", source_id="paypal-1", source_type="csv",
        account_name="PayPal",
    )
    store_transactions(conn, [paypal_txn])

    linked = link_paypal_to_cards(conn)
    assert linked == 0

    row = conn.execute(
        "SELECT canonical_id FROM transactions WHERE source_id = 'paypal-1'"
    ).fetchone()
    assert row["canonical_id"] is None
