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

## Account-to-institution mapping

The system has 11 accounts across 7 institutions. Only 4 institutions have downloaders:

| Institution | Accounts | Downloader | Mode |
|---|---|---|---|
| PayPal | PayPal | `paypal.py` | Automated |
| Chase | Chase Prime Visa, Chase Freedom, Checking | `chase.py` | Navigate-and-prompt |
| BofA | Bank of America (CC + checking) | `bofa.py` | Navigate-and-prompt |
| Capital One | Capital One Venture, Capital One Wendy | `capital_one.py` | Navigate-and-prompt |
| Target | Target Card | None | Ignored |
| Citi | Citi Costco | None | Ignored |
| Apple | Apple Card | None | Ignored |

Freshness is checked per institution (most recent transaction across all accounts at that institution), not per individual account. Chase downloads one CSV per card, so the navigate-and-prompt message lists each stale Chase account separately.

For BofA, the downloader opens one tab. BofA checking and credit card CSVs have different filename patterns — the file watcher handles both (`stmt`/`bofa` → checking parser, `_NNNN.csv` → CC parser).

For Capital One, the downloader opens one tab. The terminal guidance reminds the user to download each card separately. Filename containing `wendy` → Capital One Wendy, otherwise → Capital One Venture.

## Freshness definition

"Stale" means: the most recent transaction date for any account at that institution is more than 3 days before today. This is a rough heuristic — a bank with no recent charges would appear stale even if you downloaded yesterday. Good enough for a monthly workflow; not worth tracking download timestamps for this.

## Components

### `src/cashflow/downloaders/base.py`

Shared infrastructure:

- `connect_to_chrome(port=9222)` — Playwright CDP connection, shared across all downloaders. Never closes existing tabs; only creates new ones.
- `get_freshness(conn)` — returns `{institution: latest_date}` for all institutions with downloaders
- Error on connection failure: "Chrome not reachable on port 9222. Quit Chrome fully and relaunch with: `open -a 'Google Chrome' --args --remote-debugging-port=9222 --profile-directory='Profile 1'`" (note: must quit, not just open a new window)

### `src/cashflow/downloaders/paypal.py`

Full automation:

- Navigate to `https://www.paypal.com/reports/dlog`
- Set start date = latest PayPal transaction date (or 30 days ago if DB empty)
- Set end date = today
- Select CSV format
- Click "Create Report"
- Poll for completion every 2 seconds, timeout after 60 seconds
- Click download link when ready
- Return downloaded file path

### `src/cashflow/downloaders/chase.py`

Navigate-and-prompt:

- Open `https://secure.chase.com/web/auth/dashboard` in a new tab
- Print per-account guidance: "Chase Prime Visa stale since Mar 8. Chase Freedom stale since Mar 12. Download each card's activity as CSV."

### `src/cashflow/downloaders/bofa.py`

Navigate-and-prompt:

- Open `https://secure.bankofamerica.com/` in a new tab (can't deep-link past auth)
- Print: "BofA stale since Mar 12. Download checking (stmt*.csv) and credit card (*_NNNN.csv) separately."

### `src/cashflow/downloaders/capital_one.py`

Navigate-and-prompt:

- Open `https://myaccounts.capitalone.com/` in a new tab
- Print: "Capital One Venture stale since Mar 10. Capital One Wendy stale since Mar 15. Download each card separately. Include 'wendy' in filename for Wendy's card."

### `src/cashflow/downloaders/orchestrator.py`

Coordinator:

- Connect to Chrome once via CDP
- Query freshness for all institutions with downloaders
- Skip institutions fresh within 3 days
- Run PayPal downloader (automated)
- Open tabs for stale manual institutions with terminal guidance
- Start file watcher on `~/Downloads`
- File matching uses a shared `identify_file(filename)` function (extracted from `cli.py`'s routing logic) that returns the parser name or None. Ignores `.crdownload` and zero-byte files. Handles Chrome's `(1)`, `(2)` deduplication suffixes by stripping them before matching.
- As each CSV is detected: copy to a temp dir (don't move — leave original in Downloads), ingest via existing `store_transactions`
- Print running status showing which institutions are still pending
- On Ctrl+C or all received: run categorization + dedup (same as `cli.py` lines 134-154)
- Graceful shutdown on SIGINT: finish any in-progress ingest before exiting, never leave DB in partial state
- Timeout after 5 minutes of no new files, with prompt to continue or finish

### CLI changes

- Add `--download` flag to `cashflow ingest`
- `--download` and `--files` are composable: download runs first, then normal file-based ingest runs on `--files` if provided
- Without `--files`, downloaded files are ingested directly (no need to specify a directory)
- Post-processing (categorization, dedup, reconciliation) runs once at the end, not twice

### `identify_file(filename)` — shared parser routing

Extract the filename→parser routing logic from `cli.py` lines 88-129 into a shared function that both `cli.py` and the file watcher use. Returns a string like `"chase"`, `"paypal"`, `"bofa_checking"`, `"bofa_cc"`, `"capital_one:venture"`, `"capital_one:wendy"`, or `None`. This eliminates duplication and ensures the watcher matches the same patterns as manual ingest.

## Dependencies

- `playwright` — CDP connection and browser navigation. No browser binary install needed (connecting to existing Chrome). Heavyweight package but no lighter alternative supports CDP page navigation reliably.
- `watchdog` — filesystem monitoring for `~/Downloads`

## Not in scope

- Chrome launch management (user starts Chrome themselves)
- Credential storage or session management
- Deep-link navigation for BofA/Capital One (auth walls prevent it)
- Retry logic beyond Playwright's built-in waits
- Scheduled/background execution
- Downloaders for Target, Citi, Apple (could be added later with the same pattern)

## Testing

- Unit tests: `get_freshness`, `identify_file` (including Chrome's `(1)` suffix dedup), staleness threshold
- Manual integration test: run against live Chrome + PayPal session
- Existing parser and dedup tests remain unchanged

## Risks

- PayPal `/reports/dlog` page could redesign (low probability, stable for years)
- Chrome profile directory name (`Profile 1`) may differ — verify on first run
- `watchdog` triggers on partial downloads — filter `.crdownload` and zero-byte files
- PayPal report generation is async — 60s timeout with 2s polling
- Chrome must be fully quit and relaunched with debug port flag; opening a new window doesn't enable CDP
- An agent with CDP access to your authenticated banking session is a security surface; mitigated by the fact that this only runs locally, on demand, with your explicit invocation
