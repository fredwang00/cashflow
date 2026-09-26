from cashflow.seed import seed_all
from cashflow.queries import get_month_spending, get_ytd_surplus, get_review_queue_count, get_goal, get_fsa_candidates

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


def test_get_month_spending_subtracts_reimbursed_amount(db):
    seed_all(db)
    _insert_txn(db, 1627.80, "2026-03-12")
    _insert_txn(db, 500.0, "2026-03-15")
    db.execute(
        "UPDATE transactions SET reimbursed_amount = 1127.80 WHERE amount = 1627.80"
    )
    db.commit()
    total = get_month_spending(db, 2026, 3)
    assert abs(total - 1000.0) < 0.01


def test_get_ytd_surplus_accounts_for_reimbursement(db):
    seed_all(db)
    _insert_income(db, 15000.0, "2026-01-15")
    _insert_txn(db, 10000.0, "2026-01-15")
    _insert_txn(db, 1600.0, "2026-01-20")
    db.execute(
        "UPDATE transactions SET reimbursed_amount = 1100.0 WHERE amount = 1600.0"
    )
    db.commit()
    surplus = get_ytd_surplus(db, 2026)
    assert abs(surplus - 4500.0) < 0.01


def _ensure_category(db, name, cat_type="necessity"):
    existing = db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if existing:
        return existing["id"]
    db.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, cat_type))
    db.commit()
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]


def _insert_categorized_txn(db, amount, txn_date, category_name, merchant="test"):
    cat_id = _ensure_category(db, category_name)
    db.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, "
        "category_id, status, confidence, who, source_type) "
        "VALUES (?, ?, ?, 'test', ?, 1, ?, 'confirmed', 100, 'shared', 'csv')",
        (f"fsa-{txn_date}-{amount}-{merchant}", txn_date, amount, merchant, cat_id),
    )
    db.commit()


def test_fsa_candidates_finds_medical_category(db):
    seed_all(db)
    _insert_categorized_txn(db, 30.0, "2026-02-23", "Medical", "CHILDRENS HOSPITAL")
    _insert_categorized_txn(db, 72.80, "2026-06-01", "Dental", "PEDIATRIC DENTISTRY")
    _insert_categorized_txn(db, 50.0, "2026-03-01", "Groceries", "COSTCO")
    rows = get_fsa_candidates(db, 2026)
    assert len(rows) == 2
    assert sum(r["amount"] for r in rows) == 102.80


def test_fsa_candidates_finds_eligible_merchants(db):
    seed_all(db)
    _insert_categorized_txn(db, 239.0, "2026-09-01", "Subscriptions", "Whoop")
    _insert_categorized_txn(db, 102.4, "2026-09-04", "Shopping", "Leluv")
    rows = get_fsa_candidates(db, 2026)
    assert len(rows) == 2


def test_fsa_candidates_excludes_other_years(db):
    seed_all(db)
    _insert_categorized_txn(db, 30.0, "2025-12-15", "Medical", "DOCTOR")
    _insert_categorized_txn(db, 30.0, "2026-01-15", "Medical", "DOCTOR2")
    rows = get_fsa_candidates(db, 2026)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-01-15"


def test_fsa_candidates_excludes_linked_duplicates(db):
    seed_all(db)
    _insert_categorized_txn(db, 30.0, "2026-03-01", "Medical", "DOCTOR")
    db.execute(
        "INSERT INTO transactions (source_id, canonical_id, date, amount, description, merchant, "
        "account_id, category_id, status, confidence, who, source_type) "
        "VALUES ('dup-fsa', 1, '2026-03-01', 30.0, 'test', 'DOCTOR', 1, "
        "(SELECT id FROM categories WHERE name = 'Medical'), 'confirmed', 100, 'shared', 'csv')"
    )
    db.commit()
    rows = get_fsa_candidates(db, 2026)
    assert len(rows) == 1


def test_fsa_candidates_shows_reimbursement_status(db):
    seed_all(db)
    _insert_categorized_txn(db, 30.0, "2026-03-01", "Medical", "DOCTOR")
    db.execute("UPDATE transactions SET is_reimbursed = 1, reimbursed_amount = 30.0 WHERE amount = 30.0")
    db.commit()
    rows = get_fsa_candidates(db, 2026)
    assert len(rows) == 1
    assert rows[0]["is_reimbursed"] == 1
    assert rows[0]["reimbursed_amount"] == 30.0
