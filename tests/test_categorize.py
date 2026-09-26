import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cashflow.seed import seed_all
from cashflow.categorize import (
    categorize_by_llm,
    categorize_by_rules,
    confirm_transaction,
    get_pending_for_review,
)


@pytest.fixture(autouse=True)
def llm_environment(monkeypatch):
    monkeypatch.setenv("CASHFLOW_LLM_KEY", "test-key")
    monkeypatch.setenv("CASHFLOW_LLM_URL", "http://test.local/v1/chat/completions")
    monkeypatch.setenv("CASHFLOW_LLM_KEY_HEADER", "apikey")


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


@pytest.fixture
def llm_transport(monkeypatch):
    """Keep the real HTTP client, replacing only its network transport."""
    client_class = httpx.Client
    def install(handler):
        monkeypatch.setattr(
            "cashflow.categorize.httpx.Client",
            lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


def test_learned_specific_rule_overrides_generic_rule(db):
    seed_all(db)
    _insert_rule(db, "Crumbl", "Shopping")
    _insert_pending_txn(db, "corrected", "Crumbl Cookies")
    category_id = db.execute("SELECT id FROM categories WHERE name = 'Fast Food'").fetchone()["id"]
    confirm_transaction(db, 1, category_id)
    _insert_pending_txn(db, "next", "CRUMBL COOKIES STORE")

    assert categorize_by_rules(db) == (1, 0)
    txn = db.execute("SELECT category_id FROM transactions WHERE source_id = 'next'").fetchone()
    assert txn["category_id"] == category_id


def test_empty_merchant_correction_does_not_create_match_all_rule(db):
    seed_all(db)
    _insert_pending_txn(db, "blank", "")
    category_id = db.execute("SELECT id FROM categories WHERE name = 'Shopping'").fetchone()["id"]
    confirm_transaction(db, 1, category_id)
    _insert_pending_txn(db, "other", "Unrelated Store")
    assert categorize_by_rules(db) == (0, 1)
    assert db.execute("SELECT COUNT(*) FROM merchant_rules WHERE pattern = ''").fetchone()[0] == 0


def test_native_anthropic_request(db, llm_transport, monkeypatch):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    monkeypatch.setenv("CASHFLOW_LLM_URL", "https://api.anthropic.com/v1/messages?test=1")
    monkeypatch.setenv("CASHFLOW_LLM_KEY_HEADER", "x-api-key")

    def handler(request):
        payload = json.loads(request.content)
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["x-api-key"] == "test-key"
        assert "VALID CATEGORIES" in payload["system"]
        assert [message["role"] for message in payload["messages"]] == ["user"]
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"category":"Fast Food","confidence":95}'}]})

    llm_transport(handler)
    assert categorize_by_llm(db) == (1, 0)


@pytest.mark.parametrize("confidence", [101, -1, -0.5, True, "95", float("inf"), float("nan"), 95.5])
def test_invalid_llm_confidence_remains_uncategorized(db, llm_transport, confidence):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Unknown Store")
    response_text = json.dumps({"category": "Shopping", "confidence": confidence})
    llm_transport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": response_text}}]}))

    assert categorize_by_llm(db) == (0, 1)
    txn = db.execute("SELECT category_id, status, confidence FROM transactions WHERE source_id = 't1'").fetchone()
    assert tuple(txn) == (None, "pending", 0)


@pytest.mark.parametrize("content", [None, [], 42, '{"category": [], "confidence":95}'])
def test_malformed_llm_response_does_not_stop_next_transaction(db, llm_transport, content):
    seed_all(db)
    _insert_pending_txn(db, "bad", "Bad Store")
    _insert_pending_txn(db, "good", "Good Store")
    responses = iter([content, '{"category":"Shopping","confidence":95}'])
    llm_transport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": next(responses)}}]}))

    assert categorize_by_llm(db) == (1, 1)
    assert db.execute("SELECT status FROM transactions WHERE source_id = 'good'").fetchone()[0] == "confirmed"


def test_confirm_transaction_refreshes_rule_confidence(db):
    seed_all(db)
    _insert_rule(db, "Store", "Shopping")
    db.execute("UPDATE merchant_rules SET confidence = 60 WHERE pattern = 'Store'")
    _insert_pending_txn(db, "first", "Store")
    category_id = db.execute("SELECT id FROM categories WHERE name = 'Groceries'").fetchone()["id"]
    confirm_transaction(db, 1, category_id)
    _insert_pending_txn(db, "next", "Store")
    categorize_by_rules(db)
    txn = db.execute("SELECT category_id, confidence FROM transactions WHERE source_id = 'next'").fetchone()
    assert tuple(txn) == (category_id, 100)


@pytest.mark.parametrize("confidence, expected", [(0.95, 95), (1.0, 100), (0.0, 0), (0.6, 60)])
def test_probability_confidence_is_normalized(db, llm_transport, confidence, expected):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Store")
    response_text = json.dumps({"category": "Shopping", "confidence": confidence})

    def handler(request):
        payload = json.loads(request.content)
        assert [message["role"] for message in payload["messages"]] == ["system", "user"]
        assert "system" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"content": response_text}}]})

    llm_transport(handler)
    categorize_by_llm(db)
    txn = db.execute("SELECT confidence, status FROM transactions WHERE source_id = 't1'").fetchone()
    assert tuple(txn) == (expected, "confirmed" if expected >= 90 else "pending")
