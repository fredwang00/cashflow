from cashflow.seed import seed_all
from cashflow.categorize import categorize_by_rules


def _insert_rule(db, pattern, category_name):
    cat_id = db.execute(
        "SELECT id FROM categories WHERE name = ?", (category_name,)
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO merchant_rules (pattern, category_id, source, confidence) "
        "VALUES (?, ?, 'manual', 100)",
        (pattern, cat_id),
    )
    db.commit()


def _insert_pending_txn(db, source_id, merchant, amount=50.0):
    db.execute(
        "INSERT INTO transactions "
        "(source_id, date, amount, description, merchant, account_id, "
        "status, confidence, who, source_type) "
        "VALUES (?, '2026-03-01', ?, ?, ?, 1, 'pending', 0, 'shared', 'csv')",
        (source_id, amount, merchant, merchant),
    )
    db.commit()


def test_categorize_by_rules_matches_substring(db):
    seed_all(db)
    _insert_rule(db, "Whole Foods", "Groceries")
    _insert_pending_txn(db, "t1", "Whole Foods")
    matched, unmatched = categorize_by_rules(db)
    assert matched == 1
    assert unmatched == 0
    row = db.execute("SELECT * FROM transactions WHERE source_id = 't1'").fetchone()
    cat = db.execute("SELECT name FROM categories WHERE id = ?", (row["category_id"],)).fetchone()
    assert cat["name"] == "Groceries"
    assert row["status"] == "confirmed"
    assert row["confidence"] == 100


def test_categorize_by_rules_case_insensitive(db):
    seed_all(db)
    _insert_rule(db, "whole foods", "Groceries")
    _insert_pending_txn(db, "t1", "WHOLE FOODS MARKET")
    matched, _ = categorize_by_rules(db)
    assert matched == 1


def test_categorize_by_rules_skips_already_categorized(db):
    seed_all(db)
    _insert_rule(db, "Whole Foods", "Groceries")
    _insert_pending_txn(db, "t1", "Whole Foods")
    categorize_by_rules(db)
    matched, unmatched = categorize_by_rules(db)
    assert matched == 0
    assert unmatched == 0


def test_categorize_by_rules_returns_unmatched(db):
    seed_all(db)
    _insert_rule(db, "Whole Foods", "Groceries")
    _insert_pending_txn(db, "t1", "Whole Foods")
    _insert_pending_txn(db, "t2", "Unknown Merchant")
    matched, unmatched = categorize_by_rules(db)
    assert matched == 1
    assert unmatched == 1


def test_categorize_by_rules_increments_match_count(db):
    seed_all(db)
    _insert_rule(db, "Whole Foods", "Groceries")
    _insert_pending_txn(db, "t1", "Whole Foods")
    _insert_pending_txn(db, "t2", "Whole Foods Market ONE")
    categorize_by_rules(db)
    rule = db.execute("SELECT match_count FROM merchant_rules WHERE pattern = 'Whole Foods'").fetchone()
    assert rule["match_count"] == 2


from unittest.mock import patch, MagicMock
from cashflow.categorize import categorize_by_llm


def test_categorize_by_llm_assigns_category(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"category": "Fast Food", "confidence": 95}')]

    with patch("cashflow.categorize.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response
        categorized, pending = categorize_by_llm(db)

    assert categorized == 1
    assert pending == 0
    row = db.execute("SELECT * FROM transactions WHERE source_id = 't1'").fetchone()
    cat = db.execute("SELECT name FROM categories WHERE id = ?", (row["category_id"],)).fetchone()
    assert cat["name"] == "Fast Food"
    assert row["status"] == "confirmed"
    assert row["confidence"] == 95


def test_categorize_by_llm_queues_low_confidence(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Mysterious Store")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"category": "Shopping", "confidence": 60}')]

    with patch("cashflow.categorize.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response
        categorized, pending = categorize_by_llm(db)

    assert categorized == 0
    assert pending == 1
    row = db.execute("SELECT * FROM transactions WHERE source_id = 't1'").fetchone()
    cat = db.execute("SELECT name FROM categories WHERE id = ?", (row["category_id"],)).fetchone()
    assert cat["name"] == "Shopping"
    assert row["status"] == "pending"
    assert row["confidence"] == 60


def test_categorize_by_llm_skips_already_categorized(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Fast Food'").fetchone()["id"]
    db.execute(
        "UPDATE transactions SET category_id = ?, status = 'confirmed', confidence = 100 "
        "WHERE source_id = 't1'",
        (cat_id,),
    )
    db.commit()

    with patch("cashflow.categorize.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        categorized, pending = categorize_by_llm(db)
        mock_client.messages.create.assert_not_called()

    assert categorized == 0
    assert pending == 0
