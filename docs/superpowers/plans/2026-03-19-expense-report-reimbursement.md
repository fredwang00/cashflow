# Expense Report Reimbursement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag reimbursed business expenses so they're excluded from the trend graph's baseline view.

**Architecture:** Add `is_reimbursed` column to transactions. New .xlsx parser reads expense reports, matches rows to existing transactions by date + amount, and sets the flag. Baseline trend query excludes both one-offs and reimbursed. Dashboard gets a toggle column mirroring the one-off star pattern.

**Tech Stack:** openpyxl (new dependency), SQLite, FastAPI, Chart.js (existing)

---

### File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/cashflow/db.py` | Modify | Add `is_reimbursed` column to schema |
| `src/cashflow/parsers/expense_report.py` | Create | Parse .xlsx expense reports |
| `src/cashflow/reimburse.py` | Create | Match parsed expense rows to transactions, set flag |
| `src/cashflow/cli.py` | Modify | Add `--expense-report` option to `ingest` |
| `src/cashflow/server.py` | Modify | Add toggle endpoint, include `is_reimbursed` in queries, exclude from baseline |
| `src/cashflow/static/index.html` | Modify | Add Reimb column header |
| `src/cashflow/static/app.js` | Modify | Add reimbursed toggle button in transaction rows |
| `pyproject.toml` | Modify | Add `openpyxl` dependency |
| `tests/fixtures/expense_report_sample.xlsx` | Create | Test fixture |
| `tests/test_expense_report.py` | Create | Parser + matching tests |
| `tests/test_server.py` | Modify | Test toggle-reimbursed endpoint and baseline exclusion |
| `tests/test_cli.py` | Modify | Test `ingest --expense-report` CLI flow |

---

### Task 1: Add openpyxl dependency and schema column

**Files:**
- Modify: `pyproject.toml:9-14`
- Modify: `src/cashflow/db.py:31-48` (transactions CREATE TABLE)
- Test: `tests/test_db.py`

- [ ] **Step 1: Add openpyxl to dependencies**

```toml
dependencies = [
    "click>=8.1",
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "openpyxl>=3.1",
]
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write failing test for schema column**

```python
# tests/test_db.py — add to existing file
def test_is_reimbursed_column_exists(tmp_path):
    from cashflow.db import get_connection
    conn = get_connection(tmp_path / "test.db")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    assert "is_reimbursed" in cols
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py::test_is_reimbursed_column_exists -v`
Expected: FAIL — `is_reimbursed` not in column list

- [ ] **Step 4: Add column to schema and migration**

In `src/cashflow/db.py`, add after `one_off_label TEXT,` (line 42):

```python
    is_reimbursed BOOLEAN NOT NULL DEFAULT 0,
```

Also add a migration at the end of `SCHEMA_SQL` for existing databases:

```sql
-- Migration: add is_reimbursed to existing transactions tables
ALTER TABLE transactions ADD COLUMN is_reimbursed BOOLEAN NOT NULL DEFAULT 0;
```

Note: `ALTER TABLE ADD COLUMN` is a no-op error if the column already exists. Wrap in a check or use a try/except in `create_schema`. The simplest approach: add a separate migration function in `db.py` called after `create_schema`:

```python
def _migrate(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "is_reimbursed" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN is_reimbursed BOOLEAN NOT NULL DEFAULT 0")
        conn.commit()
```

Call `_migrate(conn)` in `get_connection` after `create_schema(conn)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_db.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/cashflow/db.py tests/test_db.py
git commit -m "feat: add is_reimbursed column and openpyxl dependency"
```

---

### Task 2: Expense report parser

**Files:**
- Create: `src/cashflow/parsers/expense_report.py`
- Create: `tests/fixtures/expense_report_sample.xlsx`
- Create: `tests/test_expense_report.py`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/expense_report_sample.xlsx` with openpyxl:

```python
# One-time script or inline in test setup
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(["Date", "Receipt", "Expense Type", "Vendor Details", "Payment Type", "Approved"])
ws.append(["04/12/2025", "Yes", "Taxi", "Uber Technologies", "Cash", "$53.94"])
ws.append(["04/11/2025", "Yes", "Individual Meals", "Mikado", "Cash", "$48.31"])
ws.append(["04/11/2025", "Yes", "Hotel", "Mint House", "Cash", "$2,025.60"])
wb.save("tests/fixtures/expense_report_sample.xlsx")
```

- [ ] **Step 2: Write failing test for parser**

```python
# tests/test_expense_report.py
from pathlib import Path
from cashflow.parsers.expense_report import parse_expense_report

FIXTURE = Path(__file__).parent / "fixtures" / "expense_report_sample.xlsx"

def test_parse_expense_report():
    rows = parse_expense_report(FIXTURE)
    assert len(rows) == 3
    assert rows[0].date.isoformat() == "2025-04-12"
    assert rows[0].amount == 53.94
    assert rows[0].vendor == "Uber Technologies"

def test_parse_expense_report_amounts():
    rows = parse_expense_report(FIXTURE)
    amounts = [r.amount for r in rows]
    assert 2025.60 in amounts  # comma-formatted dollar amount parsed correctly
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_expense_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cashflow.parsers.expense_report'`

- [ ] **Step 4: Implement parser**

```python
# src/cashflow/parsers/expense_report.py
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import openpyxl


@dataclass
class ExpenseRow:
    date: date
    amount: float
    vendor: str
    expense_type: str


def _parse_amount(val: str) -> float:
    """Parse '$1,620.48' -> 1620.48"""
    return float(str(val).replace("$", "").replace(",", ""))


def _parse_date(val) -> date:
    """Handle both string dates ('04/12/2025') and native Excel datetime objects."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%m/%d/%Y").date()


def parse_expense_report(path: Path) -> list[ExpenseRow]:
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:  # skip header
            continue
        if not row[0]:
            continue
        dt = _parse_date(row[0])
        amount = _parse_amount(row[5])  # Approved column
        vendor = str(row[3])
        expense_type = str(row[2])
        rows.append(ExpenseRow(date=dt, amount=amount, vendor=vendor, expense_type=expense_type))
    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_expense_report.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/cashflow/parsers/expense_report.py tests/test_expense_report.py tests/fixtures/expense_report_sample.xlsx
git commit -m "feat: add expense report xlsx parser"
```

---

### Task 3: Matching engine — link expense rows to transactions

**Files:**
- Create: `src/cashflow/reimburse.py`
- Modify: `tests/test_expense_report.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_expense_report.py — add to imports at top
import sqlite3
from datetime import date
from cashflow.db import create_schema, store_transactions
from cashflow.seed import seed_all
from cashflow.models import ParsedTransaction
from cashflow.reimburse import match_expense_report


def _make_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    return conn


def test_match_expense_report(tmp_path):
    conn = _make_db(tmp_path)
    txns = [
        ParsedTransaction(date=date(2025, 4, 12), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 11), amount=48.31, description="MIKADO NYC", merchant="Mikado", source_id="t2", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 11), amount=2025.60, description="MINT HOUSE", merchant="Mint House", source_id="t3", source_type="csv", account_name="Chase Prime Visa"),
        ParsedTransaction(date=date(2025, 4, 15), amount=100.00, description="GROCERY", merchant="Kroger", source_id="t4", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)
    rows = parse_expense_report(FIXTURE)

    matched, unmatched = match_expense_report(conn, rows)
    assert matched == 3
    assert unmatched == 0

    # Verify flag is set
    reimbursed = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE is_reimbursed = 1").fetchone()["c"]
    assert reimbursed == 3

    # Kroger should NOT be flagged
    kroger = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 't4'").fetchone()
    assert kroger["is_reimbursed"] == 0


def test_match_expense_report_idempotent(tmp_path):
    conn = _make_db(tmp_path)
    txns = [
        ParsedTransaction(date=date(2025, 4, 12), amount=53.94, description="UBER *TRIP", merchant="Uber", source_id="t1", source_type="csv", account_name="Chase Prime Visa"),
    ]
    store_transactions(conn, txns)
    rows = parse_expense_report(FIXTURE)

    match_expense_report(conn, rows)
    match_expense_report(conn, rows)  # second run

    reimbursed = conn.execute("SELECT COUNT(*) as c FROM transactions WHERE is_reimbursed = 1").fetchone()["c"]
    assert reimbursed == 1


def test_match_expense_report_unmatched(tmp_path):
    conn = _make_db(tmp_path)
    # No transactions in DB — all expense rows should be unmatched
    rows = parse_expense_report(FIXTURE)
    matched, unmatched = match_expense_report(conn, rows)
    assert matched == 0
    assert unmatched == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_expense_report.py::test_match_expense_report -v`
Expected: FAIL — `ImportError: cannot import name 'match_expense_report'`

- [ ] **Step 3: Implement matching engine**

```python
# src/cashflow/reimburse.py
import sqlite3
from cashflow.parsers.expense_report import ExpenseRow


def match_expense_report(conn: sqlite3.Connection, rows: list[ExpenseRow]) -> tuple[int, int]:
    """Match expense report rows to transactions by date + amount. Returns (matched, unmatched)."""
    matched = 0
    unmatched = 0
    for row in rows:
        txn = conn.execute(
            "SELECT id FROM transactions "
            "WHERE date = ? AND ABS(amount - ?) < 0.005 AND canonical_id IS NULL AND is_reimbursed = 0",
            (row.date.isoformat(), row.amount),
        ).fetchone()
        if txn:
            conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE id = ?", (txn["id"],))
            matched += 1
        else:
            unmatched += 1
    conn.commit()
    return matched, unmatched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_expense_report.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/reimburse.py tests/test_expense_report.py
git commit -m "feat: add expense report matching engine"
```

---

### Task 4: CLI — `ingest --expense-report`

**Files:**
- Modify: `src/cashflow/cli.py:30-34` (ingest command options)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli.py — add
def test_ingest_expense_report(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.db"
    fixture_xlsx = Path(__file__).parent / "fixtures" / "expense_report_sample.xlsx"
    runner = CliRunner()

    # Seed DB and insert a transaction that matches the fixture (2025-04-12, $53.94)
    runner.invoke(cli, ["--db", str(db_path), "status"])  # triggers seed
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    acct_id = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
        "VALUES ('er-test-1', '2025-04-12', 53.94, 'UBER *TRIP', 'Uber', ?, 'confirmed', 100, 'fred', 'csv')",
        (acct_id,),
    )
    conn.commit()
    conn.close()

    # Ingest expense report
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--expense-report", str(fixture_xlsx)]
    )
    assert result.exit_code == 0
    assert "1 matched" in result.output

    # Verify the flag was actually set
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 'er-test-1'").fetchone()
    assert row["is_reimbursed"] == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_ingest_expense_report -v`
Expected: FAIL — no `--expense-report` option

- [ ] **Step 3: Add `--expense-report` option to ingest command**

In `src/cashflow/cli.py`, add the option and handling:

```python
# Add to imports at top:
from cashflow.parsers.expense_report import parse_expense_report
from cashflow.reimburse import match_expense_report

# Add option to ingest command (after --auto):
@click.option("--expense-report", type=click.Path(exists=True), help="Path to expense report .xlsx file or directory.")

# Add to ingest function signature:
def ingest(ctx, files, email, auto, expense_report):

# Add handling block before the files processing:
    if expense_report:
        er_path = Path(expense_report)
        if er_path.is_file():
            xlsx_files = [er_path]
        else:
            xlsx_files = sorted(er_path.glob("*.xlsx"))
        for xlsx in xlsx_files:
            click.echo(f"Matching expense report: {xlsx.name}...")
            rows = parse_expense_report(xlsx)
            matched, unmatched = match_expense_report(conn, rows)
            click.secho(f"  {matched} matched, {unmatched} unmatched", fg="green" if unmatched == 0 else "yellow")
            if unmatched > 0:
                # Print unmatched for manual review
                for row in rows:
                    txn = conn.execute(
                        "SELECT id FROM transactions WHERE date = ? AND ABS(amount - ?) < 0.005 AND canonical_id IS NULL",
                        (row.date.isoformat(), row.amount),
                    ).fetchone()
                    if not txn:
                        click.secho(f"    No match: {row.date} ${row.amount:,.2f} {row.vendor}", fg="yellow")
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/cli.py tests/test_cli.py
git commit -m "feat: add --expense-report option to ingest command"
```

---

### Task 5: API — baseline excludes reimbursed, add toggle endpoint

**Files:**
- Modify: `src/cashflow/server.py:91-178` (queries), `src/cashflow/server.py:180-196` (toggle pattern)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_server.py — add

def test_yearly_baseline_excludes_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    # Flag one transaction as reimbursed
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    data = resp.json()
    march = data["months"][2]  # March = index 2
    # Baseline should exclude the $1500 reimbursed Kroger transaction
    assert march["spending_baseline"] < march["spending"]


def test_toggle_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)

    resp = client.post("/api/transactions/1/toggle-reimbursed")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_reimbursed"] is True

    # Toggle off
    resp = client.post("/api/transactions/1/toggle-reimbursed")
    data = resp.json()
    assert data["is_reimbursed"] is False


def test_monthly_includes_is_reimbursed(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE transactions SET is_reimbursed = 1 WHERE source_id = 'test-1'")
    conn.commit()
    conn.close()

    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    data = resp.json()
    reimbursed_txns = [t for t in data["transactions"] if t.get("is_reimbursed")]
    assert len(reimbursed_txns) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py::test_yearly_baseline_excludes_reimbursed tests/test_server.py::test_toggle_reimbursed tests/test_server.py::test_monthly_includes_is_reimbursed -v`
Expected: FAIL

- [ ] **Step 3: Update server.py**

Changes:
1. Add `t.is_reimbursed` to all SELECT queries that return transaction fields
2. Update baseline query in yearly endpoint
3. Add toggle-reimbursed endpoint

In the monthly endpoint (line 95-96), transactions endpoint (lines 122-123 and 131-132), add `t.is_reimbursed,` after `t.one_off_label,` in each SELECT. For example the monthly query becomes:

```python
"SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
"t.is_one_off, t.one_off_label, t.is_reimbursed, c.name as category "
```

Apply the same change to both SELECT branches in the `/api/transactions` endpoint (lines 122 and 131).

```python
# Baseline query update (server.py yearly endpoint):
sp_baseline = conn.execute(
    "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
    "WHERE canonical_id IS NULL AND is_one_off = 0 AND is_reimbursed = 0 "
    "AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
    (str(year), f"{mo:02d}"),
).fetchone()["total"]

# New endpoint:
@app.post("/api/transactions/{txn_id}/toggle-reimbursed")
def toggle_reimbursed(txn_id: int):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    txn = conn.execute("SELECT id, is_reimbursed FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        conn.close()
        return {"error": "not found"}
    new_val = 0 if txn["is_reimbursed"] else 1
    conn.execute("UPDATE transactions SET is_reimbursed = ? WHERE id = ?", (new_val, txn_id))
    conn.commit()
    conn.close()
    return {"id": txn_id, "is_reimbursed": bool(new_val)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_server.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/server.py tests/test_server.py
git commit -m "feat: exclude reimbursed from baseline, add toggle endpoint"
```

---

### Task 6: Dashboard — reimbursed toggle in transaction table

**Files:**
- Modify: `src/cashflow/static/index.html:79` (add column header)
- Modify: `src/cashflow/static/app.js:372-395` (add toggle button)

- [ ] **Step 1: Add column header to index.html**

After the `<th>One-off</th>` line (line 79), add:

```html
<th>Reimb</th>
```

- [ ] **Step 2: Add reimbursed toggle button to app.js**

After the one-off button block (after line 395 `tr.appendChild(tdOneOff);`), add:

```javascript
var tdReimb = document.createElement('td');
var rBtn = document.createElement('button');
rBtn.className = 'oneoff-btn' + (tx.is_reimbursed ? ' active' : '');
rBtn.textContent = tx.is_reimbursed ? '$' : '-';
rBtn.title = tx.is_reimbursed ? 'Reimbursed' : 'Mark as reimbursed';
rBtn.dataset.id = tx.id;
rBtn.addEventListener('click', function() {
    var id = parseInt(this.dataset.id);
    fetch('/api/transactions/' + id + '/toggle-reimbursed', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            rBtn.classList.toggle('active', data.is_reimbursed);
            rBtn.textContent = data.is_reimbursed ? '$' : '-';
            rBtn.title = data.is_reimbursed ? 'Reimbursed' : 'Mark as reimbursed';
            tx.is_reimbursed = data.is_reimbursed ? 1 : 0;
        });
});
tdReimb.appendChild(rBtn);
tr.appendChild(tdReimb);
```

- [ ] **Step 3: Verify manually**

Run: `cashflow dashboard` and check:
- Reimb column appears
- Clicking `-` toggles to `$` and back
- Reimbursed transactions show `$` icon

- [ ] **Step 4: Commit**

```bash
git add src/cashflow/static/index.html src/cashflow/static/app.js
git commit -m "feat: add reimbursed toggle to dashboard transaction table"
```

---

### Task 7: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add expense report docs**

Add to the CLI commands section after the tagging block:

```markdown
# Expense reports (reimbursements)
cashflow ingest --expense-report ~/Downloads/expense-reports-2025/
cashflow ingest --expense-report ~/Downloads/core_week.xlsx  # single file
```

Add to the supported data sources table:

```markdown
| Expense reports | .xlsx | Matches to existing transactions by date + amount |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add expense report ingestion to README"
```

---

### Task 8: Full integration test and verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All pass (141 existing + ~8 new)

- [ ] **Step 2: Run against real data**

```bash
cashflow ingest --expense-report ~/Downloads/expense-reports-2025/
```

Verify output shows matched/unmatched counts per file.

- [ ] **Step 3: Check trend graph**

Run: `cashflow dashboard`
Navigate to months with reimbursed expenses (Apr, Nov, Dec 2025). Baseline view should show lower spending than Total view.

- [ ] **Step 4: Final commit if any fixups needed**
