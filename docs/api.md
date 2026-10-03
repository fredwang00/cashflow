# HTTP API reference

The dashboard server (`cashflow dashboard`, default `http://localhost:8080`) is a FastAPI app created by `create_app()` in `src/cashflow/server.py`. All endpoints are read-only except the two toggles. Interactive OpenAPI docs are served automatically at `/docs` and `/redoc` while the server runs.

## Endpoints

### `GET /`

Serves the dashboard UI (`src/cashflow/static/index.html`).

### `GET /api/status`

Current-month snapshot used by the header cards and burn-rate bar.

Returns:

```json
{
  "year": 2026, "month": 9,
  "spending": 5123.45, "ceiling": 6500.0,
  "income": 9000.0, "surplus": 3876.55,
  "ytd_spending": 41000.0, "ytd_income": 62000.0, "ytd_surplus": 21000.0,
  "annual_goal": 24000.0, "review_queue": 12
}
```

`spending` and `ytd_spending` exclude savings/investment transfers (see `not_savings()` in `src/cashflow/queries.py`) and net out `reimbursed_amount`.

### `GET /api/monthly/{year}/{month}`

Everything for one month's view.

- Path: `year` (e.g. `2026`), `month` (1–12).
- Returns: `{"year", "month", "total", "transactions": [...], "by_category": [...]}` where each transaction has `id, date, amount, merchant, description, status, who, is_one_off, one_off_label, is_reimbursed, reimbursed_amount, category`, and `by_category` is `[{name, total}]` sorted descending. `total` is the same savings-excluding, reimbursement-netted figure as `/api/status`.

### `GET /api/transactions?year=&month=&limit=`

Transaction list, newest first. Defaults to the current year when `year` is omitted; `limit` defaults to 100. Same transaction fields as `/api/monthly`. Duplicate rows (`canonical_id IS NOT NULL`) are never returned.

### `GET /api/yearly/{year}`

Twelve-month trend data.

Returns: `{"year", "months": [...], "ytd_income", "ytd_spending", "ytd_surplus"}` where each month has:

| Field | Meaning |
|-------|---------|
| `spending` | All spending, savings excluded, reimbursements netted |
| `spending_baseline` | Same, but `is_one_off = 0` and unreimbursed only |
| `spending_oneoffs` | Tagged one-offs (`is_one_off = 1`), reimbursements netted |
| `income` | From the `income` table |
| `surplus` / `surplus_baseline` | Income minus spending / baseline |

### `POST /api/transactions/{txn_id}/toggle-oneoff?label=`

Toggles `is_one_off` on a transaction. When turning on, `label` (optional form/query param) sets `one_off_label`; when turning off the label is cleared. Returns `{"id", "is_one_off"}`. 404 if the id is unknown.

### `POST /api/transactions/{txn_id}/toggle-reimbursed`

Toggles full reimbursement: sets `is_reimbursed = 1` and `reimbursed_amount = amount` (or clears both). Returns the updated values. 404 if the id is unknown.

## Notes

- The server binds to localhost only; there is no auth by design.
- No merchant/category search endpoint exists yet — use `cashflow find "term"` or direct SQL ([docs/adhoc-queries.md](adhoc-queries.md)).
- New endpoints should follow the existing pattern: open a read connection via `_get_db` for GETs, a fresh writable `sqlite3.connect` for mutations, and `conn.close()` in all paths.
