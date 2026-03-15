# Plan 1: Foundation — Schema, Chase CSV Ingestion, Status CLI

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Go from zero to ingesting Chase Prime Visa CSVs, storing categorized transactions in SQLite, and displaying burn rate via `cashflow status`.

**Architecture:** Python CLI (Click) backed by SQLite. CSV parser reads Chase statement exports, normalizes transactions, and stores them. Seed data populates categories, accounts, and goals from the existing 2025 budget. Status command computes burn rate and surplus from stored data.

**Tech Stack:** Python 3.12+, Click, SQLite (stdlib sqlite3), pytest

**Spec:** `docs/superpowers/specs/2026-03-14-cashflow-design.md`

---

## File Structure

```
cashflow/
├── pyproject.toml                  # Package metadata, dependencies, entry point
├── src/
│   └── cashflow/
│       ├── __init__.py
│       ├── cli.py                  # Click group + subcommands
│       ├── db.py                   # Schema creation, connection helper
│       ├── seed.py                 # Seed categories, accounts, goals
│       ├── models.py              # Dataclasses for parsed transactions
│       ├── parsers/
│       │   ├── __init__.py
│       │   └── chase.py           # Chase Prime Visa CSV parser
│       └── queries.py             # Read queries (status, review queue count)
├── tests/
│   ├── conftest.py                # Shared fixtures: in-memory DB, sample data
│   ├── test_db.py                 # Schema creation tests
│   ├── test_seed.py               # Seed data tests
│   ├── test_chase_parser.py       # Chase CSV parsing tests
│   ├── test_ingest.py             # End-to-end ingest tests
│   ├── test_queries.py            # Status/query tests
│   └── fixtures/
│       └── chase_sample.csv       # Minimal Chase CSV fixture
└── docs/
```

---

## Chunk 1: Project Scaffolding + Database

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/cashflow/__init__.py`
- Create: `src/cashflow/cli.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "cashflow"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[project.scripts]
cashflow = "cashflow.cli:cli"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2: Create package init**

```python
# src/cashflow/__init__.py
```

Empty file. Just marks the package.

- [ ] **Step 3: Create minimal CLI entry point**

```python
# src/cashflow/cli.py
import click


@click.group()
def cli():
    """Household financial dashboard."""
    pass
```

- [ ] **Step 4: Create test conftest with DB fixture**

```python
# tests/conftest.py
import sqlite3
import pytest


@pytest.fixture
def db():
    """In-memory SQLite database with schema applied."""
    from cashflow.db import create_schema

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    yield conn
    conn.close()
```

- [ ] **Step 5: Install package in dev mode and verify**

Run: `cd /Users/fwang/code/cashflow && pip install -e ".[dev]"`
Then: `cashflow --help`
Expected: Shows "Household financial dashboard." and usage info.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py
git commit -m "chore: scaffold cashflow project with Click CLI entry point"
```

---

### Task 2: Database Schema

**Files:**
- Create: `src/cashflow/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test for schema creation**

```python
# tests/test_db.py
import sqlite3
import pytest
from cashflow.db import create_schema, get_connection


def test_create_schema_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    expected = [
        "accounts",
        "amazon_items",
        "budgets",
        "categories",
        "goals",
        "income",
        "ingest_state",
        "merchant_rules",
        "transactions",
    ]
    assert tables == expected
    conn.close()


def test_transactions_source_id_is_unique():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute(
        "INSERT INTO accounts (name, type, institution, is_active) "
        "VALUES ('Test', 'credit', 'Test', 1)"
    )
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, "
        "account_id, status, confidence, who, source_type) "
        "VALUES ('abc', '2026-01-01', 100.0, 'test', 'test', 1, 'confirmed', 100, "
        "'fred', 'csv')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transactions (source_id, date, amount, description, merchant, "
            "account_id, status, confidence, who, source_type) "
            "VALUES ('abc', '2026-01-02', 200.0, 'test2', 'test2', 1, 'confirmed', "
            "100, 'fred', 'csv')"
        )
    conn.close()


def test_budgets_unique_constraint():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute(
        "INSERT INTO categories (name, type) VALUES ('Groceries', 'want')"
    )
    conn.execute(
        "INSERT INTO budgets (category_id, year, month, amount) "
        "VALUES (1, 2026, 3, 1200.0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO budgets (category_id, year, month, amount) "
            "VALUES (1, 2026, 3, 1500.0)"
        )
    conn.close()


def test_canonical_id_self_reference():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute(
        "INSERT INTO accounts (name, type, institution, is_active) "
        "VALUES ('Test', 'credit', 'Test', 1)"
    )
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, "
        "account_id, status, confidence, who, source_type) "
        "VALUES ('email-1', '2026-01-01', 50.0, 'test', 'Amazon', 1, 'confirmed', "
        "100, 'fred', 'email')"
    )
    # Second record from CSV linked to first via canonical_id
    conn.execute(
        "INSERT INTO transactions (source_id, canonical_id, date, amount, description, "
        "merchant, account_id, status, confidence, who, source_type) "
        "VALUES ('csv-1', 1, '2026-01-01', 50.0, 'AMAZON MKTPL', 'Amazon', 1, "
        "'confirmed', 100, 'fred', 'csv')"
    )
    # Only canonical records (canonical_id IS NULL) should appear in deduped queries
    rows = conn.execute(
        "SELECT * FROM transactions WHERE canonical_id IS NULL"
    ).fetchall()
    assert len(rows) == 1
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/fwang/code/cashflow && python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cashflow.db'`

- [ ] **Step 3: Implement db.py with full schema**

```python
# src/cashflow/db.py
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".cashflow" / "cashflow.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a connection to the cashflow database, creating it if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist."""
    conn.executescript(SCHEMA_SQL)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES categories(id),
    type TEXT NOT NULL CHECK (type IN ('necessity', 'want'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('credit', 'debit', 'cash')),
    institution TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT UNIQUE NOT NULL,
    canonical_id INTEGER REFERENCES transactions(id),
    date DATE NOT NULL,
    amount REAL NOT NULL,
    description TEXT NOT NULL,
    merchant TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    is_one_off BOOLEAN NOT NULL DEFAULT 0,
    one_off_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed')),
    confidence INTEGER NOT NULL DEFAULT 0,
    who TEXT NOT NULL DEFAULT 'shared' CHECK (who IN ('fred', 'wife', 'shared')),
    source_type TEXT NOT NULL CHECK (source_type IN ('email', 'csv', 'amazon_report', 'manual')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS amazon_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER REFERENCES transactions(id),
    order_number TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price REAL NOT NULL,
    order_date DATE NOT NULL,
    account TEXT NOT NULL CHECK (account IN ('fred', 'wife')),
    category_id INTEGER REFERENCES categories(id),
    is_subscribe_save BOOLEAN NOT NULL DEFAULT 0,
    delivery_frequency TEXT
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    amount REAL NOT NULL,
    UNIQUE (category_id, year, month)
);

CREATE TABLE IF NOT EXISTS merchant_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT UNIQUE NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'learned')),
    confidence INTEGER NOT NULL DEFAULT 100,
    match_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT UNIQUE NOT NULL,
    date DATE NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    pay_period TEXT
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('ceiling', 'surplus', 'sinking', 'invest')),
    amount REAL NOT NULL,
    period TEXT CHECK (period IN ('monthly', 'yearly')),
    target_date DATE
);

CREATE TABLE IF NOT EXISTS ingest_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    last_sync DATETIME,
    cursor TEXT,
    metadata TEXT
);
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/db.py tests/test_db.py
git commit -m "feat: add SQLite schema with all tables from spec"
```

---

### Task 3: Seed Data

**Files:**
- Create: `src/cashflow/seed.py`
- Create: `tests/test_seed.py`

- [ ] **Step 1: Write failing tests for seed data**

```python
# tests/test_seed.py
from cashflow.seed import seed_categories, seed_accounts, seed_goals, seed_all


def test_seed_categories_creates_necessities(db):
    seed_categories(db)
    rows = db.execute(
        "SELECT name FROM categories WHERE type = 'necessity' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "Mortgage" in names
    assert "Auto Insurance" in names
    assert "Verizon" in names


def test_seed_categories_creates_wants(db):
    seed_categories(db)
    rows = db.execute(
        "SELECT name FROM categories WHERE type = 'want' AND parent_id IS NULL "
        "ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "Groceries" in names
    assert "Restaurants" in names
    assert "Kids Activities" in names


def test_seed_categories_creates_subscriptions_as_children(db):
    seed_categories(db)
    # Subscriptions parent
    parent = db.execute(
        "SELECT id FROM categories WHERE name = 'Subscriptions'"
    ).fetchone()
    assert parent is not None
    children = db.execute(
        "SELECT name FROM categories WHERE parent_id = ?", (parent["id"],)
    ).fetchall()
    names = [r["name"] for r in children]
    assert "CAROL Bike" in names
    assert "Amazon Prime" in names
    assert "Audible" in names


def test_seed_categories_creates_amazon_mixed(db):
    seed_categories(db)
    row = db.execute(
        "SELECT * FROM categories WHERE name = 'Amazon - Mixed'"
    ).fetchone()
    assert row is not None
    assert row["type"] == "want"


def test_seed_accounts(db):
    seed_accounts(db)
    rows = db.execute("SELECT name FROM accounts ORDER BY name").fetchall()
    names = [r["name"] for r in rows]
    assert "Chase Prime Visa" in names
    assert "Chase Freedom" in names
    assert "Capital One" in names
    assert "Bank of America" in names
    assert "Target Card" in names
    assert "Checking" in names


def test_seed_goals(db):
    seed_goals(db)
    ceiling = db.execute(
        "SELECT * FROM goals WHERE type = 'ceiling'"
    ).fetchone()
    assert ceiling["amount"] == 12000.0
    assert ceiling["period"] == "monthly"

    surplus = db.execute(
        "SELECT * FROM goals WHERE type = 'surplus'"
    ).fetchone()
    assert surplus["amount"] == 40000.0
    assert surplus["period"] == "yearly"


def test_seed_all_is_idempotent(db):
    seed_all(db)
    count_1 = db.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    seed_all(db)
    count_2 = db.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    assert count_1 == count_2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement seed.py**

```python
# src/cashflow/seed.py
import sqlite3

NECESSITIES = [
    "Mortgage", "Mom&Dad Payment", "Auto Insurance", "Gas & Fuel",
    "Service & Parts", "Nat Gas + Electricity", "CVB Public Utility",
    "Hampton Roads Sanitation", "Verizon", "AT&T", "Term Life Insurance",
    "Water Delivery", "YouTube TV", "YouTube Premium", "Credit Card Fees",
]

WANTS = [
    "Groceries", "Fast Food", "Restaurants", "Kids Activities", "Outschool",
    "Clothing", "Landscaping", "Home Improvement", "Soda Stream", "Coffee",
    "Shopping", "Gifts", "Birthdays & Holidays", "Christmas", "Amazon - Mixed",
]

SUBSCRIPTIONS = [
    "CAROL Bike", "Patreon", "Crunchyroll", "Google One", "iCloud+",
    "Amazon Prime", "Audible", "Ashby Payment", "AppleCard Payment",
]

ACCOUNTS = [
    ("Chase Prime Visa", "credit", "Chase"),
    ("Chase Freedom", "credit", "Chase"),
    ("Capital One", "credit", "Capital One"),
    ("Bank of America", "credit", "BofA"),
    ("Target Card", "credit", "Target"),
    ("Checking", "debit", "Chase"),
]

GOALS = [
    ("Monthly Ceiling", "ceiling", 12000.0, "monthly", None),
    ("Annual Surplus", "surplus", 40000.0, "yearly", None),
]


def seed_categories(conn: sqlite3.Connection) -> None:
    """Seed category hierarchy. Idempotent — skips existing rows."""
    for name in NECESSITIES:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'necessity')",
            (name,),
        )
    for name in WANTS:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'want')",
            (name,),
        )
    # Subscriptions parent category
    conn.execute(
        "INSERT OR IGNORE INTO categories (name, type) VALUES ('Subscriptions', 'want')"
    )
    parent_id = conn.execute(
        "SELECT id FROM categories WHERE name = 'Subscriptions'"
    ).fetchone()[0]
    for name in SUBSCRIPTIONS:
        conn.execute(
            "INSERT OR IGNORE INTO categories (name, parent_id, type) "
            "VALUES (?, ?, 'want')",
            (name, parent_id),
        )
    conn.commit()


def seed_accounts(conn: sqlite3.Connection) -> None:
    """Seed account list. Idempotent."""
    for name, acct_type, institution in ACCOUNTS:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (name, type, institution, is_active) "
            "VALUES (?, ?, ?, 1)",
            (name, acct_type, institution),
        )
    conn.commit()


def seed_goals(conn: sqlite3.Connection) -> None:
    """Seed default goals. Idempotent."""
    for name, goal_type, amount, period, target_date in GOALS:
        conn.execute(
            "INSERT OR IGNORE INTO goals (name, type, amount, period, target_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, goal_type, amount, period, target_date),
        )
    conn.commit()


def seed_all(conn: sqlite3.Connection) -> None:
    """Run all seed functions."""
    seed_categories(conn)
    seed_accounts(conn)
    seed_goals(conn)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_seed.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/seed.py tests/test_seed.py
git commit -m "feat: seed categories, accounts, and goals from 2025 budget"
```

---

## Chunk 2: Chase CSV Parser + Ingest CLI

### Task 4: Chase CSV Test Fixture

**Files:**
- Create: `tests/fixtures/chase_sample.csv`

Chase CSVs have this format (from the actual statements — download one from Chase to confirm, but this matches the standard export):

- [ ] **Step 1: Create minimal Chase CSV fixture**

```csv
Transaction Date,Post Date,Description,Category,Type,Amount,Memo
12/01/2025,12/02/2025,AMAZON MKTPL*BB89X0D51 Amzn.com/bill WA Order Number 112-0026560-9545020,Shopping,Sale,-150.65,
12/01/2025,12/02/2025,Audible*BB83D6RN2 Amzn.com/bill NJ Order Number D01-0333631-0963463,Shopping,Sale,-4.21,
12/01/2025,12/01/2025,AUTOMATIC PAYMENT - THANK YOU,,Payment,4215.60,
12/02/2025,12/03/2025,Whole Foods Market ONE WFM.COM/HELP DE,Groceries,Sale,-15.97,
12/02/2025,12/03/2025,AMAZON MKTPL*BB4BV0BC0 Amzn.com/bill WA Order Number 112-4930024-9146614,Shopping,Sale,-17.91,
12/02/2025,12/03/2025,AMAZON MKTPL*BB11169Z1 Amzn.com/bill WA Order Number 112-8303932-0955457,Shopping,Sale,-12.64,
12/04/2025,12/05/2025,Amazon.com*BI8A11MA2 Amzn.com/bill WA Order Number 112-8834452-7280211,Shopping,Sale,-169.26,
```

Note: Chase CSVs use **negative amounts for purchases** and positive for payments/credits. This is the opposite of our spec convention (positive = expense). The parser must flip the sign.

- [ ] **Step 2: Commit fixture**

```bash
git add tests/fixtures/chase_sample.csv
git commit -m "test: add Chase Prime Visa CSV fixture"
```

---

### Task 5: Chase CSV Parser

**Files:**
- Create: `src/cashflow/models.py`
- Create: `src/cashflow/parsers/__init__.py`
- Create: `src/cashflow/parsers/chase.py`
- Create: `tests/test_chase_parser.py`

- [ ] **Step 1: Create models.py with ParsedTransaction dataclass**

```python
# src/cashflow/models.py
from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class ParsedTransaction:
    """A transaction parsed from any source, not yet stored in the DB."""

    date: date
    amount: float  # Positive = expense, negative = credit/refund
    description: str
    merchant: str
    source_id: str  # Unique key for dedup
    source_type: str  # 'csv', 'email', etc.
    account_name: str  # e.g., 'Chase Prime Visa'
    order_number: Optional[str] = None  # Amazon order number if found
```

- [ ] **Step 2: Write failing tests for Chase parser**

```python
# tests/test_chase_parser.py
from pathlib import Path
from cashflow.parsers.chase import parse_chase_csv

FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"


def test_parse_chase_csv_returns_transactions():
    txns = parse_chase_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_chase_csv_skips_payments():
    txns = parse_chase_csv(FIXTURE)
    descriptions = [t.description for t in txns]
    assert not any("AUTOMATIC PAYMENT" in d for d in descriptions)


def test_parse_chase_csv_flips_sign():
    """Chase uses negative for purchases. We want positive for expenses."""
    txns = parse_chase_csv(FIXTURE)
    # All remaining txns should be purchases (positive after flip)
    assert all(t.amount > 0 for t in txns)


def test_parse_chase_csv_extracts_order_number():
    txns = parse_chase_csv(FIXTURE)
    amazon_txns = [t for t in txns if t.order_number is not None]
    assert len(amazon_txns) >= 4
    # Check specific order number format
    assert any(t.order_number == "112-0026560-9545020" for t in amazon_txns)


def test_parse_chase_csv_normalizes_merchant():
    txns = parse_chase_csv(FIXTURE)
    wf = [t for t in txns if "Whole Foods" in t.merchant]
    assert len(wf) == 1
    assert wf[0].merchant == "Whole Foods"


def test_parse_chase_csv_source_id_is_unique():
    txns = parse_chase_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_chase_csv_sets_account_name():
    txns = parse_chase_csv(FIXTURE)
    assert all(t.account_name == "Chase Prime Visa" for t in txns)


def test_parse_chase_csv_sets_source_type():
    txns = parse_chase_csv(FIXTURE)
    assert all(t.source_type == "csv" for t in txns)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_chase_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement Chase CSV parser**

```python
# src/cashflow/parsers/__init__.py
```

```python
# src/cashflow/parsers/chase.py
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from cashflow.models import ParsedTransaction

ORDER_NUMBER_RE = re.compile(r"Order Number\s+(\d{3}-\d{7}-\d{7})")
# Also handle D01- prefix for digital orders (Audible, Prime Video)
DIGITAL_ORDER_RE = re.compile(r"Order Number\s+(D\d{2}-\d{7}-\d{7})")

MERCHANT_PATTERNS = [
    (re.compile(r"Whole Foods", re.IGNORECASE), "Whole Foods"),
    (re.compile(r"AMAZON MKTPL", re.IGNORECASE), "Amazon Marketplace"),
    (re.compile(r"Amazon\.com", re.IGNORECASE), "Amazon.com"),
    (re.compile(r"Audible", re.IGNORECASE), "Audible"),
    (re.compile(r"Prime Video", re.IGNORECASE), "Prime Video"),
    (re.compile(r"Kindle Svcs", re.IGNORECASE), "Kindle"),
]


def _normalize_merchant(description: str) -> str:
    """Extract a clean merchant name from the raw Chase description."""
    for pattern, name in MERCHANT_PATTERNS:
        if pattern.search(description):
            return name
    # Fallback: take everything before the first digit/special char cluster
    cleaned = re.split(r"[*#]", description)[0].strip()
    return cleaned if cleaned else description


def _extract_order_number(description: str) -> str | None:
    """Extract Amazon order number from Chase description if present."""
    match = ORDER_NUMBER_RE.search(description)
    if match:
        return match.group(1)
    match = DIGITAL_ORDER_RE.search(description)
    if match:
        return match.group(1)
    return None


def _make_source_id(row: dict) -> str:
    """Generate a deterministic dedup key from a CSV row."""
    raw = f"{row['Transaction Date']}|{row['Description']}|{row['Amount']}"
    return f"chase-csv-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_chase_csv(path: Path) -> list[ParsedTransaction]:
    """Parse a Chase credit card CSV export into transactions.

    Chase CSVs use negative amounts for purchases and positive for
    payments/credits. This parser flips the sign so expenses are positive,
    matching the spec convention.
    """
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount = float(row["Amount"])

            # Skip payments and credits (positive in Chase = payment to card)
            if amount > 0:
                continue

            # Flip sign: Chase negative purchase -> our positive expense
            amount = -amount

            txn_date = datetime.strptime(
                row["Transaction Date"], "%m/%d/%Y"
            ).date()

            description = row["Description"]

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=_normalize_merchant(description),
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Chase Prime Visa",
                    order_number=_extract_order_number(description),
                )
            )

    return transactions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_chase_parser.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/cashflow/models.py src/cashflow/parsers/ tests/test_chase_parser.py
git commit -m "feat: Chase Prime Visa CSV parser with order number extraction"
```

---

### Task 6: Ingest Command — Store Parsed Transactions

**Files:**
- Create: `tests/test_ingest.py`
- Modify: `src/cashflow/cli.py`
- Modify: `src/cashflow/db.py` (add `store_transactions` function)

- [ ] **Step 1: Write failing tests for transaction storage**

```python
# tests/test_ingest.py
from datetime import date
from cashflow.models import ParsedTransaction
from cashflow.db import store_transactions
from cashflow.seed import seed_all


def _make_txn(**overrides) -> ParsedTransaction:
    defaults = dict(
        date=date(2026, 1, 15),
        amount=42.99,
        description="AMAZON MKTPL*TEST Amzn.com/bill WA",
        merchant="Amazon Marketplace",
        source_id="chase-csv-abc123",
        source_type="csv",
        account_name="Chase Prime Visa",
        order_number="113-1234567-8901234",
    )
    defaults.update(overrides)
    return ParsedTransaction(**defaults)


def test_store_transactions_inserts_rows(db):
    seed_all(db)
    txns = [_make_txn(), _make_txn(source_id="chase-csv-def456", amount=10.0)]
    stored = store_transactions(db, txns)
    assert stored == 2
    rows = db.execute("SELECT * FROM transactions").fetchall()
    assert len(rows) == 2


def test_store_transactions_resolves_account_id(db):
    seed_all(db)
    store_transactions(db, [_make_txn()])
    row = db.execute("SELECT account_id FROM transactions").fetchone()
    acct = db.execute(
        "SELECT name FROM accounts WHERE id = ?", (row["account_id"],)
    ).fetchone()
    assert acct["name"] == "Chase Prime Visa"


def test_store_transactions_skips_duplicates(db):
    seed_all(db)
    txns = [_make_txn()]
    store_transactions(db, txns)
    # Ingest same transaction again
    stored = store_transactions(db, txns)
    assert stored == 0
    rows = db.execute("SELECT * FROM transactions").fetchall()
    assert len(rows) == 1


def test_store_transactions_sets_pending_status(db):
    seed_all(db)
    store_transactions(db, [_make_txn()])
    row = db.execute("SELECT status FROM transactions").fetchone()
    assert row["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: FAIL — `ImportError: cannot import name 'store_transactions'`

- [ ] **Step 3: Add store_transactions to db.py**

Add to the bottom of `src/cashflow/db.py`:

```python
from cashflow.models import ParsedTransaction


def store_transactions(
    conn: sqlite3.Connection, txns: list[ParsedTransaction]
) -> int:
    """Store parsed transactions. Returns count of newly inserted rows.

    Skips duplicates (same source_id). Resolves account_name to account_id.
    """
    # Build account name -> id lookup
    accounts = {
        row["name"]: row["id"]
        for row in conn.execute("SELECT id, name FROM accounts").fetchall()
    }

    inserted = 0
    for txn in txns:
        account_id = accounts.get(txn.account_name)
        if account_id is None:
            continue  # Unknown account, skip

        try:
            conn.execute(
                "INSERT INTO transactions "
                "(source_id, date, amount, description, merchant, account_id, "
                "status, confidence, who, source_type) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 'shared', ?)",
                (
                    txn.source_id,
                    txn.date.isoformat(),
                    txn.amount,
                    txn.description,
                    txn.merchant,
                    account_id,
                    txn.source_type,
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # Duplicate source_id, skip

    conn.commit()
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Wire up the `cashflow ingest --files` CLI command**

Replace `src/cashflow/cli.py`:

```python
# src/cashflow/cli.py
import click
from pathlib import Path

from cashflow.db import get_connection, store_transactions
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv


@click.group()
def cli():
    """Household financial dashboard."""
    pass


@cli.command()
@click.option("--files", type=click.Path(exists=True), help="Path to CSV/PDF inbox directory or file.")
@click.option("--email", is_flag=True, help="Poll Gmail for new emails. (Not yet implemented.)")
@click.option("--auto", is_flag=True, help="Run both email and file ingestion.")
def ingest(files, email, auto):
    """Ingest transactions from CSV files or email."""
    conn = get_connection()
    seed_all(conn)

    if email or auto:
        click.echo("Email ingestion not yet implemented.")

    if not files and not auto:
        click.echo("No source specified. Use --files PATH or --email.")
        return

    path = Path(files) if files else None
    if path is None:
        return

    total = 0
    csv_files = [path] if path.is_file() else sorted(path.glob("*.csv"))

    for csv_file in csv_files:
        click.echo(f"Parsing {csv_file.name}...")
        if "chase" in csv_file.name.lower():
            txns = parse_chase_csv(csv_file)
        else:
            click.echo(f"  Skipped — no parser for {csv_file.name}")
            continue

        stored = store_transactions(conn, txns)
        click.echo(f"  {stored} new transactions ({len(txns) - stored} duplicates skipped)")
        total += stored

    click.echo(f"\nDone. {total} transactions ingested.")
    conn.close()
```

- [ ] **Step 6: Manual smoke test with real data**

Run: `cashflow ingest --files ~/Downloads/amazon-chase/`
Expected: Should show "no parser" for PDFs and txt files, but attempt to parse any .csv if present. If there are no CSVs in that directory, test with the fixture:
Run: `cashflow ingest --files tests/fixtures/chase_sample.csv`
Expected: Shows "Parsing chase_sample.csv... 6 new transactions (0 duplicates skipped)"

- [ ] **Step 7: Commit**

```bash
git add src/cashflow/cli.py src/cashflow/db.py tests/test_ingest.py
git commit -m "feat: cashflow ingest --files command for Chase CSV ingestion"
```

---

## Chunk 3: Status Queries + CLI

### Task 7: Status Queries

**Files:**
- Create: `src/cashflow/queries.py`
- Create: `tests/test_queries.py`

- [ ] **Step 1: Write failing tests for status queries**

```python
# tests/test_queries.py
from datetime import date
from cashflow.seed import seed_all
from cashflow.queries import (
    get_month_spending,
    get_ytd_surplus,
    get_review_queue_count,
    get_goal,
)


def _insert_txn(db, amount, txn_date, status="confirmed"):
    """Helper to insert a transaction directly."""
    db.execute(
        "INSERT INTO transactions "
        "(source_id, date, amount, description, merchant, account_id, "
        "status, confidence, who, source_type) "
        "VALUES (?, ?, ?, 'test', 'test', 1, ?, 100, 'shared', 'csv')",
        (f"test-{txn_date}-{amount}", txn_date, amount, status),
    )
    db.commit()


def _insert_income(db, amount, inc_date):
    db.execute(
        "INSERT INTO income (source_id, date, amount, source) VALUES (?, ?, ?, 'fei_paycheck')",
        (f"income-{inc_date}-{amount}", inc_date, amount),
    )
    db.commit()


def test_get_month_spending(db):
    seed_all(db)
    _insert_txn(db, 1000.0, "2026-03-01")
    _insert_txn(db, 500.0, "2026-03-15")
    _insert_txn(db, 200.0, "2026-02-28")  # Different month, excluded
    total = get_month_spending(db, 2026, 3)
    assert total == 1500.0


def test_get_month_spending_excludes_linked_duplicates(db):
    seed_all(db)
    _insert_txn(db, 100.0, "2026-03-01")
    # Insert a duplicate linked via canonical_id
    db.execute(
        "INSERT INTO transactions "
        "(source_id, canonical_id, date, amount, description, merchant, account_id, "
        "status, confidence, who, source_type) "
        "VALUES ('dup-1', 1, '2026-03-01', 100.0, 'test', 'test', 1, "
        "'confirmed', 100, 'shared', 'email')"
    )
    db.commit()
    total = get_month_spending(db, 2026, 3)
    assert total == 100.0  # Not 200


def test_get_ytd_surplus(db):
    seed_all(db)
    _insert_income(db, 15000.0, "2026-01-15")
    _insert_income(db, 15000.0, "2026-02-15")
    _insert_txn(db, 10000.0, "2026-01-15")
    _insert_txn(db, 11000.0, "2026-02-15")
    surplus = get_ytd_surplus(db, 2026)
    assert surplus == 9000.0  # 30000 income - 21000 expenses


def test_get_review_queue_count(db):
    seed_all(db)
    _insert_txn(db, 50.0, "2026-03-01", status="pending")
    _insert_txn(db, 75.0, "2026-03-02", status="pending")
    _insert_txn(db, 100.0, "2026-03-03", status="confirmed")
    count = get_review_queue_count(db)
    assert count == 2


def test_get_goal(db):
    seed_all(db)
    ceiling = get_goal(db, "ceiling")
    assert ceiling is not None
    assert ceiling["amount"] == 12000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_queries.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement queries.py**

```python
# src/cashflow/queries.py
import sqlite3
from typing import Optional


def get_month_spending(conn: sqlite3.Connection, year: int, month: int) -> float:
    """Total spending for a given month, excluding linked duplicates."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM transactions "
        "WHERE canonical_id IS NULL "
        "AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
        (str(year), f"{month:02d}"),
    ).fetchone()
    return row["total"]


def get_ytd_spending(conn: sqlite3.Connection, year: int) -> float:
    """Total spending year-to-date, excluding linked duplicates."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM transactions "
        "WHERE canonical_id IS NULL AND strftime('%Y', date) = ?",
        (str(year),),
    ).fetchone()
    return row["total"]


def get_ytd_income(conn: sqlite3.Connection, year: int) -> float:
    """Total income year-to-date."""
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM income "
        "WHERE strftime('%Y', date) = ?",
        (str(year),),
    ).fetchone()
    return row["total"]


def get_ytd_surplus(conn: sqlite3.Connection, year: int) -> float:
    """YTD surplus = income - spending."""
    return get_ytd_income(conn, year) - get_ytd_spending(conn, year)


def get_review_queue_count(conn: sqlite3.Connection) -> int:
    """Count of transactions pending review."""
    row = conn.execute(
        "SELECT COUNT(*) as c FROM transactions "
        "WHERE canonical_id IS NULL AND status = 'pending'"
    ).fetchone()
    return row["c"]


def get_goal(
    conn: sqlite3.Connection, goal_type: str
) -> Optional[sqlite3.Row]:
    """Fetch a goal by type."""
    return conn.execute(
        "SELECT * FROM goals WHERE type = ?", (goal_type,)
    ).fetchone()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_queries.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/queries.py tests/test_queries.py
git commit -m "feat: status queries for month spending, YTD surplus, review queue"
```

---

### Task 8: Status CLI Command

**Files:**
- Modify: `src/cashflow/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing test for status command**

```python
# tests/test_cli.py
from click.testing import CliRunner
from cashflow.cli import cli


def test_status_command_runs(tmp_path):
    """Status command should run and show ceiling + surplus info."""
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "ceiling" in result.output.lower() or "$" in result.output


def test_ingest_then_status(tmp_path):
    """Ingest a CSV then check status reflects the data."""
    from pathlib import Path

    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()

    # Ingest
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--files", str(fixture)]
    )
    assert result.exit_code == 0
    assert "new transactions" in result.output

    # Status
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "$" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — status command doesn't exist yet

- [ ] **Step 3: Add --db option to CLI group and status command**

Update `src/cashflow/cli.py` — add a `--db` option to the group so all commands can share it, and add the `status` command:

```python
# src/cashflow/cli.py
import click
from datetime import date
from pathlib import Path

from cashflow.db import get_connection, store_transactions
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv
from cashflow.queries import (
    get_month_spending,
    get_ytd_surplus,
    get_review_queue_count,
    get_goal,
)


@click.group()
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    help="Path to SQLite database (default: ~/.cashflow/cashflow.db).",
)
@click.pass_context
def cli(ctx, db):
    """Household financial dashboard."""
    ctx.ensure_object(dict)
    db_path = Path(db) if db else None
    conn = get_connection(db_path) if db_path else get_connection()
    seed_all(conn)
    ctx.obj["conn"] = conn


@cli.command()
@click.option("--files", type=click.Path(exists=True), help="Path to CSV inbox directory or file.")
@click.option("--email", is_flag=True, help="Poll Gmail for new emails. (Not yet implemented.)")
@click.option("--auto", is_flag=True, help="Run both email and file ingestion.")
@click.pass_context
def ingest(ctx, files, email, auto):
    """Ingest transactions from CSV files or email."""
    conn = ctx.obj["conn"]

    if email or auto:
        click.echo("Email ingestion not yet implemented.")

    if not files and not auto:
        click.echo("No source specified. Use --files PATH or --email.")
        return

    path = Path(files) if files else None
    if path is None:
        return

    total = 0
    csv_files = [path] if path.is_file() else sorted(path.glob("*.csv"))

    for csv_file in csv_files:
        click.echo(f"Parsing {csv_file.name}...")
        if "chase" in csv_file.name.lower():
            txns = parse_chase_csv(csv_file)
        else:
            click.echo(f"  Skipped — no parser for {csv_file.name}")
            continue

        stored = store_transactions(conn, txns)
        click.echo(f"  {stored} new transactions ({len(txns) - stored} duplicates skipped)")
        total += stored

    click.echo(f"\nDone. {total} transactions ingested.")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current month burn rate and YTD surplus."""
    conn = ctx.obj["conn"]
    today = date.today()
    year, month = today.year, today.month

    spending = get_month_spending(conn, year, month)
    ceiling = get_goal(conn, "ceiling")
    ceiling_amt = ceiling["amount"] if ceiling else 12000.0

    days_in_month = (date(year, month % 12 + 1, 1) - date(year, month, 1)).days if month < 12 else 31
    days_left = days_in_month - today.day
    pct = (spending / ceiling_amt * 100) if ceiling_amt > 0 else 0

    # Color: green if under 80%, yellow 80-95%, red over 95%
    if pct < 80:
        color = "green"
    elif pct < 95:
        color = "yellow"
    else:
        color = "red"

    month_name = today.strftime("%B %Y")
    click.secho(
        f"{month_name}: ${spending:,.0f} / ${ceiling_amt:,.0f} ceiling "
        f"({pct:.0f}%) — {days_left} days left",
        fg=color,
    )

    surplus = get_ytd_surplus(conn, year)
    surplus_goal = get_goal(conn, "surplus")
    surplus_amt = surplus_goal["amount"] if surplus_goal else 40000.0

    months_elapsed = month
    pace = (surplus / months_elapsed * 12) if months_elapsed > 0 else 0
    surplus_pct = (surplus / surplus_amt * 100) if surplus_amt > 0 else 0

    click.secho(
        f"YTD surplus: ${surplus:,.0f} / ${surplus_amt:,.0f} goal "
        f"({surplus_pct:.0f}%) — on pace for ${pace:,.0f}",
        fg="green" if surplus_pct >= (months_elapsed / 12 * 100) else "yellow",
    )

    queue = get_review_queue_count(conn)
    if queue > 0:
        click.secho(f"Review queue: {queue} items", fg="yellow")
    else:
        click.secho("Review queue: empty", fg="green")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass (should be ~19 tests total)

- [ ] **Step 6: Manual end-to-end test**

```bash
cashflow ingest --files tests/fixtures/chase_sample.csv
cashflow status
```

Expected output similar to:
```
March 2026: $0 / $12,000 ceiling (0%) — 16 days left
YTD surplus: $-371 / $40,000 goal (-1%) — on pace for $-1,484
Review queue: 6 items
```

(Surplus is negative because there's no income data yet — only expenses from the fixture. The fixture transactions are from Dec 2025 so they won't show in March spending. This is correct behavior.)

- [ ] **Step 7: Commit**

```bash
git add src/cashflow/cli.py tests/test_cli.py
git commit -m "feat: cashflow status command showing burn rate and surplus"
```

---

## Summary

After completing Plan 1, you have:
- A working `cashflow` CLI installed on your system
- SQLite database with all 9 tables from the spec
- Seed data: 40+ categories, 6 accounts, 2 goals
- Chase Prime Visa CSV parser with order number extraction
- `cashflow ingest --files` to load real statement data
- `cashflow status` showing monthly burn rate, YTD surplus, review queue count
- 19+ automated tests covering schema, seeds, parsing, storage, and queries

**Next:** Plan 2 adds the categorization engine (merchant rules + LLM) and `cashflow review`.
