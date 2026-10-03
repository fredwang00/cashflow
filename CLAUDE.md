# CLAUDE.md

Guidance for AI agents working in this repo. The full context lives in [README.md](README.md); this file is the fast path for ad hoc work.

## What this is

A local-first household finance pipeline: bank CSV parsers → SQLite (`~/.cashflow/cashflow.db`) → CLI (`cashflow`) + FastAPI dashboard. Personal tool, single household, deliberately narrow bank support.

## Repo layout

- `src/cashflow/` — all Python. `cli.py` (Click commands), `server.py` (FastAPI, endpoints documented in [docs/api.md](docs/api.md)), `db.py` (schema DDL), `queries.py` (spending/income formulas — source of truth for burn rate and the savings exclusion), `parsers/` (one module per bank/source), `categorize.py` (rules + LLM fallback), `static/` (dashboard JS/HTML/CSS).
- `tests/` — pytest + Node-based JS tests; run `python -m pytest tests/ -v`.
- `docs/` — operating guides. `docs/superpowers/` is design history, **not** current instructions.

## Answering data questions

Prefer direct SQL over writing code. Follow [docs/adhoc-queries.md](docs/adhoc-queries.md) for schema semantics and copy-paste recipes. Critical rules:

- The DB is at `~/.cashflow/cashflow.db`, outside the repo. Open read-only: `sqlite3 -readonly`.
- Always filter `canonical_id IS NULL` (duplicate rows).
- Charges are **positive**; refunds are negative rows. Income lives in a separate `income` table, not as negative transactions.
- "Spending" excludes savings/investment categories via `not_savings()` in `queries.py` — match that condition or your numbers won't equal `cashflow status`.
- Effective cost is `amount - reimbursed_amount`.
- Vendors appear under many name variants (`TOWN CENTER BARBER SHO` vs `Town Center Barber Shop`) — run the variant-discovery recipe before any vendor query.
- Before counting two same-amount charges near each other as two real charges, check the `possible_dupes` view (`cashflow dupes`) — cross-source pairs are not linked by `canonical_id`.
- Remediate confirmed duplicate pairs with `cashflow dedupe-link` (single pair or `--from-dupes` bulk with filters + preview). Never write `canonical_id` by hand; `cashflow dedupe-unlink` undoes.
- For questions a human asked conversationally, `cashflow find QUERY --date-from ... --date-to ... --min-amount ... --who ... --account ... --json` covers most cases without SQL.
- The docs' SQL recipes are validated against the schema by `tests/test_docs_sql.py` — keep new recipes as read-only SELECT/WITH statements in ```sql fences so they stay covered.

## Gotchas

- Tests use temporary databases. Never point any tool or test fixture at the real `~/.cashflow/cashflow.db` for writes.
- Code fixes do not repair historical records automatically; reconciliation notes are in [docs/2026-09-23-audit.md](docs/2026-09-23-audit.md).
- Unknown CSV formats fail loudly by design — don't add silent fallback parsing.
- `.env` is not auto-loaded; `CASHFLOW_LLM_URL` unset means rules-only categorization.
