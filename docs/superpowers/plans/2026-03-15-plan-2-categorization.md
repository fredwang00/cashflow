# Plan 2: Categorization Engine + Review CLI

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically categorize ingested transactions using merchant rules and LLM, then provide an interactive CLI for reviewing and correcting categorizations that feed back into the rules engine.

**Architecture:** Two-stage categorization runs after ingestion: first a deterministic rules check (substring match against merchant_rules), then an LLM call for unmatched transactions. High-confidence results auto-confirm; low-confidence go to a review queue. User corrections create new merchant rules, so the system learns over time.

**Tech Stack:** Python 3.12+, Click, SQLite, Anthropic Claude API (anthropic SDK), pytest

**Spec:** `docs/superpowers/specs/2026-03-14-cashflow-design.md` — sections "Categorization Engine" and "CLI Interface"

**Depends on:** Plan 1 (complete — 30 tests passing, `cashflow ingest` and `cashflow status` working)

---

## New Files

```
src/cashflow/
├── categorize.py          # Rules engine + LLM categorization
└── (cli.py modified)      # Add review command, hook categorize into ingest

tests/
├── test_categorize.py     # Rules matching, LLM mock, auto-accept/queue
└── test_review.py         # Interactive review flow
```

---

## Chunk 1: Rules-Based Categorization

### Task 1: Merchant Rules Matching

**Files:**
- Create: `src/cashflow/categorize.py`
- Create: `tests/test_categorize.py`

- [ ] **Step 1: Write failing tests for rules matching**

```python
# tests/test_categorize.py
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
    # Run again — already confirmed, should not reprocess
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_categorize.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement rules matching**

```python
# src/cashflow/categorize.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_categorize.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/categorize.py tests/test_categorize.py
git commit -m "feat: rules-based merchant categorization engine"
```

---

## Chunk 2: LLM Categorization

### Task 2: LLM Categorization with Mock

**Files:**
- Modify: `src/cashflow/categorize.py`
- Modify: `tests/test_categorize.py`
- Modify: `pyproject.toml` (add anthropic dependency)

- [ ] **Step 1: Add anthropic to dependencies**

In `pyproject.toml`, add `"anthropic>=0.40"` to the `dependencies` list (after `"click>=8.1"`).

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write failing tests for LLM categorization**

Append to `tests/test_categorize.py`:

```python
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
    # Low confidence: category assigned but status stays pending for review
    assert row["status"] == "pending"
    assert row["confidence"] == 60


def test_categorize_by_llm_skips_already_categorized(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Crumbl Cookies")
    # Manually categorize it
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
        # Should not call the API at all
        mock_client.messages.create.assert_not_called()

    assert categorized == 0
    assert pending == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_categorize.py::test_categorize_by_llm_assigns_category -v`
Expected: FAIL — `cannot import name 'categorize_by_llm'`

- [ ] **Step 4: Implement LLM categorization**

Add to `src/cashflow/categorize.py`:

```python
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

    # Build category list for the prompt
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_categorize.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/cashflow/categorize.py tests/test_categorize.py pyproject.toml
git commit -m "feat: LLM-powered categorization with confidence thresholds"
```

---

### Task 3: Wire Categorization into Ingest

**Files:**
- Modify: `src/cashflow/cli.py`

- [ ] **Step 1: Update ingest command to run categorization after storing**

In `src/cashflow/cli.py`, add import at top:

```python
from cashflow.categorize import categorize_by_rules, categorize_by_llm
```

Then in the `ingest` function, after the CSV processing loop (after `click.echo(f"\nDone. {total} transactions ingested.")`), add:

```python
    if total > 0:
        click.echo("Categorizing...")
        rules_matched, rules_unmatched = categorize_by_rules(conn)
        click.echo(f"  Rules: {rules_matched} matched, {rules_unmatched} unmatched")

        if rules_unmatched > 0:
            try:
                llm_confirmed, llm_pending = categorize_by_llm(conn)
                click.echo(f"  LLM: {llm_confirmed} auto-confirmed, {llm_pending} need review")
            except Exception as e:
                click.echo(f"  LLM categorization skipped: {e}")
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS (the CLI tests use mocked/fixture data and won't hit the real API)

- [ ] **Step 3: Commit**

```bash
git add src/cashflow/cli.py
git commit -m "feat: auto-categorize during ingest (rules then LLM)"
```

---

## Chunk 3: Review CLI + Learning Loop

### Task 4: Learning — Create Rules from Corrections

**Files:**
- Modify: `src/cashflow/categorize.py`
- Modify: `tests/test_categorize.py`

- [ ] **Step 1: Write failing tests for learning**

Append to `tests/test_categorize.py`:

```python
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
    # Correct the category — should update existing rule
    confirm_transaction(db, txn_id=1, category_id=cat_id)
    rule = db.execute("SELECT * FROM merchant_rules WHERE pattern = 'Crumbl Cookies'").fetchone()
    assert rule["category_id"] == cat_id
    # Old rule for "Crumbl" should still exist (different pattern)
    old_rule = db.execute("SELECT * FROM merchant_rules WHERE pattern = 'Crumbl'").fetchone()
    assert old_rule is not None


def test_get_pending_for_review(db):
    seed_all(db)
    _insert_pending_txn(db, "t1", "Store A", 25.0)
    _insert_pending_txn(db, "t2", "Store B", 75.0)
    # Categorize t1 but leave pending (low confidence)
    cat_id = db.execute("SELECT id FROM categories WHERE name = 'Shopping'").fetchone()["id"]
    db.execute(
        "UPDATE transactions SET category_id = ?, confidence = 60 WHERE source_id = 't1'",
        (cat_id,),
    )
    db.commit()

    pending = get_pending_for_review(db)
    assert len(pending) == 2
    # Should include category suggestion where available
    t1 = [p for p in pending if p["source_id"] == "t1"][0]
    assert t1["suggested_category"] == "Shopping"
    t2 = [p for p in pending if p["source_id"] == "t2"][0]
    assert t2["suggested_category"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_categorize.py::test_confirm_transaction_updates_status -v`
Expected: FAIL — `cannot import name 'confirm_transaction'`

- [ ] **Step 3: Implement learning functions**

Add to `src/cashflow/categorize.py`:

```python
def confirm_transaction(
    conn: sqlite3.Connection, txn_id: int, category_id: int
) -> None:
    """Confirm a transaction's category and create/update a merchant rule.

    This is the learning loop: user corrections become persistent rules.
    """
    conn.execute(
        "UPDATE transactions SET category_id = ?, status = 'confirmed', "
        "confidence = 100 WHERE id = ?",
        (category_id, txn_id),
    )

    # Get the merchant name to create a rule
    txn = conn.execute(
        "SELECT merchant FROM transactions WHERE id = ?", (txn_id,)
    ).fetchone()

    if txn:
        merchant = txn["merchant"]
        # Upsert: create new rule or update existing one with same pattern
        existing = conn.execute(
            "SELECT id FROM merchant_rules WHERE pattern = ?", (merchant,)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE merchant_rules SET category_id = ?, source = 'learned' "
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
    """Get all pending transactions with their suggested category (if any).

    Returns dicts with transaction fields plus 'suggested_category' name.
    """
    rows = conn.execute(
        "SELECT t.id, t.source_id, t.date, t.amount, t.merchant, t.description, "
        "t.category_id, t.confidence, c.name as suggested_category "
        "FROM transactions t "
        "LEFT JOIN categories c ON t.category_id = c.id "
        "WHERE t.status = 'pending' AND t.canonical_id IS NULL "
        "ORDER BY t.date DESC"
    ).fetchall()

    return [dict(row) for row in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_categorize.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/categorize.py tests/test_categorize.py
git commit -m "feat: learning loop — corrections create persistent merchant rules"
```

---

### Task 5: Interactive Review CLI Command

**Files:**
- Modify: `src/cashflow/cli.py`
- Create: `tests/test_review.py`

- [ ] **Step 1: Write failing test for review command**

```python
# tests/test_review.py
from click.testing import CliRunner
from cashflow.cli import cli


def test_review_shows_pending_transactions(tmp_path):
    db_path = tmp_path / "test.db"
    fixture_path = "tests/fixtures/chase_sample.csv"
    runner = CliRunner()

    # Ingest first (without API key, LLM will be skipped)
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", fixture_path])

    # Review with 's' to skip all
    result = runner.invoke(
        cli, ["--db", str(db_path), "review"], input="s\ns\ns\ns\ns\ns\n"
    )
    assert result.exit_code == 0
    assert "merchant" in result.output.lower() or "$" in result.output


def test_review_empty_queue(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "review"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "no" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_review.py -v`
Expected: FAIL — review command doesn't exist

- [ ] **Step 3: Add review command to cli.py**

Add this import to the top of `src/cashflow/cli.py`:

```python
from cashflow.categorize import categorize_by_rules, categorize_by_llm, confirm_transaction, get_pending_for_review
```

Then add the review command:

```python
@cli.command()
@click.pass_context
def review(ctx):
    """Interactively review and categorize pending transactions."""
    conn = ctx.obj["conn"]

    pending = get_pending_for_review(conn)
    if not pending:
        click.secho("Review queue is empty.", fg="green")
        return

    categories = conn.execute(
        "SELECT id, name, type FROM categories ORDER BY type, name"
    ).fetchall()
    cat_list = [(c["id"], c["name"], c["type"]) for c in categories]

    click.echo(f"\n{len(pending)} transactions to review:\n")

    reviewed = 0
    for txn in pending:
        click.secho(f"  {txn['date']}  ${txn['amount']:>9,.2f}  {txn['merchant']}", fg="white", bold=True)
        click.echo(f"  {txn['description']}")
        if txn["suggested_category"]:
            click.secho(f"  Suggested: {txn['suggested_category']} ({txn['confidence']}% confidence)", fg="cyan")

        click.echo()
        # Show numbered category list
        for i, (cat_id, cat_name, cat_type) in enumerate(cat_list, 1):
            marker = "N" if cat_type == "necessity" else "W"
            click.echo(f"    {i:>3}. [{marker}] {cat_name}")

        click.echo()
        choice = click.prompt(
            "  Enter number to categorize, [a]ccept suggestion, [s]kip, [q]uit",
            default="s",
        )

        if choice.lower() == "q":
            break
        elif choice.lower() == "s":
            continue
        elif choice.lower() == "a" and txn["suggested_category"]:
            confirm_transaction(conn, txn["id"], txn["category_id"])
            click.secho(f"  Confirmed: {txn['suggested_category']}", fg="green")
            reviewed += 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(cat_list):
                cat_id, cat_name, _ = cat_list[idx]
                confirm_transaction(conn, txn["id"], cat_id)
                click.secho(f"  Categorized: {cat_name}", fg="green")
                reviewed += 1
            else:
                click.secho("  Invalid number, skipping.", fg="yellow")
        else:
            click.secho("  Skipped.", fg="yellow")

        click.echo()

    click.echo(f"\nReviewed {reviewed} transactions.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/cashflow/cli.py tests/test_review.py
git commit -m "feat: interactive cashflow review command with category selection"
```

---

### Task 6: Tag Command

**Files:**
- Modify: `src/cashflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for tag command**

Append to `tests/test_cli.py`:

```python
def test_tag_one_off(tmp_path):
    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()

    # Ingest first
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(fixture)])

    # Tag transaction 1 as one-off
    result = runner.invoke(
        cli, ["--db", str(db_path), "tag", "1", "--one-off", "NAS build"]
    )
    assert result.exit_code == 0
    assert "tagged" in result.output.lower() or "one-off" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_tag_one_off -v`
Expected: FAIL — tag command doesn't exist

- [ ] **Step 3: Add tag command to cli.py**

```python
@cli.command()
@click.argument("txn_id", type=int)
@click.option("--one-off", type=str, help="Label this transaction as a one-off expense.")
@click.pass_context
def tag(ctx, txn_id, one_off):
    """Tag a transaction (e.g., as a one-off expense)."""
    conn = ctx.obj["conn"]

    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        click.secho(f"Transaction {txn_id} not found.", fg="red")
        return

    if one_off:
        conn.execute(
            "UPDATE transactions SET is_one_off = 1, one_off_label = ? WHERE id = ?",
            (one_off, txn_id),
        )
        conn.commit()
        click.secho(
            f"Tagged #{txn_id} as one-off: \"{one_off}\" "
            f"(${txn['amount']:,.2f} on {txn['date']})",
            fg="green",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/cashflow/cli.py tests/test_cli.py
git commit -m "feat: cashflow tag command for one-off expense labeling"
```

---

## Summary

After completing Plan 2, you have:
- **Merchant rules engine** — substring matching, case-insensitive, with match counting
- **LLM categorization** — Claude categorizes unknowns, auto-confirms >= 90% confidence
- **Auto-categorization in ingest pipeline** — rules first, then LLM, after every ingest
- **Interactive review CLI** — `cashflow review` shows pending transactions, numbered category picker, accept/skip/quit
- **Learning loop** — every confirmation creates a persistent merchant rule
- **One-off tagging** — `cashflow tag ID --one-off "label"`
- ~44+ automated tests

**Next:** Plan 3 adds remaining CSV parsers (Capital One, BofA, Target), Amazon order reports, and the reconciliation engine.
