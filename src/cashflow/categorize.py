import sqlite3


def categorize_by_rules(conn: sqlite3.Connection) -> tuple[int, int]:
    """Apply merchant_rules to pending uncategorized transactions.

    Returns (matched_count, unmatched_count).
    Matched transactions get status='confirmed' and the rule's category_id.
    """
    rules = conn.execute(
        "SELECT id, pattern, category_id, confidence FROM merchant_rules"
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


import json
import anthropic


CATEGORIZE_SYSTEM_PROMPT = """You categorize household financial transactions.

Given a merchant name, amount, and description, return a JSON object with:
- "category": the best matching category name from the list below
- "confidence": 0-100 how confident you are

CATEGORIES:
{categories}

Rules:
- Return ONLY valid JSON, no explanation
- "category" must exactly match one of the category names above
- Use 90+ confidence for obvious matches
- Use 50-89 for reasonable guesses
- Use below 50 only if truly uncertain
"""


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

    client = anthropic.Anthropic()
    confirmed = 0
    still_pending = 0

    for txn in pending:
        user_msg = (
            f"Merchant: {txn['merchant']}\n"
            f"Description: {txn['description']}\n"
            f"Amount: ${txn['amount']:.2f}"
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=100,
                system=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()
            result = json.loads(raw)
            category_name = result["category"]
            confidence = int(result["confidence"])
        except (json.JSONDecodeError, KeyError, IndexError, anthropic.APIError):
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
