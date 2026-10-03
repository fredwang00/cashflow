"""Tests for the possible_dupes view and the `dupes` command."""
import json
import sqlite3
from click.testing import CliRunner
from cashflow.cli import cli


def _acct(conn, name):
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO accounts (name, type, institution) VALUES (?, 'credit', 'Test')", (name,)
    ).lastrowid


def _txn(conn, source_id, d, amount, merchant, account_id, who="fred", canonical_id=None):
    conn.execute(
        "INSERT INTO transactions (source_id, canonical_id, date, amount, description, merchant, "
        "account_id, status, confidence, who, source_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, 'csv')",
        (source_id, canonical_id, d, amount, merchant, merchant, account_id, who),
    )


def _insert_cross_source_pair(conn):
    """The real-world pattern: one haircut, two Cap One pipelines, two cards, one day apart."""
    card_a = _acct(conn, "Capital One Venture")
    card_b = _acct(conn, "Capital One")
    _txn(conn, "capone-abc123", "2026-02-18", 25.0, "TOWN CENTER BARBER SHO", card_a, who="fred")
    _txn(conn, "capone-csv-xyz789", "2026-02-19", 25.0, "Town Center Barber Shop", card_b, who="shared")


def test_view_flags_cross_source_pair(db):
    _insert_cross_source_pair(db)
    rows = db.execute("SELECT * FROM possible_dupes").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["amount"] == 25.0
    assert r["days_apart"] == 1
    assert r["merchant_a"] == "TOWN CENTER BARBER SHO"
    assert r["merchant_b"] == "Town Center Barber Shop"
    assert r["account_a"] == "Capital One Venture"
    assert r["source_a"] == "capone-abc123"
    assert r["source_b"] == "capone-csv-xyz789"


def test_view_requires_same_amount(db):
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-02-18", 25.0, "SHOP ONE", card)
    _txn(db, "s2", "2026-02-18", 27.0, "SHOP ONE", card)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_requires_dates_within_three_days(db):
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-02-18", 25.0, "SHOP ONE", card)
    _txn(db, "s2", "2026-03-30", 25.0, "SHOP ONE", card)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_ignores_refund_reversal_pairs(db):
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-08-03", 215.10, "CODENINJAS", card)
    _txn(db, "s2", "2026-08-06", -215.10, "CODENINJAS", card)  # refund, not a dupe
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_ignores_already_canonical_flagged(db):
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-02-18", 25.0, "SHOP ONE", card)
    dup_id = db.execute("SELECT id FROM transactions WHERE source_id = 's1'").fetchone()[0]
    _txn(db, "s2", "2026-02-19", 25.0, "SHOP ONE", card, canonical_id=dup_id)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_ignores_occurrence_suffix_siblings(db):
    # `-occurrence-N` rows are intentional same-day purchases (Chase/Robinhood), never dupes.
    card = _acct(db, "Card A")
    _txn(db, "chase-csv-abc123", "2026-08-15", 95.59, "VERIZON", card)
    _txn(db, "chase-csv-abc123-occurrence-2", "2026-08-15", 95.59, "VERIZON", card)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_requires_fuzzy_merchant_match(db):
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-02-18", 25.0, "TOWN CENTER BARBER", card)
    _txn(db, "s2", "2026-02-18", 25.0, "DAPPERS ST BARBERSHOP", card)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0


def test_view_flags_genuine_same_day_double_swipe(db):
    # Advisory by design: a real double swipe (or two identical purchases) also appears.
    card = _acct(db, "Card A")
    _txn(db, "s1", "2026-10-01", 215.10, "CODENINJASVIRGINIABEA", card)
    _txn(db, "s2", "2026-10-01", 215.10, "CODENINJAS VIRGINIA BEA", card)
    assert db.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 1


def _seeded_cli_db(tmp_path):
    db_path = tmp_path / "test.db"
    CliRunner().invoke(cli, ["--db", str(db_path), "status"])  # triggers seed_all
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    _insert_cross_source_pair(conn)
    conn.commit()
    conn.close()
    return db_path


def test_dupes_command_table(tmp_path):
    db_path = _seeded_cli_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dupes"])
    assert result.exit_code == 0
    assert "possible duplicate pair" in result.output
    assert "cross-account" in result.output
    assert "TOWN CENTER BARBER SHO" in result.output
    assert "Town Center Barber Shop" in result.output
    assert "Capital One Venture / Capital One" in result.output


def test_dupes_command_defaults_to_cross_account(tmp_path):
    # Same-account identical pair (a genuine repeat) is hidden by default, shown with --all.
    db_path = tmp_path / "test.db"
    CliRunner().invoke(cli, ["--db", str(db_path), "status"])
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    card = conn.execute("SELECT id FROM accounts WHERE name = 'Bank of America'").fetchone()[0]
    for src, d in (("bofa-1", "2026-10-01"), ("bofa-2", "2026-10-01")):
        conn.execute(
            "INSERT INTO transactions (source_id, date, amount, description, merchant, "
            "account_id, status, confidence, who, source_type) "
            "VALUES (?, ?, 215.10, 'cn', 'CODENINJAS VIRGINIA BEA', ?, 'pending', 0, 'shared', 'csv')",
            (src, d, card),
        )
    conn.commit()
    conn.close()
    default = CliRunner().invoke(cli, ["--db", str(db_path), "dupes"])
    assert default.exit_code == 0
    assert "CODENINJAS" not in default.output
    everything = CliRunner().invoke(cli, ["--db", str(db_path), "dupes", "--all"])
    assert everything.exit_code == 0
    assert "CODENINJAS" in everything.output


def test_dupes_command_json(tmp_path):
    db_path = _seeded_cli_db(tmp_path)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dupes", "--json"])
    assert result.exit_code == 0
    pairs = json.loads(result.output)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["amount"] == 25.0
    assert p["days_apart"] == 1
    assert p["account_a"] == "Capital One Venture"


def test_dupes_command_empty(tmp_path):
    db_path = tmp_path / "test.db"
    CliRunner().invoke(cli, ["--db", str(db_path), "status"])
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dupes"])
    assert result.exit_code == 0
    assert "No possible duplicate pairs found." in result.output
