from cashflow.seed import seed_all
from cashflow.dedup_checking import link_checking_duplicates


def _insert_checking_txn(db, source_id, date, amount, merchant, description):
    acct_id = db.execute("SELECT id FROM accounts WHERE name = 'Checking'").fetchone()["id"]
    db.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
        "VALUES (?, ?, ?, ?, ?, ?, 'confirmed', 100, 'shared', 'csv')",
        (source_id, date, amount, description, merchant, acct_id),
    )
    db.commit()


def test_links_same_date_amount_merchant(db):
    seed_all(db)
    _insert_checking_txn(db, "chk-1", "2026-04-01", 3607.94, "Newrez Mortgage",
                         "NEWREZ-SHELLPOIN DES:ACH PMT ID:XXXXX73355")
    _insert_checking_txn(db, "chk-2", "2026-04-01", 3607.94, "Newrez Mortgage",
                         "NEWREZ-SHELLPOIN DES:ACH PMT ID:0671373355")
    linked = link_checking_duplicates(db)
    assert linked == 1
    dup = db.execute("SELECT canonical_id FROM transactions WHERE source_id = 'chk-2'").fetchone()
    keep = db.execute("SELECT id FROM transactions WHERE source_id = 'chk-1'").fetchone()
    assert dup["canonical_id"] == keep["id"]


def test_does_not_link_different_amounts(db):
    seed_all(db)
    _insert_checking_txn(db, "chk-a", "2026-04-01", 100.0, "Venmo", "Zelle payment")
    _insert_checking_txn(db, "chk-b", "2026-04-01", 200.0, "Venmo", "Zelle payment")
    linked = link_checking_duplicates(db)
    assert linked == 0


def test_does_not_link_different_dates(db):
    seed_all(db)
    _insert_checking_txn(db, "chk-c", "2026-04-01", 100.0, "Venmo", "Zelle")
    _insert_checking_txn(db, "chk-d", "2026-04-02", 100.0, "Venmo", "Zelle")
    linked = link_checking_duplicates(db)
    assert linked == 0


def test_handles_triple_duplicates(db):
    seed_all(db)
    _insert_checking_txn(db, "chk-e", "2026-03-02", 10.0, "Lottery", "NEOP VI Lottery")
    _insert_checking_txn(db, "chk-f", "2026-03-02", 10.0, "Lottery", "NEOP VI Lottery")
    _insert_checking_txn(db, "chk-g", "2026-03-02", 10.0, "Lottery", "NEOP VI Lottery")
    linked = link_checking_duplicates(db)
    assert linked == 2
    keep = db.execute("SELECT id FROM transactions WHERE source_id = 'chk-e'").fetchone()
    for sid in ("chk-f", "chk-g"):
        row = db.execute("SELECT canonical_id FROM transactions WHERE source_id = ?", (sid,)).fetchone()
        assert row["canonical_id"] == keep["id"]


def test_idempotent(db):
    seed_all(db)
    _insert_checking_txn(db, "chk-h", "2026-04-01", 50.0, "Test", "Test")
    _insert_checking_txn(db, "chk-i", "2026-04-01", 50.0, "Test", "Test")
    assert link_checking_duplicates(db) == 1
    assert link_checking_duplicates(db) == 0


def test_skips_non_checking_accounts(db):
    seed_all(db)
    apple_id = db.execute("SELECT id FROM accounts WHERE name = 'Apple Card'").fetchone()["id"]
    db.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
        "VALUES ('apple-1', '2026-04-01', 50.0, 'Test', 'Test', ?, 'confirmed', 100, 'shared', 'csv')",
        (apple_id,),
    )
    db.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
        "VALUES ('apple-2', '2026-04-01', 50.0, 'Test', 'Test', ?, 'confirmed', 100, 'shared', 'csv')",
        (apple_id,),
    )
    db.commit()
    linked = link_checking_duplicates(db)
    assert linked == 0
