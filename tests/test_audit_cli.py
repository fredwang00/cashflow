from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from cashflow.cli import cli
from cashflow.db import get_connection
from cashflow.seed import seed_all


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "test.db"
    conn = get_connection(path)
    seed_all(conn)
    conn.close()
    return path


@pytest.fixture
def run(db_path):
    runner = CliRunner()
    return lambda *args: runner.invoke(cli, ["--db", str(db_path), *args])


def _charges(db_path, description, amount, months, last_days_ago=10, category="Shopping"):
    conn = get_connection(db_path)
    cat_id = conn.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()["id"]
    last = date.today() - timedelta(days=last_days_ago)
    for i in range(months):
        day = last - timedelta(days=30 * i)
        conn.execute(
            "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, category_id, "
            "status, source_type) VALUES (?, ?, ?, ?, 'm', 1, ?, 'confirmed', 'csv')",
            (f"{description}-{day}", day.isoformat(), amount, description, cat_id),
        )
    conn.commit()
    conn.close()


def test_audit_lists_unreviewed_recurring_with_costs(run, db_path):
    _charges(db_path, "UBER *ONE MEMBERSHIP UBERAmsterdam", 4.40, 6)
    _charges(db_path, "CRUNCHYROLL CA", 7.99, 6)
    result = run("audit")
    assert result.exit_code == 0, result.output
    assert "uber one membership" in result.output
    assert "crunchyroll ca" in result.output
    assert "$95.88" in result.output  # 7.99 * 12
    assert "To review (2" in result.output


def test_audit_keep_by_substring_moves_it_out_of_review(run, db_path):
    _charges(db_path, "CRUNCHYROLL CA", 7.99, 6)
    result = run("audit", "keep", "crunchy")
    assert result.exit_code == 0, result.output
    assert "crunchyroll ca" in result.output
    result = run("audit")
    assert "To review" not in result.output
    assert "Kept: 1" in result.output


def test_audit_ambiguous_match_lists_candidates(run, db_path):
    _charges(db_path, "GOOGLE *YOUTUBEPREMIUM CA", 22.99, 6)
    _charges(db_path, "GOOGLE *YOUTUBE MEMBER", 1.99, 6)
    result = run("audit", "cancel", "google")
    assert result.exit_code != 0
    assert "google youtubepremium ca" in result.output
    assert "google youtube member" in result.output


def test_audit_unknown_match_errors(run, db_path):
    result = run("audit", "ignore", "netflix")
    assert result.exit_code != 0
    assert "No recurring charge matches" in result.output


def test_audit_alarms_when_cancelled_charge_returns(run, db_path):
    _charges(db_path, "SQSP* WORKSP#1 SQUARESPACE.CNY", 8.40, 6, last_days_ago=40)
    assert run("audit", "cancel", "squarespace").exit_code == 0
    conn = get_connection(db_path)
    conn.execute("UPDATE recurring_reviews SET decided_on = ?", ((date.today() - timedelta(days=35)).isoformat(),))
    conn.commit()
    conn.close()
    _charges(db_path, "SQSP* WORKSP#2 SQUARESPACE.CNY", 8.40, 1, last_days_ago=5)
    result = run("audit")
    assert "after you cancelled" in result.output


def test_new_charge_raises_only_the_new_alarm():
    from cashflow.audit import Recurring
    from cashflow.audit_cli import _alarms
    uber = Recurring(
        key="uber one membership", label="UBER *ONE MEMBERSHIP", category="Auto", cadence="monthly",
        count=3, first_seen=date(2026, 7, 16), last_seen=date(2026, 9, 16), amount=4.40,
        latest_amount=4.55, price_increase=0.81, active=True, is_new=True,
        decision=None, decided_on=None, charged_after_cancel=None,
    )
    [(message, _)] = _alarms([uber])
    assert "new recurring charge" in message


def test_audit_ignore_hides_false_positive(run, db_path):
    _charges(db_path, "CRUNCHYROLL CA", 7.99, 6)
    run("audit", "ignore", "crunchyroll")
    result = run("audit")
    assert "crunchyroll" not in result.output
