import sqlite3
from datetime import date
from fastapi.testclient import TestClient
from cashflow.server import create_app
from cashflow.db import create_schema, store_transactions, store_income
from cashflow.seed import seed_all
from cashflow.models import ParsedTransaction


def _make_app(db_path):
    return create_app(str(db_path))


def _seed_and_populate(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    txns = [
        ParsedTransaction(date=date(2026, 3, 1), amount=1500.0, description="KROGER", merchant="Kroger", source_id="test-1", source_type="csv", account_name="Bank of America"),
        ParsedTransaction(date=date(2026, 3, 5), amount=3450.37, description="NEWREZ MORTGAGE", merchant="Newrez Mortgage", source_id="test-2", source_type="csv", account_name="Checking"),
        ParsedTransaction(date=date(2026, 3, 10), amount=200.0, description="TARGET", merchant="Target", source_id="test-3", source_type="csv", account_name="Target Card"),
        ParsedTransaction(date=date(2026, 2, 15), amount=800.0, description="KROGER", merchant="Kroger", source_id="test-4", source_type="csv", account_name="Bank of America"),
    ]
    store_transactions(conn, txns)
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Groceries') WHERE source_id = 'test-1'")
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Mortgage') WHERE source_id = 'test-2'")
    conn.commit()
    store_income(conn, [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-1"},
        {"date": date(2026, 2, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-2"},
        {"date": date(2026, 3, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-3"},
    ])
    conn.close()


def test_status_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "month_spending" in data
    assert "ceiling" in data
    assert "ytd_surplus" in data
    assert "review_queue" in data


def test_monthly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert "by_category" in data
    assert "total" in data


def test_transactions_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/transactions?year=2026&month=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_yearly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    assert resp.status_code == 200
    data = resp.json()
    assert "months" in data
    assert "ytd_income" in data
    assert "ytd_spending" in data
    assert "ytd_surplus" in data


def test_yearly_baseline_excludes_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    # Flag one transaction as reimbursed
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    data = resp.json()
    march = data["months"][2]  # March = index 2
    # Baseline should exclude the $1500 reimbursed Kroger transaction
    assert march["spending_baseline"] < march["spending"]


def test_toggle_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)

    resp = client.post("/api/transactions/1/toggle-reimbursed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_reimbursed"] is True

    # Toggle off
    resp = client.post("/api/transactions/1/toggle-reimbursed")
    data = resp.json()
    assert data["is_reimbursed"] is False


def test_monthly_includes_is_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    data = resp.json()
    reimbursed_txns = [t for t in data["transactions"] if t.get("is_reimbursed")]
    assert len(reimbursed_txns) == 1


def test_index_serves_html(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
