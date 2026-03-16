from datetime import date
from cashflow.models import ParsedTransaction
from cashflow.db import store_transactions
from cashflow.seed import seed_all

def _make_txn(**overrides) -> ParsedTransaction:
    defaults = dict(date=date(2026, 1, 15), amount=42.99, description="AMAZON MKTPL*TEST", merchant="Amazon Marketplace", source_id="chase-csv-abc123", source_type="csv", account_name="Chase Prime Visa", order_number="113-1234567-8901234")
    defaults.update(overrides)
    return ParsedTransaction(**defaults)

def test_store_transactions_inserts_rows(db):
    seed_all(db)
    txns = [_make_txn(), _make_txn(source_id="chase-csv-def456", amount=10.0)]
    stored = store_transactions(db, txns)
    assert stored == 2
    rows = db.execute("SELECT * FROM transactions").fetchall()
    assert len(rows) == 2

def test_store_transactions_resolves_account_id(db):
    seed_all(db)
    store_transactions(db, [_make_txn()])
    row = db.execute("SELECT account_id FROM transactions").fetchone()
    acct = db.execute("SELECT name FROM accounts WHERE id = ?", (row["account_id"],)).fetchone()
    assert acct["name"] == "Chase Prime Visa"

def test_store_transactions_skips_duplicates(db):
    seed_all(db)
    txns = [_make_txn()]
    store_transactions(db, txns)
    stored = store_transactions(db, txns)
    assert stored == 0
    rows = db.execute("SELECT * FROM transactions").fetchall()
    assert len(rows) == 1

def test_store_transactions_sets_pending_status(db):
    seed_all(db)
    store_transactions(db, [_make_txn()])
    row = db.execute("SELECT status FROM transactions").fetchone()
    assert row["status"] == "pending"
