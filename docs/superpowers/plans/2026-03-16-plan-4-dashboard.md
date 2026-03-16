# Plan 4: Dashboard — FastAPI Server + HTML Frontend

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a local HTML dashboard at `http://localhost:8080` showing monthly burn rate, YTD surplus, spending by category, and a transaction list. The dashboard reads from the same SQLite database the CLI writes to.

**Architecture:** FastAPI serves read-only JSON API endpoints + static HTML/JS frontend. Chart.js for visualizations. Single-page app with tab navigation between views. No build step — vanilla HTML/JS/CSS.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, SQLite (read-only), Chart.js (CDN), vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-14-cashflow-design.md` — sections "Dashboard Views", "Deployment Architecture"

**Depends on:** Plans 1-3 (complete — 131 tests, 2,761 transactions ingested)

---

## New Files

```
src/cashflow/
├── server.py                    # FastAPI app with API endpoints
├── static/
│   ├── index.html               # Dashboard SPA
│   ├── style.css                # Dashboard styles
│   └── app.js                   # Dashboard JS (fetch API, render charts)
└── (cli.py modified)            # Add dashboard command

tests/
└── test_server.py               # API endpoint tests
```

---

## Chunk 1: FastAPI Server + API Endpoints

### Task 1: FastAPI Server with Core API

**Files:**
- Create: `src/cashflow/server.py`
- Create: `tests/test_server.py`
- Modify: `pyproject.toml` (add fastapi, uvicorn)

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to dependencies:
```
    "fastapi>=0.115",
    "uvicorn>=0.34",
```

Also add `"httpx>=0.27"` to the `dev` optional dependencies (required by FastAPI's TestClient).

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Write failing tests for API endpoints**

```python
# tests/test_server.py
import sqlite3
from datetime import date
from fastapi.testclient import TestClient
from cashflow.server import create_app
from cashflow.db import create_schema, store_transactions, store_income
from cashflow.seed import seed_all
from cashflow.models import ParsedTransaction


def _make_app(db_path):
    return create_app(str(db_path))


def _seed_and_populate(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_all(conn)
    # Add some transactions
    txns = [
        ParsedTransaction(date=date(2026, 3, 1), amount=1500.0, description="KROGER", merchant="Kroger", source_id="test-1", source_type="csv", account_name="Bank of America"),
        ParsedTransaction(date=date(2026, 3, 5), amount=3450.37, description="NEWREZ MORTGAGE", merchant="Newrez Mortgage", source_id="test-2", source_type="csv", account_name="Checking"),
        ParsedTransaction(date=date(2026, 3, 10), amount=200.0, description="TARGET", merchant="Target", source_id="test-3", source_type="csv", account_name="Target Card"),
        ParsedTransaction(date=date(2026, 2, 15), amount=800.0, description="KROGER", merchant="Kroger", source_id="test-4", source_type="csv", account_name="Bank of America"),
    ]
    store_transactions(conn, txns)
    # Confirm some
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Groceries') WHERE source_id = 'test-1'")
    conn.execute("UPDATE transactions SET status = 'confirmed', category_id = (SELECT id FROM categories WHERE name = 'Mortgage') WHERE source_id = 'test-2'")
    conn.commit()
    # Add income
    store_income(conn, [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-1"},
        {"date": date(2026, 2, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-2"},
        {"date": date(2026, 3, 15), "amount": 7584.14, "source": "fei_paycheck", "description": "SPOTIFY", "source_id": "inc-3"},
    ])
    conn.close()


def test_status_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "month_spending" in data
    assert "ceiling" in data
    assert "ytd_surplus" in data
    assert "review_queue" in data


def test_monthly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/monthly/2026/3")
    assert resp.status_code == 200
    data = resp.json()
    assert "transactions" in data
    assert "by_category" in data
    assert "total" in data


def test_transactions_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/transactions?year=2026&month=3")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_yearly_endpoint(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/api/yearly/2026")
    assert resp.status_code == 200
    data = resp.json()
    assert "months" in data
    assert "ytd_income" in data
    assert "ytd_spending" in data
    assert "ytd_surplus" in data


def test_index_serves_html(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_and_populate(db_path)
    app = _make_app(db_path)
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_server.py -v`
Expected: FAIL

- [ ] **Step 4: Implement server.py**

```python
# src/cashflow/server.py
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cashflow.db import DEFAULT_DB_PATH

STATIC_DIR = Path(__file__).parent / "static"


def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def create_app(db_path: str = str(DEFAULT_DB_PATH)) -> FastAPI:
    app = FastAPI(title="cashflow")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def api_status():
        conn = _get_db(db_path)
        today = date.today()
        y, m = today.year, today.month

        spending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
            "WHERE canonical_id IS NULL AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
            (str(y), f"{m:02d}"),
        ).fetchone()["total"]

        income = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM income WHERE strftime('%Y', date) = ?",
            (str(y),),
        ).fetchone()["total"]

        ytd_spending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
            "WHERE canonical_id IS NULL AND strftime('%Y', date) = ?",
            (str(y),),
        ).fetchone()["total"]

        review_count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE canonical_id IS NULL AND status = 'pending'"
        ).fetchone()["c"]

        ceiling_row = conn.execute("SELECT amount FROM goals WHERE type = 'ceiling'").fetchone()
        ceiling = ceiling_row["amount"] if ceiling_row else 12000.0

        surplus_row = conn.execute("SELECT amount FROM goals WHERE type = 'surplus'").fetchone()
        surplus_goal = surplus_row["amount"] if surplus_row else 40000.0

        days_in_month = 31
        if m < 12:
            days_in_month = (date(y, m + 1, 1) - date(y, m, 1)).days
        days_left = days_in_month - today.day

        conn.close()
        return {
            "month_spending": round(spending, 2),
            "ceiling": ceiling,
            "pct": round(spending / ceiling * 100, 1) if ceiling > 0 else 0,
            "days_left": days_left,
            "days_in_month": days_in_month,
            "month_name": today.strftime("%B %Y"),
            "ytd_income": round(income, 2),
            "ytd_spending": round(ytd_spending, 2),
            "ytd_surplus": round(income - ytd_spending, 2),
            "surplus_goal": surplus_goal,
            "review_queue": review_count,
        }

    @app.get("/api/monthly/{year}/{month}")
    def api_monthly(year: int, month: int):
        conn = _get_db(db_path)

        txns = conn.execute(
            "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
            "t.is_one_off, t.one_off_label, c.name as category "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
            "ORDER BY t.date DESC",
            (str(year), f"{month:02d}"),
        ).fetchall()

        by_category = conn.execute(
            "SELECT c.name as category, ROUND(SUM(t.amount), 2) as total "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
            "GROUP BY c.name ORDER BY total DESC",
            (str(year), f"{month:02d}"),
        ).fetchall()

        total = sum(t["amount"] for t in txns)

        conn.close()
        return {
            "year": year,
            "month": month,
            "total": round(total, 2),
            "transactions": [dict(t) for t in txns],
            "by_category": [dict(r) for r in by_category],
        }

    @app.get("/api/transactions")
    def api_transactions(year: int = 2026, month: int | None = None, limit: int = 100):
        conn = _get_db(db_path)
        if month:
            rows = conn.execute(
                "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
                "t.is_one_off, t.one_off_label, c.name as category "
                "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
                "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
                "ORDER BY t.date DESC LIMIT ?",
                (str(year), f"{month:02d}", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
                "t.is_one_off, t.one_off_label, c.name as category "
                "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
                "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? "
                "ORDER BY t.date DESC LIMIT ?",
                (str(year), limit),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @app.get("/api/yearly/{year}")
    def api_yearly(year: int):
        conn = _get_db(db_path)

        months = []
        for m in range(1, 13):
            spending = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
                "WHERE canonical_id IS NULL AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
                (str(year), f"{m:02d}"),
            ).fetchone()["total"]

            income = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM income "
                "WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ?",
                (str(year), f"{m:02d}"),
            ).fetchone()["total"]

            months.append({
                "month": m,
                "spending": round(spending, 2),
                "income": round(income, 2),
                "surplus": round(income - spending, 2),
            })

        ytd_income = sum(m["income"] for m in months)
        ytd_spending = sum(m["spending"] for m in months)

        conn.close()
        return {
            "year": year,
            "months": months,
            "ytd_income": round(ytd_income, 2),
            "ytd_spending": round(ytd_spending, 2),
            "ytd_surplus": round(ytd_income - ytd_spending, 2),
        }

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app
```

- [ ] **Step 5: Create placeholder static files**

Create `src/cashflow/static/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>cashflow</title>
    <link rel="stylesheet" href="/static/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
</head>
<body>
    <h1>cashflow</h1>
    <p>Loading...</p>
    <script src="/static/app.js"></script>
</body>
</html>
```

Create `src/cashflow/static/style.css`:
```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }
```

Create `src/cashflow/static/app.js`:
```javascript
// placeholder
console.log('cashflow dashboard loaded');
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_server.py -v`
Expected: All 5 tests PASS

- [ ] **Step 7: Wire dashboard command into CLI**

Read `src/cashflow/cli.py`. Add the dashboard command:

```python
@cli.command()
@click.option("--port", default=8080, help="Port to serve on.")
@click.pass_context
def dashboard(ctx, port):
    """Open the financial dashboard in a browser."""
    import threading
    import webbrowser
    import uvicorn
    from cashflow.server import create_app

    db_path = str(ctx.obj["conn"].execute("PRAGMA database_list").fetchone()[2])
    ctx.obj["conn"].close()

    app = create_app(db_path)
    # Delay browser open so server has time to start
    threading.Timer(1.0, webbrowser.open, args=[f"http://localhost:{port}"]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

- [ ] **Step 8: Commit**

```bash
git add src/cashflow/server.py src/cashflow/static/ tests/test_server.py pyproject.toml src/cashflow/cli.py
git commit -m "feat: FastAPI dashboard server with status, monthly, yearly, transactions API"
```

---

## Chunk 2: Dashboard Frontend

### Task 2: Dashboard HTML/JS/CSS

This is the visual frontend. The dashboard is a single-page app with:
- **Header bar** showing current month burn rate (big number + progress bar)
- **YTD surplus** card
- **Monthly spending by category** bar chart
- **Transaction list** table with search
- **Month selector** to navigate between months

**Files:**
- Rewrite: `src/cashflow/static/index.html`
- Rewrite: `src/cashflow/static/style.css`
- Rewrite: `src/cashflow/static/app.js`

- [ ] **Step 1: Build the dashboard frontend**

This step is intentionally open-ended — use the `superpowers:frontend-design` skill or build directly. The frontend should:

1. On load, fetch `/api/status` and render the header with burn rate + surplus
2. Fetch `/api/monthly/{year}/{month}` and render a Chart.js bar chart of spending by category
3. Render the transaction list as a sortable table
4. Include month navigation (prev/next buttons)
5. Auto-refresh data when month changes

The design should follow the dark theme from the brainstorming visual companion (dark slate background, blue/green/yellow accent colors).

Key implementation details:
- All data comes from the API endpoints — no server-side rendering
- Chart.js loaded from CDN (already in the HTML)
- Vanilla JS, no framework
- Responsive for laptop + tablet (no mobile needed, LAN-only)

- [ ] **Step 2: Manual test**

Run: `cashflow dashboard`
Expected: Browser opens to `http://localhost:8080`, shows burn rate and spending chart with real data.

- [ ] **Step 3: Commit**

```bash
git add src/cashflow/static/
git commit -m "feat: dashboard frontend with burn rate, category chart, and transaction list"
```

---

## Summary

After completing Plan 4, you have:
- **FastAPI server** with 4 read-only API endpoints (status, monthly, yearly, transactions)
- **HTML dashboard** at `http://localhost:8080` showing:
  - Monthly burn rate vs $12k ceiling (progress bar, color-coded)
  - YTD surplus vs $40k goal
  - Spending by category (bar chart)
  - Transaction list with merchant, amount, date, category
  - Month navigation
- **`cashflow dashboard` CLI command** — opens browser and starts server
- ~136+ automated tests

**Next:** Plan 5 adds the Intelligence Layer (`cashflow ask` + `cashflow briefing`).
