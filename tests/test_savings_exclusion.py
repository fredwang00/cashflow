from datetime import date

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from cashflow.audit import category_spikes
from cashflow.cli import cli
from cashflow.db import get_connection
from cashflow.plans import monthly_free_cash
from cashflow.queries import get_month_spending, get_ytd_spending, get_ytd_surplus
from cashflow.seed import seed_all
from cashflow.server import create_app


@pytest.fixture
def conn(db):
    seed_all(db)
    return db


_counter = 0


def _txn(conn, day, amount, category=None, one_off=False):
    global _counter
    _counter += 1
    category_id = None
    if category:
        conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'want')", (category,))
        category_id = conn.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, category_id, "
        "is_one_off, status, source_type) VALUES (?, ?, ?, 'd', 'm', 1, ?, ?, 'confirmed', 'csv')",
        (f"s{_counter}", day, amount, category_id, int(one_off)),
    )
    conn.commit()


def test_month_spending_excludes_investments_and_savings(conn):
    _txn(conn, "2026-03-05", 200.0, "Groceries")
    _txn(conn, "2026-03-06", 1000.0, "Crypto/Investments")
    _txn(conn, "2026-03-07", 500.0, "Investments")
    _txn(conn, "2026-03-08", 250.0, "College Savings")
    assert get_month_spending(conn, 2026, 3) == pytest.approx(200.0)


def test_uncategorized_transactions_still_count_as_spending(conn):
    _txn(conn, "2026-03-05", 75.0)
    _txn(conn, "2026-03-06", 1000.0, "Crypto/Investments")
    assert get_month_spending(conn, 2026, 3) == pytest.approx(75.0)


def test_investments_count_toward_surplus(conn):
    conn.execute("INSERT INTO income (source_id, date, amount, source) VALUES ('i1', '2026-02-15', 5000, 'paycheck')")
    _txn(conn, "2026-02-10", 3000.0, "Groceries")
    _txn(conn, "2026-02-11", 1500.0, "Crypto/Investments", one_off=True)
    assert get_ytd_spending(conn, 2026) == pytest.approx(3000.0)
    assert get_ytd_surplus(conn, 2026) == pytest.approx(2000.0)


def test_free_cash_baseline_excludes_investments(conn):
    for month in ("06", "07", "08"):
        conn.execute("INSERT INTO income (source_id, date, amount, source) VALUES (?, ?, 6000, 'paycheck')",
                     (f"i{month}", f"2026-{month}-15"))
        _txn(conn, f"2026-{month}-10", 4000.0, "Groceries")
    _txn(conn, "2026-08-18", 3000.0, "Crypto/Investments")
    free = monthly_free_cash(conn, today=date(2026, 9, 26))
    assert free.baseline_burn == pytest.approx(4000.0)


def test_category_spikes_ignore_investment_categories(conn):
    for month in range(2, 8):
        _txn(conn, f"2026-{month:02d}-10", 100.0, "Crypto/Investments")
    _txn(conn, "2026-08-10", 5000.0, "Crypto/Investments")
    assert category_spikes(conn, date(2026, 9, 26)) == []


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "server.db"
    setup = get_connection(path)
    seed_all(setup)
    _txn(setup, "2026-03-05", 200.0, "Groceries")
    _txn(setup, "2026-03-06", 1000.0, "Crypto/Investments")
    setup.close()
    return TestClient(create_app(str(path)))


def test_dashboard_monthly_total_and_categories_exclude_investments(client):
    data = client.get("/api/monthly/2026/3").json()
    assert data["total"] == pytest.approx(200.0)
    assert [c["category"] for c in data["by_category"]] == ["Groceries"]
    assert len(data["transactions"]) == 2


def test_dashboard_yearly_spending_excludes_investments(client):
    march = client.get("/api/yearly/2026").json()["months"][2]
    assert march["spending"] == pytest.approx(200.0)
    assert march["spending_baseline"] == pytest.approx(200.0)


@pytest.fixture
def run(tmp_path):
    db_path = str(tmp_path / "cli.db")
    runner = CliRunner()
    return lambda *args: runner.invoke(cli, ["--db", db_path, *args])


def test_rule_delete_removes_rule(run):
    assert run("rule", "set", "Zelle", "Landscaping").exit_code == 0
    result = run("rule", "delete", "Zelle")
    assert result.exit_code == 0, result.output
    assert "Deleted rule" in result.output
    assert "Zelle" not in run("rule", "list").output


def test_rule_delete_unknown_pattern_errors(run):
    result = run("rule", "delete", "No Such Rule")
    assert result.exit_code != 0
    assert "No rule" in result.output
