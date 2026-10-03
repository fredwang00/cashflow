"""Regression tests for dedupe-link / dedupe-unlink (canonical linking).

The real-world regression these guard against: the Capital One
double-ingestion of May-July 2025, where the same charge arrived through
both the statement-PDF pipeline (post date) and the CSV export
(transaction date), on different accounts, 1-2 days apart.
"""
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


def _txn(conn, source_id, d, amount, merchant, account_id, who="fred"):
    return conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, "
        "account_id, status, confidence, who, source_type) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, 'csv')",
        (source_id, d, amount, merchant, merchant, account_id, who),
    ).lastrowid


def _capone_pair(conn, csv_date, statement_date, amount, merchant):
    """The real pattern: CSV export (transaction date) vs statement PDF (post date)."""
    csv_id = _txn(conn, f"capone-csv-{merchant}-{csv_date}", csv_date, amount, merchant,
                  _acct(conn, "Capital One Venture"))
    stmt_id = _txn(conn, f"capone-{merchant}-{statement_date}", statement_date, amount, merchant,
                   _acct(conn, "Capital One Wendy"), who="shared")
    return csv_id, stmt_id


def _seeded_cli_db(tmp_path, populate=None):
    db_path = tmp_path / "test.db"
    CliRunner().invoke(cli, ["--db", str(db_path), "status"])  # triggers seed_all
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    rows = populate(conn) if populate else []
    conn.commit()
    conn.close()
    return db_path, rows


def _canonical_total(db_path, month):
    conn = sqlite3.connect(str(db_path))
    total = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions "
        "WHERE canonical_id IS NULL AND amount > 0 AND strftime('%Y-%m', date) = ?",
        (month,),
    ).fetchone()[0]
    conn.close()
    return total


# ---------- single-pair mode ----------

def test_single_pair_links_dupe_to_keeper(tmp_path):
    def populate(conn):
        csv_id, stmt_id = _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")
        return csv_id, stmt_id

    db_path, (csv_id, stmt_id) = _seeded_cli_db(tmp_path, populate)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(csv_id), str(stmt_id)])
    assert result.exit_code == 0
    assert "excluded from totals" in result.output

    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (stmt_id,)).fetchone()
    keeper = conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (csv_id,)).fetchone()
    conn.close()
    assert row[0] == csv_id     # statement copy now points at the CSV copy
    assert keeper[0] is None   # keeper stays canonical


def test_single_pair_spending_drops_by_one_copy(tmp_path):
    def populate(conn):
        return _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")

    db_path, (csv_id, stmt_id) = _seeded_cli_db(tmp_path, populate)
    before = _canonical_total(db_path, "2025-07")
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(csv_id), str(stmt_id)])
    assert result.exit_code == 0
    after = _canonical_total(db_path, "2025-07")
    assert round(before - after, 2) == 168.38


def test_single_pair_self_link_rejected(tmp_path):
    def populate(conn):
        return _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")

    db_path, (csv_id, _) = _seeded_cli_db(tmp_path, populate)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(csv_id), str(csv_id)])
    assert result.exit_code != 0
    assert "cannot be linked to itself" in result.output


def test_single_pair_keeper_must_be_canonical(tmp_path):
    def populate(conn):
        a, b = _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")
        c = _txn(conn, "third-copy", "2025-07-06", 168.38, "GOl Et Kasap", _acct(conn, "Bank of America"))
        return a, b, c

    db_path, (a, b, c) = _seeded_cli_db(tmp_path, populate)
    # Link b -> a first, then try to keep b (now a dupe) as keeper for c.
    assert CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(a), str(b)]).exit_code == 0
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(b), str(c)])
    assert result.exit_code != 0
    assert "itself a linked duplicate" in result.output


def test_single_pair_missing_transaction(tmp_path):
    db_path, _ = _seeded_cli_db(tmp_path, populate=lambda conn: None)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "1", "999"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_single_pair_requires_both_ids(tmp_path):
    db_path, _ = _seeded_cli_db(tmp_path, populate=lambda conn: None)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "1"])
    assert result.exit_code != 0
    assert "--from-dupes" in result.output


def test_single_pair_relink_reports_previous(tmp_path):
    def populate(conn):
        a, b = _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")
        c = _txn(conn, "third-copy", "2025-07-06", 168.38, "GOl Et Kasap", _acct(conn, "Bank of America"))
        return a, b, c

    db_path, (a, b, c) = _seeded_cli_db(tmp_path, populate)
    assert CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(a), str(b)]).exit_code == 0
    # Re-point b at c instead; must report the re-link, not fail.
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", str(c), str(b)])
    assert result.exit_code == 0
    assert f"was linked to #{a}" in result.output
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (b,)).fetchone()[0] == c
    conn.close()


# ---------- bulk mode ----------

def test_bulk_links_cross_account_pairs_keeping_earlier(tmp_path):
    """The core Cap One regression: statement copies fold into CSV copies."""

    def populate(conn):
        pairs = [
            _capone_pair(conn, "2025-05-10", "2025-05-12", 7500.00, "A1 BETTER HEATING"),
            _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap"),
            _capone_pair(conn, "2025-07-08", "2025-07-09", 225.62, "ALPARSLAN DEGERLI MA"),
        ]
        return pairs

    db_path, pairs = _seeded_cli_db(tmp_path, populate)
    before = _canonical_total(db_path, "2025-07")
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"]
    )
    assert result.exit_code == 0
    assert "Linked 3 duplicate charges" in result.output
    assert "drop by $7,894.00" in result.output  # 7500 + 168.38 + 225.62

    conn = sqlite3.connect(str(db_path))
    for csv_id, stmt_id in pairs:
        assert conn.execute(
            "SELECT canonical_id FROM transactions WHERE id = ?", (stmt_id,)
        ).fetchone()[0] == csv_id
    conn.close()
    # July total drops by the two July dupes only.
    assert round(before - _canonical_total(db_path, "2025-07"), 2) == round(168.38 + 225.62, 2)


def test_bulk_survivor_is_earlier_date_even_with_higher_id(tmp_path):
    def populate(conn):
        # Insert the statement copy FIRST (lower id) but dated LATER:
        # the CSV copy has the higher id and the earlier (transaction) date.
        stmt = _txn(conn, "capone-early-id-late-date", "2025-07-07", 25.0,
                    "TOWN CENTER BARBER SHO", _acct(conn, "Capital One Wendy"), who="shared")
        csv = _txn(conn, "capone-csv-late-id-early-date", "2025-07-06", 25.0,
                   "Town Center Barber Shop", _acct(conn, "Capital One Venture"))
        return stmt, csv

    db_path, (stmt_id, csv_id) = _seeded_cli_db(tmp_path, populate)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert result.exit_code == 0
    conn = sqlite3.connect(str(db_path))
    # The earlier-dated row survives even though it has the higher id.
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (stmt_id,)).fetchone()[0] == csv_id
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (csv_id,)).fetchone()[0] is None
    conn.close()


def test_bulk_filters_and_confirmation_declined(tmp_path):
    def populate(conn):
        pairs = [
            _capone_pair(conn, "2025-05-10", "2025-05-12", 7500.00, "A1 BETTER HEATING"),
            _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap"),
        ]
        return pairs

    db_path, pairs = _seeded_cli_db(tmp_path, populate)

    # Declined confirmation writes nothing.
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes"], input="n\n"
    )
    assert result.exit_code == 0
    assert "No changes made" in result.output
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE canonical_id IS NOT NULL").fetchone()[0] == 0
    conn.close()

    # Merchant + date filters narrow to one pair.
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes",
              "--merchant", "heating", "--date-from", "2025-05-01", "--date-to", "2025-05-31", "--yes"]
    )
    assert result.exit_code == 0
    assert "1 pairs to link" in result.output
    conn = sqlite3.connect(str(db_path))
    linked = conn.execute("SELECT COUNT(*) FROM transactions WHERE canonical_id IS NOT NULL").fetchone()[0]
    conn.close()
    assert linked == 1


def test_bulk_skips_already_linked_pairs(tmp_path):
    def populate(conn):
        csv_id, stmt_id = _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")
        other_csv, other_stmt = _capone_pair(conn, "2025-07-08", "2025-07-09", 10.0, "PEYK CAFE")
        return (csv_id, stmt_id), (other_csv, other_stmt)

    db_path, ((csv_id, stmt_id), (other_csv, other_stmt)) = _seeded_cli_db(tmp_path, populate)
    # Link one pair manually first.
    assert CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", str(csv_id), str(stmt_id)]
    ).exit_code == 0
    # Bulk run: the view already hides linked pairs, so only PEYK CAFE remains;
    # the pre-linked pair must not be touched.
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert result.exit_code == 0
    assert "1 pairs to link" in result.output
    conn = sqlite3.connect(str(db_path))
    # pre-linked pair untouched: still csv_id, not re-linked
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (stmt_id,)).fetchone()[0] == csv_id
    # the other pair got linked
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (other_stmt,)).fetchone()[0] == other_csv
    conn.close()


def test_bulk_triple_copies_need_second_pass_and_never_chain(tmp_path):
    """Conservative by design: one pass links one pair of a triple and leaves
    the third copy canonical (no chains, no over-collapse); a second pass
    finishes the job."""

    def populate(conn):
        a = _txn(conn, "copy-1", "2025-07-06", 32.0, "Transatel Ubigi", _acct(conn, "Amex Gold"))
        b = _txn(conn, "copy-2", "2025-07-07", 32.0, "Transatel Ubigi", _acct(conn, "Robinhood Gold"))
        c = _txn(conn, "copy-3", "2025-07-08", 32.0, "Transatel Ubigi", _acct(conn, "Apple Card"))
        return a, b, c

    db_path, (a, b, c) = _seeded_cli_db(tmp_path, populate)
    first = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert first.exit_code == 0
    assert "skipped" in first.output

    conn = sqlite3.connect(str(db_path))
    survivors = {r[0] for r in conn.execute(
        "SELECT id FROM transactions WHERE canonical_id IS NULL AND id IN (?, ?, ?)", (a, b, c)
    ).fetchall()}
    conn.close()
    assert survivors == {a, c}  # b linked to a; c deliberately left for review

    # The remaining pair stays visible for a deliberate second pass.
    dupes = CliRunner().invoke(cli, ["--db", str(db_path), "dupes"])
    assert dupes.exit_code == 0 and "1 possible duplicate" in dupes.output

    second = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert second.exit_code == 0
    conn = sqlite3.connect(str(db_path))
    survivors = conn.execute(
        "SELECT id FROM transactions WHERE canonical_id IS NULL AND id IN (?, ?, ?)", (a, b, c)
    ).fetchall()
    links = dict(conn.execute(
        "SELECT id, canonical_id FROM transactions WHERE id IN (?, ?, ?)", (a, b, c)
    ).fetchall())
    conn.close()
    assert len(survivors) == 1 and survivors[0][0] == a
    # Flat links only: every dupe points at the one canonical survivor.
    assert links[b] == a and links[c] == a and links[a] is None


def test_bulk_ambiguous_quad_never_chains(tmp_path):
    """Regression: the real St. Nicholas quad (2025-06-02). Four $7 copies —
    two BofA and one Wendy all dated 06-02, one Venture dated 05-31 — used to
    produce a chain (#2918 -> #1467 -> #3257) because a batch keeper was later
    linked as a dupe. Now: flat links, two survivors, no chain."""

    def populate(conn):
        bofa1 = _txn(conn, "bofa-1", "2025-06-02", 7.0, "SQ *ST. NICHOLAS CATHOLICVA BC", _acct(conn, "Bank of America"))
        bofa2 = _txn(conn, "bofa-2", "2025-06-02", 7.0, "SQ *ST. NICHOLAS CATHOLICVA BC", _acct(conn, "Bank of America"))
        wendy = _txn(conn, "capone-wendy", "2025-06-02", 7.0, "SQ *ST. NICHOLAS CATHO", _acct(conn, "Capital One Wendy"), who="shared")
        # Venture copy carries the earlier transaction date, like the real data.
        venture = _txn(conn, "capone-csv-venture", "2025-05-31", 7.0, "SQ *ST. NICHOLAS CATHOLICVA BC", _acct(conn, "Capital One Venture"))
        return bofa1, bofa2, wendy, venture

    db_path, (bofa1, bofa2, wendy, venture) = _seeded_cli_db(tmp_path, populate)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert result.exit_code == 0

    conn = sqlite3.connect(str(db_path))
    rows = dict(conn.execute(
        "SELECT id, canonical_id FROM transactions WHERE id IN (?, ?, ?, ?)",
        (bofa1, bofa2, wendy, venture),
    ).fetchall())
    conn.close()

    # No chains: every linked dupe points at a row that is itself canonical.
    for txn_id, canonical in rows.items():
        if canonical is not None:
            assert rows[canonical] is None, f"chain: #{txn_id} -> #{canonical} -> #{rows[canonical]}"

    # Exactly two survivors survive for a genuinely ambiguous quad — the batch
    # deliberately does not collapse four same-amount copies to one.
    survivors = [i for i, c in rows.items() if c is None]
    assert len(survivors) == 2
    # And both keep counting in totals: $14 across the four copies.
    total = sum(
        7.0 for i, c in rows.items() if c is None
    )
    assert total == 14.0


def test_bulk_same_account_needs_all_flag(tmp_path):
    def populate(conn):
        card = _acct(conn, "Bank of America")
        x = _txn(conn, "s1", "2026-10-01", 215.10, "CODENINJASVIRGINIABEA", card)
        y = _txn(conn, "s2", "2026-10-01", 215.10, "CODENINJAS VIRGINIA BEA", card)
        return x, y

    db_path, (x, y) = _seeded_cli_db(tmp_path, populate)
    default = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"])
    assert default.exit_code == 0
    assert "No matching pairs" in default.output

    everything = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--all", "--yes"]
    )
    assert everything.exit_code == 0
    assert "1 pairs to link" in everything.output


def test_bulk_rejects_ids_and_bad_dates(tmp_path):
    db_path, _ = _seeded_cli_db(tmp_path, populate=lambda conn: None)
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "1", "2", "--from-dupes"]
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    result = CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--date-from", "07/2025"]
    )
    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output


# ---------- unlink ----------

def test_unlink_restores_charge(tmp_path):
    def populate(conn):
        return _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")

    db_path, (csv_id, stmt_id) = _seeded_cli_db(tmp_path, populate)
    assert CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", str(csv_id), str(stmt_id)]
    ).exit_code == 0
    during = _canonical_total(db_path, "2025-07")
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-unlink", str(stmt_id)])
    assert result.exit_code == 0
    assert "count in totals again" in result.output
    assert round(_canonical_total(db_path, "2025-07") - during, 2) == 168.38
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (stmt_id,)).fetchone()[0] is None
    conn.close()


def test_unlink_skips_non_duplicates(tmp_path):
    def populate(conn):
        return _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap")

    db_path, (csv_id, stmt_id) = _seeded_cli_db(tmp_path, populate)
    result = CliRunner().invoke(cli, ["--db", str(db_path), "dedupe-unlink", str(csv_id)])
    assert result.exit_code == 0
    assert "not a linked duplicate" in result.output


def test_dupes_view_shrinks_after_bulk_link(tmp_path):
    def populate(conn):
        return [
            _capone_pair(conn, "2025-07-06", "2025-07-07", 168.38, "GOl Et Kasap"),
            _capone_pair(conn, "2025-07-08", "2025-07-09", 10.0, "PEYK CAFE"),
        ]

    db_path, pairs = _seeded_cli_db(tmp_path, populate)
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 2
    conn.close()
    assert CliRunner().invoke(
        cli, ["--db", str(db_path), "dedupe-link", "--from-dupes", "--yes"]
    ).exit_code == 0
    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM possible_dupes").fetchone()[0] == 0
    conn.close()
