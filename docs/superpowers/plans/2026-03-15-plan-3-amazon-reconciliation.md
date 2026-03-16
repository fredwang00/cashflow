# Plan 3: Amazon Orders Parser + Reconciliation Engine

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse Amazon order screen scrapes into the `amazon_items` table, then reconcile them with Chase transactions via order number matching. This cracks the Amazon black box — every opaque Chase line item like "AMAZON MKTPL*B80X61JB1" gets linked to real product names.

**Architecture:** A text parser extracts structured order data (date, total, order number, item names, Subscribe & Save status) from Amazon's "Your Orders" page scrapes. A reconciliation engine matches `amazon_items` to existing `transactions` via order number. Matched transactions get enriched with item-level detail and per-item categorization.

**Tech Stack:** Python 3.12+, Click, SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-03-14-cashflow-design.md` — sections "Amazon Reports Channel", "Reconciliation Engine"

**Depends on:** Plan 2 (complete — 45 tests passing)

---

## New Files

```
src/cashflow/
├── parsers/
│   └── amazon.py             # Amazon order screen scrape parser
├── reconcile.py              # Order number matching engine
└── (cli.py modified)         # Hook reconciliation into ingest

tests/
├── test_amazon_parser.py     # Screen scrape parsing tests
├── test_reconcile.py         # Order number matching tests
└── fixtures/
    └── amazon_orders_sample.txt  # Minimal Amazon scrape fixture
```

---

## Chunk 1: Amazon Orders Parser

### Task 1: Amazon Orders Test Fixture

**Files:**
- Create: `tests/fixtures/amazon_orders_sample.txt`

The fixture must match the real format from `~/Downloads/amazon-chase/fred-amazon-orders.txt`. Key patterns:
- `Order placed` followed by date on next line
- `Total` followed by `$amount` on next line
- `Ship to` / `Ordered by` markers
- `Order # NNN-NNNNNNN-NNNNNNN`
- Item names appear as duplicate lines (display name + accessible name)
- `Auto-delivered: Every N months` marks Subscribe & Save
- `$0.00` total for items paid by gift card or Subscribe & Save credits
- `Cancelled` orders should be skipped
- Multi-item orders have multiple item name pairs before the next `Order placed`

- [ ] **Step 1: Create minimal fixture**

```text
Your Orders
Search all orders
Search Orders
Orders Buy Again Not Yet Shipped Digital Orders Amazon Pay
48 orders placed in
2026
2026
Order placed
March 10, 2026
Total
$38.16
Ship to
Fred Wang
Order # 114-1572664-8121843
View order details  View invoice
Arriving March 26
Blueprint Bryan Johnson Creatine Monohydrate Powder – Amino Acid Powder - Supplement Supports Muscle Growth, Recovery, Strength & Focus – Unflavored Creatine for Women & Men – 5g Dose – 100 Servings
Blueprint Bryan Johnson Creatine Monohydrate Powder - Amino Acid Powder - Supplement Supports Muscle Growth, Recovery, Strength & Focus - Unflavored Creatine for Women & Men - 5g Dose - 100 Servings
Auto-delivered: Every 3 months
Buy it again
Track package
View or edit order
View your Subscribe & Save
Ask Product Question
Write a product review
Order placed
March 9, 2026
Total
$0.00
Ship to
Fred Wang
Order # 113-0558577-8378621
View order details  View invoice
Delivered March 12
Your package was left near the front door or porch.
for Ninja Creami Pints and Lids-4 Pack, 16OZ Container Compatible with NC299AMZ & NC300s Series Ice Cream Makers, Extra Cups Replacement for Ninja Creamy Containers Airtight Anti-slip Dishwasher Safe
for Ninja Creami Pints and Lids-4 Pack, 16OZ Container Compatible with NC299AMZ & NC300s Series Ice Cream Makers, Extra Cups Replacement for Ninja Creamy Containers Airtight Anti-slip Dishwasher Safe
Return or replace items: Eligible through April 11, 2026
Buy it again

View your item
Track package
Return or replace items
Share gift receipt
Ask Product Question
Leave seller feedback
Write a product review
Order placed
February 12, 2026
Total
$44.52
Ship to
Fred Wang
Order # 113-3593273-0513822
View order details  View invoice
Delivered February 15
Your package was left near the front door or porch.
tarte face tape foundation – Full-Coverage Waterproof Makeup, Hydrating & Smoothing, Natural Matte Finish for Transfer-Proof Comfortable Long-Wear Foundation, Vegan & Cruelty-Free, full size, 59S
tarte face tape foundation – Full-Coverage Waterproof Makeup, Hydrating & Smoothing, Natural Matte Finish for Transfer-Proof Comfortable Long-Wear Foundation, Vegan & Cruelty-Free, full size, 59S
Return or replace items: Eligible through March 17, 2026
Buy it again

View your item
BS-MALL Makeup Brush Set 18 Pcs Premium Synthetic Foundation Powder Concealers Eye shadows Blush Makeup Brushes with black case
BS-MALL Makeup Brush Set 18 Pcs Premium Synthetic Foundation Powder Concealers Eye shadows Blush Makeup Brushes with black case
Return or replace items: Eligible through March 17, 2026
Buy it again

View your item
Track package
Return or replace items
Share gift receipt
Leave seller feedback
Write a product review
Order placed
February 13, 2026
Order # 112-2408383-4562623
Cancelled
Your order was cancelled. You have not been charged for this order.
Sports Research Zinc Picolinate 50mg with Organic Coconut Oil | Highly Absorbable Zinc Supplement for Healthy Immune Function - Non-GMO Verified, Gluten & Soy Free (60 Liquid Softgels)
Sports Research Zinc Picolinate 50mg with Organic Coconut Oil | Highly Absorbable Zinc Supplement for Healthy Immune Function - Non-GMO Verified, Gluten & Soy Free (60 Liquid Softgels)
Order placed
March 10, 2026
Total
$7.72
Ship to
Fred Wang
Ordered by
Fred
Order # 111-4848743-5209032
View order details  View invoice
Arriving March 26
Harney & Sons Black Earl Grey Loose Leaf Tea, 4 Ounce
Harney & Sons Black Earl Grey Loose Leaf Tea, 4 Ounce
Auto-delivered: Every 3 months
Buy it again
Track package
View or edit order
View your Subscribe & Save
Write a product review
```

This fixture covers: single-item order, $0 order, multi-item order, cancelled order, Subscribe & Save, "Ordered by Fred" (wife's account).

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/amazon_orders_sample.txt
git commit -m "test: add Amazon order screen scrape fixture"
```

---

### Task 2: Amazon Orders Parser

**Files:**
- Create: `src/cashflow/parsers/amazon.py`
- Create: `tests/test_amazon_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_amazon_parser.py
from pathlib import Path
from cashflow.parsers.amazon import parse_amazon_orders

FIXTURE = Path(__file__).parent / "fixtures" / "amazon_orders_sample.txt"


def test_parse_amazon_orders_returns_orders():
    orders = parse_amazon_orders(FIXTURE)
    assert len(orders) > 0


def test_parse_amazon_orders_skips_cancelled():
    orders = parse_amazon_orders(FIXTURE)
    order_numbers = [o.order_number for o in orders]
    assert "112-2408383-4562623" not in order_numbers


def test_parse_amazon_orders_extracts_order_number():
    orders = parse_amazon_orders(FIXTURE)
    assert any(o.order_number == "114-1572664-8121843" for o in orders)


def test_parse_amazon_orders_extracts_total():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.total == 38.16


def test_parse_amazon_orders_extracts_date():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert str(creatine.order_date) == "2026-03-10"


def test_parse_amazon_orders_extracts_items():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert len(creatine.items) == 1
    assert "Creatine" in creatine.items[0].name


def test_parse_amazon_orders_multi_item():
    orders = parse_amazon_orders(FIXTURE)
    makeup = [o for o in orders if o.order_number == "113-3593273-0513822"][0]
    assert len(makeup.items) == 2
    names = [i.name for i in makeup.items]
    assert any("tarte" in n for n in names)
    assert any("BS-MALL" in n for n in names)


def test_parse_amazon_orders_detects_subscribe_save():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.items[0].is_subscribe_save is True
    assert creatine.items[0].delivery_frequency == "Every 3 months"


def test_parse_amazon_orders_non_subscribe_save():
    orders = parse_amazon_orders(FIXTURE)
    makeup = [o for o in orders if o.order_number == "113-3593273-0513822"][0]
    assert makeup.items[0].is_subscribe_save is False


def test_parse_amazon_orders_detects_wife_account():
    orders = parse_amazon_orders(FIXTURE)
    tea = [o for o in orders if o.order_number == "111-4848743-5209032"][0]
    assert tea.account == "wife"


def test_parse_amazon_orders_defaults_to_fred():
    orders = parse_amazon_orders(FIXTURE)
    creatine = [o for o in orders if o.order_number == "114-1572664-8121843"][0]
    assert creatine.account == "fred"


def test_parse_amazon_orders_includes_zero_total():
    """$0 orders (gift card, S&S credit) should still be parsed."""
    orders = parse_amazon_orders(FIXTURE)
    ninja = [o for o in orders if o.order_number == "113-0558577-8378621"][0]
    assert ninja.total == 0.0
    assert len(ninja.items) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_amazon_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Amazon orders parser**

```python
# src/cashflow/parsers/amazon.py
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class AmazonItem:
    name: str
    is_subscribe_save: bool = False
    delivery_frequency: str | None = None


@dataclass
class AmazonOrder:
    order_number: str
    order_date: 'datetime.date'
    total: float
    account: str  # "fred" or "wife"
    items: list[AmazonItem] = field(default_factory=list)


ORDER_NUMBER_RE = re.compile(r"Order #\s*(\d{3}-\d{7}-\d{7})")
TOTAL_RE = re.compile(r"^\$[\d,]+\.\d{2}$")
DATE_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}$")
AUTO_DELIVERED_RE = re.compile(r"Auto-delivered:\s+(.+)")

# Lines that are UI chrome, not item names
SKIP_PATTERNS = [
    "Buy it again", "Track package", "View or edit order",
    "View your Subscribe & Save", "Ask Product Question",
    "Write a product review", "Leave seller feedback",
    "Return or replace items", "View your item",
    "Share gift receipt", "Get product support",
    "View order details", "Add a protection plan",
    "Replace item",
]

SKIP_PREFIXES = [
    "Your package was", "Delivered ", "Arriving ", "Now arriving ",
    "Previously expected", "Return or replace items:",
    "Return items:", "Return window closed",
    "Return eligibility", "Purchased at",
    "The brand image", "Applied",
    "Gift Card balance",
]


def _is_ui_chrome(line: str) -> bool:
    """Check if a line is UI navigation/chrome rather than an item name."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in SKIP_PATTERNS:
        return True
    for prefix in SKIP_PREFIXES:
        if stripped.startswith(prefix):
            return True
    if ORDER_NUMBER_RE.match(stripped):
        return True
    if TOTAL_RE.match(stripped):
        return True
    if DATE_RE.match(stripped):
        return True
    if AUTO_DELIVERED_RE.match(stripped):
        return True
    if stripped in ("Order placed", "Total", "Ship to", "Cancelled",
                    "Your Orders", "Search all orders", "Search Orders",
                    "Orders Buy Again Not Yet Shipped Digital Orders Amazon Pay",
                    "Ordered by", "Fred", "PICKUP AT"):
        return True
    if re.match(r"^\d+ orders placed in\s*$", stripped):
        return True
    if re.match(r"^\d{4}$", stripped):
        return True
    if stripped.startswith("Fred Wang") or stripped.startswith("Virginia Beach"):
        return True
    if stripped == "--":
        return True
    return False


def parse_amazon_orders(path: Path, default_account: str = "fred") -> list[AmazonOrder]:
    """Parse an Amazon 'Your Orders' screen scrape into structured orders.

    Skips cancelled orders. Detects Subscribe & Save and wife's account
    (via 'Ordered by' marker with 111- order prefix convention).
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    orders = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Look for "Order placed" marker
        if line != "Order placed":
            i += 1
            continue

        # Next line should be date
        i += 1
        if i >= len(lines):
            break
        date_str = lines[i].strip()
        date_match = DATE_RE.match(date_str)
        if not date_match:
            continue
        order_date = datetime.strptime(date_str, "%B %d, %Y").date()
        i += 1

        # Scan ahead for order number, total, cancelled status, items
        total = 0.0
        order_number = None
        is_cancelled = False
        account = default_account
        items = []
        seen_item_names = set()
        current_subscribe_save = None

        # Scan until next "Order placed" or end of file
        while i < len(lines):
            scan_line = lines[i].strip()

            if scan_line == "Order placed":
                break

            if scan_line == "--":
                i += 1
                break

            # Total
            if TOTAL_RE.match(scan_line):
                total = float(scan_line.replace("$", "").replace(",", ""))
                i += 1
                continue

            # Order number
            order_match = ORDER_NUMBER_RE.match(scan_line)
            if order_match:
                order_number = order_match.group(1)
                i += 1
                continue

            # Cancelled
            if scan_line == "Cancelled":
                is_cancelled = True
                i += 1
                continue

            # Ordered by Fred = wife's account (uses 111- prefix orders)
            if scan_line == "Ordered by":
                account = "wife"
                i += 1
                continue

            # Subscribe & Save detection
            auto_match = AUTO_DELIVERED_RE.match(scan_line)
            if auto_match:
                current_subscribe_save = auto_match.group(1)
                # Apply to the most recent item
                if items:
                    items[-1].is_subscribe_save = True
                    items[-1].delivery_frequency = current_subscribe_save
                i += 1
                continue

            # Item name detection: non-chrome lines that appear as duplicates
            if not _is_ui_chrome(scan_line) and scan_line not in seen_item_names:
                seen_item_names.add(scan_line)
                items.append(AmazonItem(name=scan_line))
                current_subscribe_save = None
            elif scan_line in seen_item_names:
                # Duplicate line (accessible name) — skip
                pass

            i += 1

        if order_number and not is_cancelled:
            orders.append(AmazonOrder(
                order_number=order_number,
                order_date=order_date,
                total=total,
                account=account,
                items=items,
            ))

    return orders
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_amazon_parser.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/parsers/amazon.py tests/test_amazon_parser.py
git commit -m "feat: Amazon order screen scrape parser with S&S and multi-item support"
```

---

## Chunk 2: Reconciliation Engine

### Task 3: Store Amazon Items + Reconcile with Transactions

**Files:**
- Create: `src/cashflow/reconcile.py`
- Create: `tests/test_reconcile.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_reconcile.py
from datetime import date
from cashflow.seed import seed_all
from cashflow.parsers.amazon import AmazonOrder, AmazonItem
from cashflow.reconcile import store_amazon_orders, reconcile_amazon


def _insert_chase_txn(db, source_id, order_number, amount, txn_date="2026-03-10"):
    """Insert a Chase transaction with an Amazon order number in the description."""
    desc = f"AMAZON MKTPL*TEST Amzn.com/bill WA Order Number {order_number}"
    db.execute(
        "INSERT INTO transactions "
        "(source_id, date, amount, description, merchant, account_id, "
        "status, confidence, who, source_type) "
        "VALUES (?, ?, ?, ?, 'Amazon Marketplace', 1, 'pending', 0, 'shared', 'csv')",
        (source_id, txn_date, amount, desc),
    )
    db.commit()


def test_store_amazon_orders_inserts_items(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder", is_subscribe_save=True, delivery_frequency="Every 3 months")],
        ),
    ]
    stored = store_amazon_orders(db, orders)
    assert stored == 1
    row = db.execute("SELECT * FROM amazon_items").fetchone()
    assert row["order_number"] == "114-1572664-8121843"
    assert row["item_name"] == "Creatine Powder"
    assert row["is_subscribe_save"] == 1
    assert row["delivery_frequency"] == "Every 3 months"
    assert row["account"] == "fred"


def test_store_amazon_orders_skips_duplicates(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)
    stored = store_amazon_orders(db, orders)
    assert stored == 0


def test_store_amazon_orders_multi_item(db):
    seed_all(db)
    orders = [
        AmazonOrder(
            order_number="113-3593273-0513822",
            order_date=date(2026, 2, 12),
            total=44.52,
            account="fred",
            items=[
                AmazonItem(name="tarte face tape foundation"),
                AmazonItem(name="BS-MALL Makeup Brush Set"),
            ],
        ),
    ]
    store_amazon_orders(db, orders)
    rows = db.execute(
        "SELECT * FROM amazon_items WHERE order_number = '113-3593273-0513822'"
    ).fetchall()
    assert len(rows) == 2


def test_reconcile_matches_by_order_number(db):
    seed_all(db)
    # Insert a Chase transaction
    _insert_chase_txn(db, "chase-1", "114-1572664-8121843", 38.16)
    # Insert Amazon items
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)

    matched = reconcile_amazon(db)
    assert matched == 1

    # Amazon item should now be linked to the transaction
    item = db.execute("SELECT * FROM amazon_items WHERE order_number = '114-1572664-8121843'").fetchone()
    assert item["transaction_id"] is not None
    txn = db.execute("SELECT * FROM transactions WHERE id = ?", (item["transaction_id"],)).fetchone()
    assert txn["source_id"] == "chase-1"


def test_reconcile_skips_already_linked(db):
    seed_all(db)
    _insert_chase_txn(db, "chase-1", "114-1572664-8121843", 38.16)
    orders = [
        AmazonOrder(
            order_number="114-1572664-8121843",
            order_date=date(2026, 3, 10),
            total=38.16,
            account="fred",
            items=[AmazonItem(name="Creatine Powder")],
        ),
    ]
    store_amazon_orders(db, orders)
    reconcile_amazon(db)
    # Run again — should not double-match
    matched = reconcile_amazon(db)
    assert matched == 0


def test_reconcile_unmatched_items_stay_null(db):
    seed_all(db)
    # Amazon items with no matching Chase transaction
    orders = [
        AmazonOrder(
            order_number="999-0000000-0000000",
            order_date=date(2026, 3, 10),
            total=25.00,
            account="fred",
            items=[AmazonItem(name="Mystery Item")],
        ),
    ]
    store_amazon_orders(db, orders)
    matched = reconcile_amazon(db)
    assert matched == 0
    item = db.execute("SELECT * FROM amazon_items WHERE order_number = '999-0000000-0000000'").fetchone()
    assert item["transaction_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement reconciliation**

```python
# src/cashflow/reconcile.py
import re
import sqlite3
from cashflow.parsers.amazon import AmazonOrder

ORDER_NUMBER_RE = re.compile(r"(\d{3}-\d{7}-\d{7})")
DIGITAL_ORDER_RE = re.compile(r"(D\d{2}-\d{7}-\d{7})")


def store_amazon_orders(conn: sqlite3.Connection, orders: list[AmazonOrder]) -> int:
    """Store parsed Amazon orders as amazon_items rows.

    Returns count of newly stored items. Skips duplicates
    (same order_number + item_name combination).
    """
    inserted = 0
    for order in orders:
        for item in order.items:
            # Check for existing item with same order + name
            existing = conn.execute(
                "SELECT id FROM amazon_items WHERE order_number = ? AND item_name = ?",
                (order.order_number, item.name),
            ).fetchone()
            if existing:
                continue

            conn.execute(
                "INSERT INTO amazon_items "
                "(order_number, item_name, price, order_date, account, "
                "is_subscribe_save, delivery_frequency) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    order.order_number,
                    item.name,
                    order.total if len(order.items) == 1 else 0.0,
                    order.order_date.isoformat(),
                    order.account,
                    item.is_subscribe_save,
                    item.delivery_frequency,
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def reconcile_amazon(conn: sqlite3.Connection) -> int:
    """Match unlinked amazon_items to transactions via order number.

    Scans transaction descriptions for order numbers and links matching
    amazon_items by setting their transaction_id.

    Returns count of newly matched items.
    """
    # Get all unlinked Amazon items
    unlinked = conn.execute(
        "SELECT id, order_number FROM amazon_items WHERE transaction_id IS NULL"
    ).fetchall()

    if not unlinked:
        return 0

    # Build order_number -> [item_ids] lookup
    order_items: dict[str, list[int]] = {}
    for item in unlinked:
        order_items.setdefault(item["order_number"], []).append(item["id"])

    # Scan transactions for order numbers in descriptions
    transactions = conn.execute(
        "SELECT id, description FROM transactions WHERE canonical_id IS NULL"
    ).fetchall()

    matched = 0
    for txn in transactions:
        # Extract order number from Chase description
        match = ORDER_NUMBER_RE.search(txn["description"])
        if not match:
            match = DIGITAL_ORDER_RE.search(txn["description"])
        if not match:
            continue

        order_num = match.group(1)
        item_ids = order_items.get(order_num)
        if not item_ids:
            continue

        # Link all items for this order to this transaction
        for item_id in item_ids:
            conn.execute(
                "UPDATE amazon_items SET transaction_id = ? WHERE id = ?",
                (txn["id"], item_id),
            )
            matched += 1

        # Remove from lookup so we don't double-match
        del order_items[order_num]

    conn.commit()
    return matched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reconcile.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/reconcile.py tests/test_reconcile.py
git commit -m "feat: Amazon order storage and order-number reconciliation engine"
```

---

## Chunk 3: Wire into CLI + End-to-End

### Task 4: Add Amazon Ingestion to CLI

**Files:**
- Modify: `src/cashflow/cli.py`
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Update ingest command to handle Amazon order files**

Add imports to top of `src/cashflow/cli.py`:
```python
from cashflow.parsers.amazon import parse_amazon_orders
from cashflow.reconcile import store_amazon_orders, reconcile_amazon
```

In the `ingest` function's CSV processing loop, add an `elif` branch for Amazon files after the chase branch:

```python
        elif "amazon" in csv_file.name.lower():
            orders = parse_amazon_orders(csv_file)
            items_stored = store_amazon_orders(conn, orders)
            click.echo(f"  {items_stored} new Amazon items from {len(orders)} orders")
            total += items_stored
            continue
```

Also update the glob to include `.txt` files. Change:
```python
    csv_files = [path] if path.is_file() else sorted(path.glob("*.csv"))
```
to:
```python
    if path.is_file():
        csv_files = [path]
    else:
        csv_files = sorted(path.glob("*.csv")) + sorted(path.glob("*.txt"))
```

After the categorization block (at the very end of `ingest`, after the LLM try/except), add reconciliation:

```python
    # Reconcile Amazon items with transactions
    matched = reconcile_amazon(conn)
    if matched > 0:
        click.echo(f"  Reconciled: {matched} Amazon items linked to transactions")
```

- [ ] **Step 2: Write end-to-end test**

```python
# tests/test_e2e.py
from pathlib import Path
from click.testing import CliRunner
from cashflow.cli import cli

CHASE_FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"
AMAZON_FIXTURE = Path(__file__).parent / "fixtures" / "amazon_orders_sample.txt"


def test_ingest_amazon_orders(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--files", str(AMAZON_FIXTURE)]
    )
    assert result.exit_code == 0
    assert "Amazon items" in result.output


def test_ingest_directory_with_mixed_files(tmp_path):
    """Ingest a directory containing both Chase CSVs and Amazon order files."""
    db_path = tmp_path / "test.db"
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    # Copy fixtures to inbox
    import shutil
    shutil.copy(CHASE_FIXTURE, inbox / "chase-prime-mar-2026.csv")
    shutil.copy(AMAZON_FIXTURE, inbox / "amazon-orders-fred.txt")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--files", str(inbox)]
    )
    assert result.exit_code == 0
    assert "new transactions" in result.output
    assert "Amazon items" in result.output
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_e2e.py -v`
Expected: All 2 tests PASS

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/cli.py tests/test_e2e.py
git commit -m "feat: Amazon order ingestion and reconciliation in CLI"
```

---

## Chunk 4: Target Card CSV Parser

### Task 5: Target Card CSV Parser

Target RedCard CSVs have a clean format:
```
"Transaction Date","Posting Date","Ref#","Amount","Description","Last 4 of Card/Account","Transaction Type"
"2026-03-11","2026-03-11","0541019ENP4D71P93","66.43","TARGET  00027706  VIRGINIA BEACVA","**2410","Sale"
```

Key differences from Chase:
- Dates are ISO format (`YYYY-MM-DD`)
- Amounts are **positive for purchases** (same as our spec convention — no sign flip needed)
- Negative amounts for payments and returns
- Transaction Type: `Sale`, `Payment`, `Return`
- Descriptions are all "TARGET" with store numbers — no item-level detail
- Multiple card numbers (`**2410`, `**9147`) on the same account
- Files are named `Transactions.CSV`, `Transactions (1).CSV`, etc.

**Files:**
- Create: `src/cashflow/parsers/target.py`
- Create: `tests/test_target_parser.py`
- Create: `tests/fixtures/target_sample.csv`
- Modify: `src/cashflow/cli.py` (add target parser to ingest)

- [ ] **Step 1: Create Target CSV fixture**

Create `tests/fixtures/target_sample.csv`:
```csv
"Transaction Date","Posting Date","Ref#","Amount","Description","Last 4 of Card/Account","Transaction Type"
"2026-03-11","2026-03-11","0541019ENP4D71P93","66.43","TARGET        00027706   VIRGINIA BEACVA","**2410","Sale"
"2026-02-28","2026-02-28","0541019EBP4DAT0Q7","16.95","TARGET        00022038   CHESAPEAKE   VA","**2410","Sale"
"2026-01-19","2026-01-19","89261008600XV713D","-197.56","AUTO PAYMENT - THANKS    *            MN","","Payment"
"2026-01-08","2026-01-08","0541019QRP4DBDKKZ","326.27","TARGET        00027706   VIRGINIA BEACVA","**2410","Sale"
"2025-12-23","2025-12-23","054101981P4D6SS9G","-12.48","TARGET        00027706 VIRGINIA B CREDIT","","Return"
"2025-12-23","2025-12-23","0541019B5P4DBJ4YM","241.65","TARGET        00027706   VIRGINIA BEACVA","**2410","Sale"
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_target_parser.py
from pathlib import Path
from cashflow.parsers.target import parse_target_csv

FIXTURE = Path(__file__).parent / "fixtures" / "target_sample.csv"


def test_parse_target_csv_returns_transactions():
    txns = parse_target_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_target_csv_skips_payments():
    txns = parse_target_csv(FIXTURE)
    descriptions = [t.description for t in txns]
    assert not any("AUTO PAYMENT" in d for d in descriptions)


def test_parse_target_csv_skips_returns():
    txns = parse_target_csv(FIXTURE)
    # Returns have negative amounts — should be kept as credits
    returns = [t for t in txns if t.amount < 0]
    assert len(returns) == 1  # The -12.48 return
    assert returns[0].amount == -12.48


def test_parse_target_csv_keeps_positive_amounts():
    """Target amounts are already positive for purchases — no sign flip needed."""
    txns = parse_target_csv(FIXTURE)
    sales = [t for t in txns if t.amount > 0]
    assert len(sales) == 4  # 66.43, 16.95, 326.27, 241.65


def test_parse_target_csv_parses_iso_dates():
    txns = parse_target_csv(FIXTURE)
    first = [t for t in txns if t.amount == 66.43][0]
    assert str(first.date) == "2026-03-11"


def test_parse_target_csv_normalizes_merchant():
    txns = parse_target_csv(FIXTURE)
    assert all(t.merchant == "Target" for t in txns)


def test_parse_target_csv_source_id_is_unique():
    txns = parse_target_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_target_csv_sets_account_name():
    txns = parse_target_csv(FIXTURE)
    assert all(t.account_name == "Target Card" for t in txns)


def test_parse_target_csv_sets_source_type():
    txns = parse_target_csv(FIXTURE)
    assert all(t.source_type == "csv" for t in txns)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_target_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement Target CSV parser**

```python
# src/cashflow/parsers/target.py
import csv
import hashlib
from datetime import date
from pathlib import Path

from cashflow.models import ParsedTransaction


def _make_source_id(row: dict) -> str:
    """Generate a deterministic dedup key from a Target CSV row."""
    raw = f"{row['Transaction Date']}|{row['Ref#']}|{row['Amount']}"
    return f"target-csv-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_target_csv(path: Path) -> list[ParsedTransaction]:
    """Parse a Target RedCard CSV export into transactions.

    Target CSVs use positive amounts for purchases and negative for
    payments/returns. Payments are skipped. Returns are kept as negative
    amounts (credits). No sign flip needed — matches spec convention.
    """
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount = float(row["Amount"])
            txn_type = row["Transaction Type"].strip()

            # Skip payments
            if txn_type == "Payment":
                continue

            txn_date = date.fromisoformat(row["Transaction Date"])
            description = row["Description"].strip()

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant="Target",
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Target Card",
                )
            )

    return transactions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_target_parser.py -v`
Expected: All 9 tests PASS

- [ ] **Step 6: Wire Target parser into CLI**

In `src/cashflow/cli.py`, add import at top:
```python
from cashflow.parsers.target import parse_target_csv
```

In the ingest command's file processing loop, add an `elif` branch for Target files. The Target CSVs are named `Transactions.CSV`, `Transactions (1).CSV`, etc. — detect by checking for "transaction" in the filename:

After the `elif "amazon"` branch, add:
```python
        elif "transaction" in csv_file.name.lower():
            txns = parse_target_csv(csv_file)
        else:
            click.echo(f"  Skipped — no parser for {csv_file.name}")
            continue
```

Also update the glob to include `.CSV` (uppercase) files since Target exports use uppercase extension. Change the glob line to:
```python
        csv_files = sorted(path.glob("*.csv")) + sorted(path.glob("*.CSV")) + sorted(path.glob("*.txt"))
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/cashflow/parsers/target.py tests/test_target_parser.py tests/fixtures/target_sample.csv src/cashflow/cli.py
git commit -m "feat: Target RedCard CSV parser"
```

---

## Summary

After completing Plan 3, you have:
- **Amazon order screen scrape parser** — extracts orders, items, dates, totals, Subscribe & Save status, account detection (fred/wife)
- **Reconciliation engine** — matches Amazon items to Chase transactions via order number
- **Target RedCard CSV parser** — parses Target card statements, keeps returns as negative credits
- **Mixed-source ingestion** — `cashflow ingest --files` handles Chase CSVs, Target CSVs, and Amazon order text files in the same directory
- **End-to-end pipeline** — ingest CSVs → store transactions → categorize → ingest Amazon orders → reconcile → everything linked
- ~62+ automated tests

**Next:** Plan 4 adds the dashboard (FastAPI server, HTML frontend, sync mechanism).
