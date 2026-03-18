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


import os
from unittest.mock import patch, MagicMock
from cashflow.categorize import categorize_by_llm

os.environ.setdefault("CASHFLOW_LLM_KEY", "test-key")
os.environ.setdefault("CASHFLOW_LLM_URL", "http://test.local/v1/chat/completions")


def _mock_llm_response(json_body, format="openai"):
    """Create a mock httpx.Response.

    format='openai' → OpenAI-compatible choices[] format
    format='anthropic' → native Anthropic content[] format
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    if format == "anthropic":
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": json_body}]
        }
    else:
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json_body}}]
        }
    return mock_resp


def test_categorize_by_llm_assigns_category(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")

    mock_resp = _mock_llm_response('{"category": "Fast Food", "confidence": 95}')

    with patch("cashflow.categorize.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
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

    mock_resp = _mock_llm_response('{"category": "Shopping", "confidence": 60}')

    with patch("cashflow.categorize.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        categorized, pending = categorize_by_llm(db)

    assert categorized == 0
    assert pending == 1
    row = db.execute("SELECT * FROM transactions WHERE source_id = 't1'").fetchone()
    cat = db.execute("SELECT name FROM categories WHERE id = ?", (row["category_id"],)).fetchone()
    assert cat["name"] == "Shopping"
    assert row["status"] == "pending"
    assert row["confidence"] == 60


def test_categorize_by_llm_handles_anthropic_response_format(db):
    """Native Anthropic API returns content[] not choices[]."""
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")

    mock_resp = _mock_llm_response('{"category": "Fast Food", "confidence": 92}', format="anthropic")

    with patch("cashflow.categorize.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        categorized, pending = categorize_by_llm(db)

    assert categorized == 1
    assert pending == 0


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

    with patch("cashflow.categorize.httpx.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        MockClient.return_value.__exit__ = MagicMock(return_value=False)
        categorized, pending = categorize_by_llm(db)
        mock_client.post.assert_not_called()

    assert categorized == 0
    assert pending == 0


from cashflow.categorize import confirm_transaction, get_pending_for_review


def test_confirm_transaction_updates_status(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Fast Food'").fetchone()["id"]
    confirm_transaction(db, txn_id=1, category_id=cat_id)
    row = db.execute("SELECT * FROM transactions WHERE id = 1").fetchone()
    assert row["status"] == "confirmed"
    assert row["category_id"] == cat_id
    assert row["confidence"] == 100


def test_confirm_transaction_creates_merchant_rule(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Fast Food'").fetchone()["id"]
    confirm_transaction(db, txn_id=1, category_id=cat_id)
    rule = db.execute(
        "SELECT * FROM merchant_rules WHERE pattern = 'Crumbl Cookies'"
    ).fetchone()
    assert rule is not None
    assert rule["category_id"] == cat_id
    assert rule["source"] == "learned"


def test_confirm_transaction_updates_existing_rule(db):
    seed_all(db)
    _insert_rule(db, "Crumbl", "Shopping")
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Fast Food'").fetchone()["id"]
    confirm_transaction(db, txn_id=1, category_id=cat_id)
    rule = db.execute("SELECT * FROM merchant_rules WHERE pattern = 'Crumbl Cookies'").fetchone()
    assert rule["category_id"] == cat_id
    old_rule = db.execute("SELECT * FROM merchant_rules WHERE pattern = 'Crumbl'").fetchone()
    assert old_rule is not None


def test_get_pending_for_review(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Store A", 25.0)
    _insert_pending_txn(db, "t2", "Store B", 75.0)
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Shopping'").fetchone()["id"]
    db.execute(
        "UPDATE transactions SET category_id = ?, confidence = 60 WHERE source_id = 't1'",
        (cat_id,),
    )
    db.commit()

    pending = get_pending_for_review(db)
    assert len(pending) == 2
    t1 = [p for p in pending if p["source_id"] == "t1"][0]
    assert t1["suggested_category"] == "Shopping"
    t2 = [p for p in pending if p["source_id"] == "t2"][0]
    assert t2["suggested_category"] is None
