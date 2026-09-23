import json
import os
import re
import sqlite3
from urllib.parse import urlsplit

import httpx


def categorize_by_rules(conn: sqlite3.Connection) -> tuple[int, int]:
    """Apply merchant_rules to pending uncategorized transactions.

    Returns (matched_count, unmatched_count).
    Matched transactions get status='confirmed' and the rule's category_id.
    More specific (longer) patterns win; equal lengths favor the newest rule.
    """
    rules = conn.execute(
        "SELECT id, pattern, category_id, confidence FROM merchant_rules "
        "WHERE trim(pattern) != '' ORDER BY length(pattern) DESC, id DESC"
    ).fetchall()

    pending = conn.execute(
        "SELECT id, merchant FROM transactions "
        "WHERE status = 'pending' AND category_id IS NULL AND canonical_id IS NULL"
    ).fetchall()

    matched = 0
    unmatched = 0

    for txn in pending:
        txn_merchant = txn["merchant"].lower()
        rule_hit = None

        for rule in rules:
            if rule["pattern"].lower() in txn_merchant:
                rule_hit = rule
                break

        if rule_hit:
            conn.execute(
                "UPDATE transactions SET category_id = ?, status = 'confirmed', "
                "confidence = ? WHERE id = ?",
                (rule_hit["category_id"], rule_hit["confidence"], txn["id"]),
            )
            conn.execute(
                "UPDATE merchant_rules SET match_count = match_count + 1 WHERE id = ?",
                (rule_hit["id"],),
            )
            matched += 1
        else:
            unmatched += 1

    conn.commit()
    return matched, unmatched


CATEGORIZE_SYSTEM_PROMPT = """You categorize household financial transactions into EXACTLY one of the categories below.

Return ONLY a JSON object with two fields — no markdown, no explanation, no extra fields:
{{"category": "EXACT_CATEGORY_NAME", "confidence": 95}}

confidence is an integer 0-100.

VALID CATEGORIES (you MUST use one of these exact strings):
{categories}

If unsure, pick the closest match with lower confidence. Use "Shopping" as fallback."""


def categorize_by_llm(conn: sqlite3.Connection) -> tuple[int, int]:
    """Use Claude to categorize pending uncategorized transactions.

    Returns (auto_confirmed_count, still_pending_count).
    Confidence >= 90 auto-confirms. Lower confidence assigns category
    but leaves status as pending for human review.
    """
    pending = conn.execute(
        "SELECT id, merchant, description, amount FROM transactions "
        "WHERE status = 'pending' AND category_id IS NULL AND canonical_id IS NULL"
    ).fetchall()

    if not pending:
        return 0, 0

    categories = conn.execute(
        "SELECT id, name FROM categories ORDER BY name"
    ).fetchall()
    cat_names = [c["name"] for c in categories]
    cat_lookup = {c["name"]: c["id"] for c in categories}

    system_prompt = CATEGORIZE_SYSTEM_PROMPT.format(
        categories="\n".join(f"- {name}" for name in cat_names)
    )

    api_url = os.environ.get("CASHFLOW_LLM_URL", "")
    if not api_url:
        raise ValueError(
            "CASHFLOW_LLM_URL not set. See .env.example for configuration."
        )
    api_key = os.environ.get("CASHFLOW_LLM_KEY", "")
    # Auth header varies by provider: Anthropic uses "x-api-key",
    # OpenAI-compatible proxies often use "apikey" or "Authorization: Bearer"
    api_key_header = os.environ.get("CASHFLOW_LLM_KEY_HEADER", "apikey")
    model = os.environ.get("CASHFLOW_LLM_MODEL", "claude-sonnet-4-5-20250929")
    native_anthropic = urlsplit(api_url).path.rstrip("/").endswith("/v1/messages")
    headers = {api_key_header: api_key, "Content-Type": "application/json"}
    if native_anthropic:
        headers["anthropic-version"] = "2023-06-01"

    confirmed = 0
    still_pending = 0

    with httpx.Client(timeout=30.0) as client:
        for txn in pending:
            user_msg = (
                f"Merchant: {txn['merchant']}\n"
                f"Description: {txn['description']}\n"
                f"Amount: ${txn['amount']:.2f}"
            )

            try:
                payload = {
                    "model": model,
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": user_msg}],
                }
                if native_anthropic:
                    payload["system"] = system_prompt
                else:
                    payload["messages"].insert(0, {"role": "system", "content": system_prompt})
                resp = client.post(
                    api_url,
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                # Handle both OpenAI-compatible format (choices[]) and
                # native Anthropic format (content[])
                if "choices" in data:
                    raw = data["choices"][0]["message"]["content"]
                else:
                    raw = data["content"][0]["text"]
                if not isinstance(raw, str):
                    raise ValueError("LLM response content must be text")
                raw = raw.strip()
                # Strip markdown code fences if present
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw)
                result = json.loads(raw)
                category_name = result["category"]
                if not isinstance(category_name, str):
                    raise ValueError("LLM category must be a string")
                # Handle confidence as float 0-1 or int 0-100
                conf_raw = result["confidence"]
                if type(conf_raw) is float and 0 <= conf_raw <= 1:
                    confidence = int(conf_raw * 100)
                elif type(conf_raw) is int and 0 <= conf_raw <= 100:
                    confidence = conf_raw
                else:
                    raise ValueError("LLM confidence must be a probability or integer percentage")
            except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError, httpx.HTTPError):
                still_pending += 1
                continue

            category_id = cat_lookup.get(category_name)
            if category_id is None:
                still_pending += 1
                continue

            if confidence >= 90:
                conn.execute(
                    "UPDATE transactions SET category_id = ?, status = 'confirmed', "
                    "confidence = ? WHERE id = ?",
                    (category_id, confidence, txn["id"]),
                )
                confirmed += 1
            else:
                conn.execute(
                    "UPDATE transactions SET category_id = ?, confidence = ? WHERE id = ?",
                    (category_id, confidence, txn["id"]),
                )
                still_pending += 1

    conn.commit()
    return confirmed, still_pending


def confirm_transaction(
    conn: sqlite3.Connection, txn_id: int, category_id: int
) -> None:
    """Confirm a transaction's category and create/update a merchant rule."""
    conn.execute(
        "UPDATE transactions SET category_id = ?, status = 'confirmed', "
        "confidence = 100 WHERE id = ?",
        (category_id, txn_id),
    )

    txn = conn.execute(
        "SELECT merchant FROM transactions WHERE id = ?", (txn_id,)
    ).fetchone()

    if txn and txn["merchant"].strip():
        merchant = txn["merchant"]
        existing = conn.execute(
            "SELECT id FROM merchant_rules WHERE pattern = ?", (merchant,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE merchant_rules SET category_id = ?, source = 'learned', confidence = 100 "
                "WHERE id = ?",
                (category_id, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO merchant_rules (pattern, category_id, source, confidence) "
                "VALUES (?, ?, 'learned', 100)",
                (merchant, category_id),
            )

    conn.commit()


def get_pending_for_review(conn: sqlite3.Connection) -> list[dict]:
    """Get all pending transactions with their suggested category (if any)."""
    rows = conn.execute(
        "SELECT t.id, t.source_id, t.date, t.amount, t.merchant, t.description, "
        "t.category_id, t.confidence, c.name as suggested_category "
        "FROM transactions t "
        "LEFT JOIN categories c ON t.category_id = c.id "
        "WHERE t.status = 'pending' AND t.canonical_id IS NULL "
        "ORDER BY t.date DESC"
    ).fetchall()

    return [dict(row) for row in rows]
