from cashflow.seed import seed_all
from cashflow.queries import get_month_spending, get_ytd_surplus, get_review_queue_count, get_goal

def _insert_txn(db, amount, txn_date, status="confirmed"):
    db.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES (?, ?, ?, 'test', 'test', 1, ?, 100, 'shared', 'csv')",
        (f"test-{txn_date}-{amount}", txn_date, amount, status),
    )
    db.commit()

def _insert_income(db, amount, inc_date):
    db.execute(
        "INSERT INTO income (source_id, date, amount, source) VALUES (?, ?, ?, 'fei_paycheck')",
        (f"income-{inc_date}-{amount}", inc_date, amount),
    )
    db.commit()

def test_get_month_spending(db):
    seed_all(db)
    _insert_txn(db, 1000.0, "2026-03-01")
    _insert_txn(db, 500.0, "2026-03-15")
    _insert_txn(db, 200.0, "2026-02-28")
    total = get_month_spending(db, 2026, 3)
    assert total == 1500.0

def test_get_month_spending_excludes_linked_duplicates(db):
    seed_all(db)
    _insert_txn(db, 100.0, "2026-03-01")
    db.execute(
        "INSERT INTO transactions (source_id, canonical_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES ('dup-1', 1, '2026-03-01', 100.0, 'test', 'test', 1, 'confirmed', 100, 'shared', 'email')"
    )
    db.commit()
    total = get_month_spending(db, 2026, 3)
    assert total == 100.0

def test_get_ytd_surplus(db):
    seed_all(db)
    _insert_income(db, 15000.0, "2026-01-15")
    _insert_income(db, 15000.0, "2026-02-15")
    _insert_txn(db, 10000.0, "2026-01-15")
    _insert_txn(db, 11000.0, "2026-02-15")
    surplus = get_ytd_surplus(db, 2026)
    assert surplus == 9000.0

def test_get_review_queue_count(db):
    seed_all(db)
    _insert_txn(db, 50.0, "2026-03-01", status="pending")
    _insert_txn(db, 75.0, "2026-03-02", status="pending")
    _insert_txn(db, 100.0, "2026-03-03", status="confirmed")
    count = get_review_queue_count(db)
    assert count == 2

def test_get_goal(db):
    seed_all(db)
    ceiling = get_goal(db, "ceiling")
    assert ceiling is not None
    assert ceiling["amount"] == 12000.0
