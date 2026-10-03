"""Tests for the `find` command's filter options and --json output."""
import json
import sqlite3
from click.testing import CliRunner
from cashflow.cli import cli

VENTURE = "Capital One Venture"
SHARED_CO = "Capital One"
BOFA = "Bank of America"

TXNS = [
    # source_id, date, amount, merchant, who, account
    ("src-1", "2026-01-15", 30.0, "Town Center Barber Shop", "fred", VENTURE),
    ("src-2", "2026-02-18", 25.0, "TOWN CENTER BARBER SHO", "fred", VENTURE),
    ("src-3", "2026-02-19", 25.0, "Town Center Barber Shop", "shared", SHARED_CO),
    ("src-4", "2026-04-17", 30.0, "TOWN CENTER BARBER SHOP VIRGINIA", "shared", BOFA),
    ("src-5", "2026-04-20", -30.0, "TOWN CENTER BARBER SHOP REFUND", "shared", BOFA),
]


def _seeded_db(tmp_path, txns=TXNS):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    runner.invoke(cli, ["--db", str(db_path), "status"])  # triggers seed_all
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    for src, d, amt, merch, who, acct in txns:
        acct_id = conn.execute("SELECT id FROM accounts WHERE name = ?", (acct,)).fetchone()[0]
        conn.execute(
            "INSERT INTO transactions (source_id, date, amount, description, merchant, "
            "account_id, status, confidence, who, source_type) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, 'csv')",
            (src, d, amt, merch, merch, acct_id, who),
        )
    conn.commit()
    conn.close()
    return db_path


def _dates_in(output):
    """Extract the transaction dates shown in table output."""
    import re
    return set(re.findall(r"\d{4}-\d{2}-\d{2}", output))


def test_find_date_range(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "find", "barber", "--date-from", "2026-02-01", "--date-to", "2026-03-01"]
    )
    assert result.exit_code == 0
    dates = _dates_in(result.output)
    assert dates == {"2026-02-18", "2026-02-19"}


def test_find_min_amount(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--min-amount", "26"])
    assert result.exit_code == 0
    dates = _dates_in(result.output)
    assert "2026-01-15" in dates and "2026-04-17" in dates
    assert "2026-02-18" not in dates  # $25 below the floor
    assert "2026-04-20" not in dates  # refund is negative


def test_find_max_amount(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--max-amount", "25"])
    assert result.exit_code == 0
    dates = _dates_in(result.output)
    assert {"2026-02-18", "2026-02-19"} <= dates
    assert "2026-01-15" not in dates and "2026-04-17" not in dates


def test_find_who_filter(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--who", "fred"])
    assert result.exit_code == 0
    dates = _dates_in(result.output)
    assert dates == {"2026-01-15", "2026-02-18"}


def test_find_account_filter_is_substring_and_case_insensitive(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--account", "venture"])
    assert result.exit_code == 0
    dates = _dates_in(result.output)
    assert dates == {"2026-01-15", "2026-02-18"}


def test_find_json_output(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "find", "barber", "--who", "shared", "--json"]
    )
    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert len(rows) == 3
    assert {r["amount"] for r in rows} == {25.0, 30.0, -30.0}
    assert {r["account"] for r in rows} == {SHARED_CO, BOFA}
    for r in rows:
        assert set(r) == {"id", "date", "amount", "merchant", "description", "category", "account", "who"}


def test_find_json_empty_result(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "nonexistent", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == []


def test_find_invalid_date_format(tmp_path):
    db_path = _seeded_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--date-from", "02/2026"])
    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output


def test_find_filters_still_exclude_canonical_duplicates(tmp_path):
    # A row flagged as canonical dup (canonical_id set) must never appear.
    db_path = _seeded_db(tmp_path, txns=TXNS[:1])
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    acct_id = conn.execute("SELECT id FROM accounts WHERE name = ?", (VENTURE,)).fetchone()[0]
    conn.execute(
        "INSERT INTO transactions (source_id, canonical_id, date, amount, description, merchant, "
        "account_id, status, confidence, who, source_type) "
        "VALUES ('dup-src', 1, '2026-01-16', 30.0, 'dup', 'Town Center Barber Shop', ?, 'pending', 0, 'fred', 'csv')",
        (acct_id,),
    )
    conn.commit()
    conn.close()
    result = CliRunner().invoke(cli, ["--db", str(db_path), "find", "barber", "--json"])
    rows = json.loads(result.output)
    assert len(rows) == 1  # only the original, not the canonical-flagged copy
