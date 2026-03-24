# Multi-bank download orchestration via Playwright CDP

## Problem

Downloading CSVs from 4 financial institutions (PayPal, Chase, BofA, Capital One) is a manual, forgettable chore. Previous attempts at full automation failed because Plaid tokens are brittle and browser automation requires managing credentials. Chrome's CDP now lets agents ride an already-authenticated browser session, removing the credential problem.

## Approach

A hybrid orchestration model: fully automate where possible (PayPal), navigate-and-prompt where not (Chase, BofA, Capital One). One command checks account freshness, opens the right pages, downloads what it can, watches for manual downloads, and ingests everything.

## User flow

1. Launch Chrome with remote debugging: `open -a 'Google Chrome' --args --remote-debugging-port=9222 --profile-directory='Profile 1'`
2. Log into any banks whose sessions have expired (most stay alive for weeks)
3. Run `cashflow ingest --download`
4. Terminal shows freshness status, PayPal downloads automatically
5. Stale manual banks open in new Chrome tabs with date guidance printed
6. User clicks "Download" in each bank tab
7. File watcher detects new CSVs in ~/Downloads, auto-ingests them
8. Terminal shows progress: "2/3 received, missing: Capital One"
9. Ctrl+C or all received: categorization + dedup runs, summary printed

## Components

### `src/cashflow/downloaders/base.py`

Shared infrastructure:

- `connect_to_chrome(port=9222)` — Playwright CDP connection, shared across all downloaders
- `get_latest_transaction_dates(conn)` — returns `{account_name: latest_date}` for all accounts
- Error on connection failure includes the exact Chrome launch command for the user's personal profile

### `src/cashflow/downloaders/paypal.py`

Full automation:

- Navigate to `https://www.paypal.com/reports/dlog`
- Set start date = latest PayPal transaction date (or 30 days ago if DB empty)
- Set end date = today
- Select CSV format
- Click "Create Report", wait for download link, click download
- Return downloaded file path

### `src/cashflow/downloaders/chase.py`

Navigate-and-prompt:

- Open Chase account activity page in new tab
- Print date guidance to terminal

### `src/cashflow/downloaders/bofa.py`

Navigate-and-prompt:

- Open BofA homepage in new tab (can't deep-link past auth)
- Print date guidance to terminal

### `src/cashflow/downloaders/capital_one.py`

Navigate-and-prompt:

- Open Capital One homepage in new tab
- Print date guidance to terminal

### `src/cashflow/downloaders/orchestrator.py`

Coordinator:

- Connect to Chrome once via CDP
- Query freshness for all known accounts
- Skip accounts fresh within 3 days
- Run PayPal downloader (automated)
- Open tabs for stale manual banks with terminal guidance
- Start file watcher on `~/Downloads`
- Match new files against filename patterns (same routing as `cli.py`: `chase`, `bofa`/`stmt`, `capital`, `paypal`, etc.)
- Move matched files to staging, run through `store_transactions`
- Print running status showing which banks are still pending
- On Ctrl+C or all received: run `categorize_by_rules`, `categorize_by_llm`, `link_paypal_to_cards`, `reconcile_amazon`
- Timeout after 5 minutes of inactivity with prompt to continue or finish

### CLI changes

- Add `--download` flag to `cashflow ingest`
- When set, run orchestrator before normal file-based ingest
- `--files` continues to work independently for manual CSV drops

## Dependencies

- `playwright` — CDP connection and browser navigation. No browser binary install needed (connecting to existing Chrome).
- `watchdog` — filesystem monitoring for `~/Downloads`

## Not in scope

- Chrome launch management (user starts Chrome themselves)
- Credential storage or session management
- Deep-link navigation for BofA/Capital One (auth walls prevent it)
- Retry logic beyond Playwright's built-in waits
- Scheduled/background execution
- Other bank downloaders beyond the four

## Testing

- Unit tests: `get_latest_transaction_dates`, filename pattern matching, staleness threshold logic
- Manual integration test: run against live Chrome + PayPal session
- Existing parser and dedup tests remain unchanged

## Risks

- PayPal `/reports/dlog` page could redesign (low probability, has been stable for years)
- Chrome profile directory name (`Profile 1`) may differ — need to verify on first run
- `watchdog` may trigger on partial downloads (`.crdownload` files) — filter by extension
- PayPal report generation is async (request → wait → download), need appropriate wait logic
