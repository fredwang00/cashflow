from datetime import date
from cashflow.seed import seed_all
from cashflow.db import store_income
from cashflow.queries import get_ytd_income

def test_store_income_inserts_rows(db):
    seed_all(db)
    records = [{"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "bofa-chk-abc123"}]
    stored = store_income(db, records)
    assert stored == 1
    row = db.execute("SELECT * FROM income").fetchone()
    assert row["amount"] == 7584.14
    assert row["source"] == "fei_paycheck"

def test_store_income_skips_duplicates(db):
    seed_all(db)
    records = [{"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "bofa-chk-abc123"}]
    store_income(db, records)
    stored = store_income(db, records)
    assert stored == 0

def test_income_shows_in_ytd(db):
    seed_all(db)
    records = [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "bofa-chk-1"},
        {"date": date(2026, 1, 30), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "bofa-chk-2"},
    ]
    store_income(db, records)
    assert get_ytd_income(db, 2026) == 15168.28
