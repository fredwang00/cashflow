# cashflow — Household Financial Dashboard

Personal CLI tool + local HTML dashboard for the Wang family to track household burn rate, reconcile Amazon purchases, and stay on pace for annual financial goals.

## Problem

Tracking household finances requires manually cross-referencing Chase credit card statements, Amazon order histories (two accounts), bank statements, utility bills, and pay stubs — then typing numbers into a spreadsheet. Amazon is the worst offender: a single Chase line item like "AMAZON MKTPL*B80X61JB1 $44.52" gives no clue whether that's groceries, kids clothes, or electronics. The manual process takes hours per month and falls behind.

## Solution

An email-first ingestion pipeline that automatically collects financial data, reconciles Amazon orders to credit card charges using order numbers, and uses LLM-powered categorization that learns from corrections. The output is a SQLite database powering both a familiar Budget-vs-Actual spreadsheet view and a dashboard with burn rate tracking, surplus goals, and Amazon deep-dive.

## Design Decisions

- **Personal tool, not a product.** Hardcoded to the Wang family's specific card formats, Amazon accounts, and budget categories. No multi-tenant, no onboarding.
- **Email as primary data channel.** A dedicated Gmail address (`wangfamily-finance@gmail.com` or similar) receives forwarded receipts, bank transaction alerts, and billing emails. Gmail API polls it on a cron. This covers ~80% of transactions without manual work.
- **Bank CSVs as reconciliation layer.** Monthly CSV exports from Chase, Capital One, BofA, and Target card provide complete coverage. Email gives item-level detail; CSVs catch anything email missed.
- **Amazon order reports for item-level detail.** Amazon's "Download order reports" CSV export gives clean item-level data from both accounts. Combined with email receipts and Chase order numbers, this cracks the Amazon black box.
- **LLM categorization with learning.** Rules handle known merchants deterministically. Claude categorizes unknowns from product names/merchant descriptions. Corrections persist as new rules. The review queue shrinks over time.
- **Guardrails over rigid planning.** Monthly spending ceiling ($12k) and annual surplus goal ($40k) instead of requiring detailed sinking funds for every one-off. One-offs are tagged retroactively, not planned in advance. Optional sinking funds available when wanted.
- **Python CLI + SQLite + static HTML.** Same stack as the ECA project. SQLite is portable and queryable. Primary copy lives on Fred's MacBook; a read-only copy is synced to an always-on server for household dashboard access.

## Data Model (SQLite)

### Amount Convention

All amounts in the `transactions` table are **expenses as positive, credits/refunds as negative.** Income does NOT go through the transactions table — it has its own table. This keeps the surplus formula simple:

```
surplus = sum(income.amount) - sum(transactions.amount WHERE canonical_id IS NULL)
```

Refunds (negative amounts in transactions) naturally reduce the sum, increasing surplus. The `canonical_id IS NULL` filter is required on ALL queries against transactions to get deduplicated results.

### transactions
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| source_id | TEXT UNIQUE | Dedup key (e.g., email message ID, CSV row hash) |
| canonical_id | INTEGER FK | References transactions. If this row was matched to an existing transaction from another source, points to the canonical record. NULL if this is the canonical record. |
| date | DATE | Transaction date |
| amount | REAL | Positive = expense, negative = credit/refund. Income does NOT go here. |
| description | TEXT | Raw description from source |
| merchant | TEXT | Normalized merchant name |
| account_id | INTEGER FK | References accounts |
| category_id | INTEGER FK | References categories |
| is_one_off | BOOLEAN | Default false |
| one_off_label | TEXT | e.g., "Great Wolf Lodge family trip" |
| status | TEXT | pending / confirmed |
| confidence | INTEGER | 0-100, from rules or LLM |
| who | TEXT | fred / wife / shared |
| source_type | TEXT | email / csv / amazon_report / manual |
| created_at | DATETIME | |

The `canonical_id` self-reference handles cross-source linking. When a CSV row matches an existing email-sourced transaction, the CSV row's `canonical_id` points to the email record. Queries filter on `canonical_id IS NULL` to get deduplicated results while preserving the raw data from each source.

### amazon_items
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| transaction_id | INTEGER FK, nullable | References transactions. Many items per transaction. NULL if the Amazon order report was ingested before the corresponding Chase transaction — reconciliation back-fills this when the transaction arrives. |
| order_number | TEXT | e.g., 113-4380469-4633000 |
| item_name | TEXT | Full product name |
| price | REAL | Per-item price |
| order_date | DATE | |
| account | TEXT | fred / wife |
| category_id | INTEGER FK | Per-item category (can differ from transaction) |
| is_subscribe_save | BOOLEAN | |
| delivery_frequency | TEXT | e.g., "Every 3 months" |

### categories
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| name | TEXT | e.g., "Groceries", "Mortgage", "Kids Activities" |
| parent_id | INTEGER FK | Self-referential for hierarchy |
| type | TEXT | necessity / want |

Initial categories seeded from the 2025 budget spreadsheet (`~/Downloads/2025-budget.csv`):
- **Necessities:** Mortgage, Mom&Dad Payment, Auto Insurance, Gas & Fuel, Service & Parts, Nat Gas + Electricity, CVB Public Utility, Hampton Roads Sanitation, Verizon, AT&T, Term Life Insurance, Water Delivery, YouTube TV, YouTube Premium, Credit Card Fees
- **Wants:** Groceries, Fast Food, Restaurants, Kids Activities, Outschool, Clothing, Landscaping, Home Improvement, Soda Stream, Coffee, Shopping, Gifts, Birthdays & Holidays, Christmas
- **Subscriptions (sub-category of Wants):** CAROL Bike, Patreon, Crunchyroll, Google One, iCloud+, Amazon Prime, Audible, Ashby Payment, AppleCard Payment

Income sources (tracked in the `income` table, not categories): Fei Paycheck, Wife Paycheck, Bonus, Credit Card Rewards.

### accounts
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| name | TEXT | e.g., "Chase Prime Visa" |
| type | TEXT | credit / debit / cash |
| institution | TEXT | Chase / Capital One / BofA / Target |
| is_active | BOOLEAN | |

### budgets
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| category_id | INTEGER FK | |
| year | INTEGER | |
| month | INTEGER | 1-12 |
| amount | REAL | Budget target for that month |

UNIQUE constraint on `(category_id, year, month)`.

### merchant_rules
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| pattern | TEXT UNIQUE | Case-insensitive substring match against `transactions.merchant` |
| category_id | INTEGER FK | |
| source | TEXT | manual / learned |
| confidence | INTEGER | 0-100 |
| match_count | INTEGER | Times this rule has matched |

Patterns are simple substring matches (not regex) for predictability. Matched against the normalized `merchant` field. UNIQUE constraint on `pattern` — if a correction conflicts with an existing rule, the existing rule is updated.

### income

Income is tracked separately from transactions. Paychecks, bonuses, and other income never go into the `transactions` table. This avoids sign-convention confusion and keeps the surplus formula clean.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| source_id | TEXT UNIQUE | Dedup key |
| date | DATE | |
| amount | REAL | Always positive (net take-home) |
| source | TEXT | fei_paycheck / wife_paycheck / bonus / other |
| description | TEXT | |
| pay_period | TEXT | e.g., "2026-03-01 to 2026-03-15" |

### goals
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| name | TEXT | e.g., "Monthly Ceiling", "Annual Surplus" |
| type | TEXT | ceiling / surplus / sinking / invest |
| amount | REAL | Target amount |
| period | TEXT | monthly / yearly / NULL. NULL for sinking funds (use target_date instead). |
| target_date | DATE | For sinking funds. NULL for ceiling/surplus/invest. |

Goal progress is computed, not stored. All transaction queries include `WHERE canonical_id IS NULL`:
- **ceiling:** `sum(transactions.amount WHERE canonical_id IS NULL) for current month` vs `goal.amount`
- **surplus:** `sum(income.amount) - sum(transactions.amount WHERE canonical_id IS NULL) for YTD` vs `goal.amount`
- **invest:** `max(0, YTD_surplus - prorated_annual_surplus_goal)` — the excess beyond what's needed to hit the surplus target. If you're ahead of pace on the $40k goal, the overshoot is available for discretionary investing.
- **sinking:** `sum(income.amount) - sum(transactions.amount WHERE canonical_id IS NULL)` scoped from goal creation date to `target_date`. Shows progress toward a specific savings target by a specific date.

### ingest_state
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| source | TEXT | e.g., "gmail", "chase_csv" |
| last_sync | DATETIME | Last successful poll/import |
| cursor | TEXT | Gmail history ID or last processed filename |
| metadata | TEXT | JSON blob for source-specific state |

## Ingestion Pipeline

### Email Channel (primary, automated)

1. Gmail API polls dedicated inbox on cron (daily)
2. Per-sender parsers extract structured data:
   - **Amazon order confirmations:** item names, prices, order numbers, shipping address
   - **Bank transaction alerts:** amount, merchant, date, card
   - **Utility bills:** amount, billing period, account
   - **Subscription receipts:** service name, amount, billing period
3. Parsed transactions normalized and stored with `source_type = 'email'`

### Bank CSV Channel (monthly manual drop)

1. Download CSV/OFX from Chase, Capital One, BofA, Target
2. Drop files in `~/cashflow/inbox/`
3. Per-bank parsers normalize column formats
4. Reconcile against existing email-sourced transactions:
   - Match on amount + date proximity + merchant similarity
   - For Amazon: match on order number (embedded in Chase CSV descriptions)
5. New transactions from CSV fill gaps where email was missed
6. Conflicts flagged for manual review

### Amazon Reports Channel (periodic manual drop)

1. Download order reports CSV from both Amazon accounts
2. Drop in `~/cashflow/inbox/`
3. Parse item-level detail: item name, price, order number, date
4. Match to Chase transactions via order number
5. Enrich transactions with item names for categorization
6. Flag multi-item orders (1 Chase charge = N items, potentially different categories)

### PDF Statement Channel (deferred fallback)

PDF parsing is significantly harder than CSV parsing and all the same banks offer CSV exports. This channel is deferred — implement only if a data source lacks CSV export.

1. Drop PDFs in `~/cashflow/inbox/`
2. Parse using pdfplumber with per-bank layout templates
3. Extract transaction rows (date, description, amount, order number)
4. Feed into same reconciliation pipeline

### Reconciliation Engine

Two layers of deduplication:

**Same-source dedup:** The `source_id` unique constraint prevents ingesting the same record twice (e.g., re-importing the same CSV).

**Cross-source linking:** When a new record from source B matches an existing record from source A, the new record is inserted with `canonical_id` pointing to the existing record. Queries use `WHERE canonical_id IS NULL` to get deduplicated results. The raw data from both sources is preserved for debugging.

Matching strategies:
- **Order numbers** (Amazon emails/reports ↔ Chase CSV/PDF) — strongest signal, exact match
- **Amount + date proximity** (email alerts ↔ CSV line items) — within ±2 days, exact amount match
- **Amount + date + merchant similarity** — fallback fuzzy match, lower confidence

**Amazon-specific constraint:** Amazon purchases are exclusively on the Chase Prime Visa card. Order numbers appear in Chase transaction descriptions (e.g., "AMAZON MKTPL*B80X61JB1 Order Number 113-4380469-4633000"). This is the primary join key for Amazon reconciliation. Note: order number extraction from Chase descriptions is best-effort — some transaction types (digital orders, Subscribe & Save consolidation) may truncate or omit the order number. Unmatched Amazon items are surfaced in the review queue.

**Amazon tax/shipping discrepancy:** Amazon item prices from order reports exclude tax and sometimes shipping. The sum of `amazon_items.price` for a transaction will typically be less than `transactions.amount`. The difference is attributed to tax/shipping and is not separately categorized.

## Categorization Engine

1. **Rules check** — scan `merchant_rules` for pattern match. Deterministic, instant. "Whole Foods" → Groceries, "CAROL Bike" → Subscription.
2. **LLM categorize** — for unmatched transactions, send merchant name + amount (or Amazon product name) to Claude with the category list. Returns category + confidence score.
3. **Auto-accept or queue** — confidence ≥ 90 auto-applies with `status = 'confirmed'`. Lower confidence sets `status = 'pending'` for review.
4. **Learn** — when user confirms or corrects a categorization, create/update a `merchant_rules` entry. Subscribe & Save items and recurring merchants learn permanently after one correction.

For Amazon multi-item orders: each `amazon_item` gets its own `category_id`. The parent transaction's category is set to the highest-value item's category, or to a catch-all "Amazon - Mixed" category if items span multiple categories. "Amazon - Mixed" should be included in the seed categories as a child of Wants.

## CLI Interface

```
cashflow ingest --email          # Poll Gmail, process new emails
cashflow ingest --files PATH     # Process CSVs/PDFs from inbox
cashflow ingest --auto           # Both (used by cron)

cashflow review                  # Interactive: approve/correct pending transactions
cashflow status                  # Month snapshot + YTD progress

cashflow dashboard               # Open HTML dashboard in browser

cashflow plan NAME --amount N --by DATE   # Create sinking fund goal
cashflow tag ID --one-off "label"         # Tag transaction as one-off
cashflow goal                             # List and manage goals
```

### `cashflow status` output

```
March 2026: $8,241 / $12,000 ceiling (68%) — 17 days left
YTD surplus: $14,820 / $40,000 goal (37%) — on pace for $38,200
Discretionary investing: $3,200 / $18,000 goal (18%) — on pace for $16,400
Review queue: 3 items
```

## Dashboard Views

### Monthly Pulse
- Current month burn rate vs spending ceiling (green/yellow/red)
- Spending by category (bar chart)
- Budget vs Actual per category
- Days remaining + projected month-end total
- Comparison to prior month

### Year Tracker
- YTD surplus vs annual goal with projection
- Monthly surplus trend line
- Rolling 3-month average burn rate
- Baseline burn vs one-off burn split (so a big month doesn't cause panic if the average is fine)
- Projected year-end surplus

### Amazon Deep Dive
- Amazon spending broken down by real category (not just "Amazon")
- Subscribe & Save recurring total and item list
- Fred's account vs wife's account split
- Item-level transaction list with search
- Month-over-month Amazon trend

### Budget Grid
- The familiar spreadsheet: Budget vs Actual per month per category
- Auto-populated from transaction data
- Income row, Necessities section, Wants section, Difference row
- Matches the structure of the existing 2025-budget.csv

### Subscriptions
- All recurring charges consolidated
- Total monthly subscription burn
- Flag potential duplicates (Google One 2TB + iCloud+ 2TB)
- Flag unused services where detectable
- History of subscription cost changes

### Review Queue
- Pending transactions needing categorization
- LLM's suggested category with confidence
- One-click approve or dropdown to recategorize
- Bulk approve for high-confidence batches
- Shrinks over time as merchant_rules grows

## Deployment Architecture

Fred's MacBook Pro is the primary workstation — all writes (ingestion, review, categorization, tagging) happen here against a local SQLite database. The dashboard is served from an always-on machine so both Fred and his wife can view it from any device on the LAN.

### Machines

| Machine | Role |
|---------|------|
| Fred's MacBook Pro | CLI workstation. Local SQLite. All writes happen here. |
| Proxmox PC or Mac Mini | Dashboard server. Serves read-only dashboard to the LAN. |
| Synology DS1525+ NAS | Shared `inbox/` drop zone for CSV/PDF files. |
| Wife's MacBook Pro | Dashboard viewer only. |

### Data Flow

```
Fred's MacBook Pro (writer)
├── cashflow CLI (all commands)
├── cashflow.db (SQLite, primary copy)
├── cron: cashflow ingest --auto (email polling)
└── post-write hook: rsync cashflow.db → server

Server (Proxmox container or Mac Mini)
├── cashflow.db (read-only synced copy)
├── dashboard server (FastAPI)
│   ├── GET /                  → dashboard HTML
│   ├── GET /api/status        → month + YTD summary
│   ├── GET /api/monthly/:m    → month detail
│   ├── GET /api/amazon        → Amazon deep dive
│   ├── GET /api/budgets       → Budget grid data
│   ├── GET /api/subscriptions → recurring charges
│   ├── POST /api/ask          → text-to-SQL (Phase 2)
│   └── GET /api/briefing      → latest weekly briefing (Phase 2)
└── accessible at http://cashflow.local:8080

NAS (Synology DS1525+)
└── /cashflow/inbox/  → shared drop zone
    Wife can drop CSVs here too
    Fred's MacBook mounts this via SMB
```

### Sync Mechanism

After any CLI command that writes to SQLite, a post-command hook runs:

```bash
rsync -az ~/.cashflow/cashflow.db server:/opt/cashflow/cashflow.db
```

This is ~1 second for a typical SQLite file. The dashboard reads from the synced copy, so there's a few-second delay after writes before the dashboard reflects changes. Acceptable for a household dashboard.

The `cashflow` CLI wraps this as a built-in post-write sync:
```
cashflow ingest --auto    # ingests, then syncs
cashflow review           # categorizes, then syncs
cashflow tag ...          # tags, then syncs
```

`cashflow status` and `cashflow dashboard` (when run locally) do NOT trigger sync since they're read-only.

### Dashboard Server

A minimal FastAPI app that:
1. Opens `cashflow.db` in read-only mode (`sqlite3.connect("file:cashflow.db?mode=ro", uri=True)`)
2. Serves static HTML/JS/CSS for the dashboard
3. Exposes read-only JSON API endpoints for chart data
4. Runs as a systemd service (Proxmox) or launchd plist (Mac Mini)

No authentication needed — this is LAN-only behind the home router. The dashboard server has zero write capability to SQLite.

The server needs an `ANTHROPIC_API_KEY` environment variable for Phase 2 endpoints (`/api/ask`). The briefing cron runs on Fred's MacBook (which already has the key), not the server.

### Offline Resilience

If the server or NAS is down:
- Fred can still run all CLI commands locally (SQLite is on his MacBook)
- Sync will fail silently and retry on the next command
- Dashboard is unavailable to wife until server is back
- NAS being down just means the shared inbox isn't available — CSVs can be dropped locally instead

## Phase 2: Intelligence Layer

Phase 1 is the capture-and-display pipeline: ingestion, reconciliation, categorization, dashboard, and CLI. Once that's working with real data and trained merchant rules, Phase 2 adds two features that make the data actively useful rather than passively available. Both are read-only consumers of the existing SQLite database. Neither changes the data model or architecture from Phase 1 (one small table addition for briefing history).

### `cashflow ask` — Natural Language Queries

Ad-hoc text-to-SQL powered by Claude. Answers questions the pre-built dashboard views can't.

**CLI:**
```
$ cashflow ask "how much did we spend on kids birthday parties vs christmas in 2025?"

SQL: SELECT c.name, SUM(t.amount) as total FROM transactions t
     JOIN categories c ON t.category_id = c.id
     WHERE c.name IN ('Birthdays & Holidays', 'Christmas')
     AND strftime('%Y', t.date) = '2025' AND t.canonical_id IS NULL
     GROUP BY c.name

CATEGORY             | TOTAL
Birthdays & Holidays | $2,340.00
Christmas            | $4,127.50
```

```
$ cashflow ask "what are our top 10 amazon subscribe and save items by annual cost?"
$ cashflow ask "which months did we exceed the 12k ceiling this year?"
$ cashflow ask "how much more are we spending on groceries vs last year?"
```

**Dashboard:** A search bar at the top of the dashboard at `cashflow.local:8080`. Wife types a question, the server sends it to Claude, executes the read-only SQL, and renders the results as a table. This is the primary way she interrogates the data without needing CLI access or asking Fred to write queries.

**Implementation:**
- Claude receives the full SQLite schema + conventions (amount sign, canonical_id dedup, income table separation) as a system prompt
- Claude returns only raw SQL, no explanation
- SQL is executed against SQLite in read-only mode (`?mode=ro`) — even if Claude hallucinates a write query, SQLite blocks it
- Results displayed as a formatted table (CLI) or rendered in the browser (dashboard)
- The generated SQL is shown to the user for transparency

**Dashboard API endpoint:**
```
POST /api/ask  { "question": "..." }  →  { "sql": "...", "columns": [...], "rows": [...] }
```

### `cashflow briefing` — Weekly Financial Pulse

A push-based weekly summary that arrives in both partners' inboxes. Solves the "dashboards rot" problem — the briefing comes to you, you don't have to remember to check anything.

**CLI:**
```
$ cashflow briefing                # Generate and display in terminal
$ cashflow briefing --send         # Generate and email to both partners
```

**Example output:**
```
Week of March 9-15, 2026

You spent $2,840 this week, putting March at $8,241 so far — 68% of your
$12k ceiling with 17 days left. On pace.

YTD surplus is $14,820 against the $40k goal. You're slightly behind pace
($15,400 expected by now) — January's Steelcase chair ($535) and Mac Mini
($545) pushed that month over. February recovered well.

Notable this week: two Seagate IronWolf Pro 12TB drives ($636 total) hit
the Chase Prime card. Tagged as Electronics. One-off or NAS build?

Your Subscribe & Save total crept up to $187/month — you added creatine
powder in February. Running total for the year: $1,120 across 14 items.

Review queue: 3 items waiting.
```

**How it works:**
1. `cashflow briefing` queries the database for: this week's transactions, MTD category totals vs budget, YTD surplus pace, notable one-offs, new Subscribe & Save items, review queue size
2. Structures the data as a JSON payload
3. Sends it to Claude with a system prompt: "Write a 150-word household money memo for a busy two-parent family. Flag anomalies, state whether they're on pace, highlight the single biggest discretionary lever for the rest of the month. Conversational tone, no jargon, no charts."
4. Stores the result in a `briefings` table for historical record
5. With `--send`, emails the briefing to both partners. Uses SMTP (Gmail app password) rather than Gmail API, since the Gmail API is configured for read-only polling of the finance inbox. Sending email is a different OAuth scope and SMTP is simpler for outbound-only.

**Cron:** Runs Sunday evening so both partners start the week informed.

```
0 18 * * 0  cashflow briefing --send
```

**Data model addition:**

### briefings
| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | |
| date | DATE | Week-ending date |
| content | TEXT | The generated briefing text |
| data_snapshot | TEXT | JSON of the structured data fed to Claude |
| created_at | DATETIME | |

**Dashboard integration:** The latest briefing is displayed on the dashboard landing page at `cashflow.local:8080`. Historical briefings are browsable — a lightweight financial journal generated from your own data.

**Dashboard API endpoint:**
```
GET /api/briefing          →  latest briefing
GET /api/briefings         →  list of all briefings
```

### Why these two together

They serve complementary moments:
- **Briefing** is for when you haven't been paying attention — it catches you up proactively, weekly, no effort required
- **Ask** is for when you have a specific question — it answers instantly, on-demand, without pre-built views

Both use the same Claude API already in the stack for categorization. Both are read-only against the same SQLite database. Both work from the dashboard (wife) and CLI (Fred). Neither changes the ingestion pipeline, data model (except one small table), or deployment architecture.

## Out of Scope

- **Tax estimation / planning.** ESPP, NSO, capital gains, bracket math — separate concern, separate tool.
- **Investment portfolio tracking.** Brokerage positions, covered calls, swing trading — handled by separate trading software.
- **Multi-household / product features.** No onboarding, no accounts, no sharing.
- **Plaid / bank API integration.** Maybe later, but manual CSV + email covers the need without the cost and complexity.
- **Mobile app.** Dashboard is accessible from any browser on the LAN, including phones on home WiFi.

## Tech Stack

- **Language:** Python 3.12+
- **CLI framework:** Click
- **Database:** SQLite (local on Fred's MacBook, synced read-only copy on server)
- **Email:** Gmail API (google-api-python-client)
- **LLM:** Anthropic Claude API (anthropic SDK)
- **Dashboard server:** FastAPI (uvicorn), read-only SQLite access
- **Dashboard frontend:** Static HTML/JS/CSS (vanilla JS + Chart.js or similar)
- **Sync:** rsync over SSH
- **CSV parsing:** stdlib csv module with per-bank format configs
- **PDF parsing:** pdfplumber (deferred)
