# Plan 3b: Bank of America Parsers (Credit Card + Checking with Income)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse BofA credit card CSVs and checking account CSVs. The checking parser extracts both expenses AND income (Spotify paycheck deposits), populating the `income` table so `cashflow status` shows real surplus numbers.

**Architecture:** Two parsers: one for BofA credit cards (same structure, different last-4 digits), one for checking (has a summary header to skip, mixed income/expense). The checking parser detects Spotify deposits and routes them to the `income` table via a new `store_income` function. Everything else follows the existing ingestion pattern.

**Tech Stack:** Python 3.12+, Click, SQLite, pytest

**Depends on:** Plan 3 (complete — 74 tests passing)

---

## New Files

```
src/cashflow/
├── parsers/
│   ├── bofa_cc.py             # BofA credit card CSV parser
│   └── bofa_checking.py       # BofA checking CSV parser (income + expenses)
├── (db.py modified)           # Add store_income function
└── (cli.py modified)          # Wire new parsers into ingest

tests/
├── test_bofa_cc_parser.py
├── test_bofa_checking_parser.py
├── test_income.py
└── fixtures/
    ├── bofa_cc_sample.csv
    └── bofa_checking_sample.csv
```

---

## Chunk 1: BofA Credit Card Parser

### Task 1: BofA Credit Card Parser

BofA credit card CSV format:
```
Posted Date,Reference Number,Payee,Address,Amount
03/14/2026,24445726072300602934358,"KROGER #539 800-853-3033 VA","800-853-3033  VA ",-41.76
```

- Date: `MM/DD/YYYY`
- Amount: negative = purchases, positive = payments (same convention as Chase)
- Two cards: files ending in `_8690.csv` and `_9341.csv` — both use the same format
- Payee field has the merchant name
- Reference Number is unique per transaction (good for source_id)

**Files:**
- Create: `tests/fixtures/bofa_cc_sample.csv`
- Create: `src/cashflow/parsers/bofa_cc.py`
- Create: `tests/test_bofa_cc_parser.py`
- Modify: `src/cashflow/cli.py`

- [ ] **Step 1: Create fixture**

Create `tests/fixtures/bofa_cc_sample.csv`:
```csv
Posted Date,Reference Number,Payee,Address,Amount
03/14/2026,24445726072300602934358,"KROGER #539 800-853-3033 VA","800-853-3033  VA ",-41.76
03/13/2026,24011346072100057638046,"SP COUNTER CULTURE COUNTERCULTURNC","COUNTERCULTUR NC ",-37.37
03/10/2026,24027626068067534602130,"PAYPAL *WINSORPIANO 402-935-7733 CA","402-935-7733  CA ",-300.00
03/09/2026,74445726065300891107355,"KROGER #539 VIRGINIA BEACVA","VIRGINIA BEAC VA ",8.06
03/07/2026,24000976065369400698306,"ZUSHI JAPANESE BISTRO 757-3211495 VA","757-3211495   VA ",-120.00
03/05/2026,24692166063107752481928,"APPLE.COM/BILL 866-712-7753 CA","866-712-7753  CA ",-9.99
02/19/2026,05083204320021900084134,"PAYMENT - THANK YOU","",2744.61
04/10/2025,74208475099100025661041,"CAROL BIKE LONDON","",-15.00
```

Covers: purchases (negative), a refund/credit (positive 8.06), a payment (positive 2744.61), and a subscription (CAROL BIKE).

- [ ] **Step 2: Write failing tests**

```python
# tests/test_bofa_cc_parser.py
from pathlib import Path
from cashflow.parsers.bofa_cc import parse_bofa_cc_csv

FIXTURE = Path(__file__).parent / "fixtures" / "bofa_cc_sample.csv"


def test_parse_bofa_cc_returns_transactions():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_bofa_cc_skips_payments():
    txns = parse_bofa_cc_csv(FIXTURE)
    descriptions = [t.description for t in txns]
    assert not any("PAYMENT - THANK YOU" in d for d in descriptions)


def test_parse_bofa_cc_flips_sign_for_purchases():
    txns = parse_bofa_cc_csv(FIXTURE)
    kroger = [t for t in txns if "KROGER" in t.description and t.amount > 0]
    assert len(kroger) >= 1
    assert kroger[0].amount == 41.76


def test_parse_bofa_cc_keeps_refunds_as_negative():
    """Positive amounts in BofA (that aren't payments) are refunds — flip to negative."""
    txns = parse_bofa_cc_csv(FIXTURE)
    refunds = [t for t in txns if t.amount < 0]
    assert len(refunds) == 1
    assert refunds[0].amount == -8.06


def test_parse_bofa_cc_extracts_merchant():
    txns = parse_bofa_cc_csv(FIXTURE)
    # Should clean up the payee field
    assert any("Kroger" in t.merchant for t in txns)


def test_parse_bofa_cc_source_id_uses_reference():
    txns = parse_bofa_cc_csv(FIXTURE)
    # Reference number should be part of source_id for uniqueness
    assert all("bofa-cc-" in t.source_id for t in txns)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_bofa_cc_sets_account_name():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert all(t.account_name == "Bank of America" for t in txns)


def test_parse_bofa_cc_parses_dates():
    txns = parse_bofa_cc_csv(FIXTURE)
    carol = [t for t in txns if "CAROL" in t.description][0]
    assert str(carol.date) == "2025-04-10"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_bofa_cc_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement parser**

```python
# src/cashflow/parsers/bofa_cc.py
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from cashflow.models import ParsedTransaction

MERCHANT_PATTERNS = [
    (re.compile(r"KROGER", re.IGNORECASE), "Kroger"),
    (re.compile(r"CAROL BIKE", re.IGNORECASE), "CAROL Bike"),
    (re.compile(r"APPLE\.COM/BILL", re.IGNORECASE), "Apple"),
    (re.compile(r"STARBUCKS", re.IGNORECASE), "Starbucks"),
    (re.compile(r"WALMART", re.IGNORECASE), "Walmart"),
    (re.compile(r"WEGMANS", re.IGNORECASE), "Wegmans"),
    (re.compile(r"COSTCO", re.IGNORECASE), "Costco"),
    (re.compile(r"HOME DEPOT", re.IGNORECASE), "Home Depot"),
    (re.compile(r"UBER", re.IGNORECASE), "Uber"),
    (re.compile(r"DOLLARTREE", re.IGNORECASE), "Dollar Tree"),
    (re.compile(r"OPENAI.*CHATGPT", re.IGNORECASE), "ChatGPT"),
    (re.compile(r"Google YouTube", re.IGNORECASE), "YouTube"),
    (re.compile(r"PANERA", re.IGNORECASE), "Panera Bread"),
    (re.compile(r"H&M ", re.IGNORECASE), "H&M"),
    (re.compile(r"JCPENNEY", re.IGNORECASE), "JCPenney"),
    (re.compile(r"NYTIMES", re.IGNORECASE), "NY Times"),
]


def _normalize_merchant(payee: str) -> str:
    for pattern, name in MERCHANT_PATTERNS:
        if pattern.search(payee):
            return name
    # Fallback: take payee up to first phone number or state abbreviation
    cleaned = re.split(r"\d{3}-\d{3}-\d{4}|\d{3}-\d{7}|\s{2,}", payee)[0].strip()
    return cleaned if cleaned else payee


def _make_source_id(row: dict) -> str:
    raw = f"{row['Posted Date']}|{row['Reference Number']}|{row['Amount']}"
    return f"bofa-cc-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_bofa_cc_csv(path: Path) -> list[ParsedTransaction]:
    """Parse a BofA credit card CSV export.

    BofA uses negative for purchases, positive for payments/credits.
    Payments (large positive, "PAYMENT - THANK YOU") are skipped.
    Refunds/credits (small positive) are kept as negative amounts.
    Purchases are flipped to positive (our spec convention).
    """
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount = float(row["Amount"])
            payee = row["Payee"].strip().strip('"')

            # Skip payments
            if "PAYMENT" in payee.upper() and amount > 0:
                continue

            # Flip sign: BofA negative purchase -> positive expense
            # BofA positive refund -> negative credit
            amount = -amount

            txn_date = datetime.strptime(row["Posted Date"], "%m/%d/%Y").date()

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=payee,
                    merchant=_normalize_merchant(payee),
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Bank of America",
                )
            )

    return transactions
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_bofa_cc_parser.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Wire into CLI**

Read `src/cashflow/cli.py` first. Add import:
```python
from cashflow.parsers.bofa_cc import parse_bofa_cc_csv
```

In the ingest file processing loop, add an `elif` branch for BofA CC files. BofA CC files are named like `April2025_8690.csv`, `February2026_9341.csv` — detect by the `_8690` or `_9341` suffix pattern:

```python
        elif re.search(r"_\d{4}\.csv$", csv_file.name, re.IGNORECASE):
            txns = parse_bofa_cc_csv(csv_file)
```

Add `import re` at top of cli.py if not already there.

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/cashflow/parsers/bofa_cc.py tests/test_bofa_cc_parser.py tests/fixtures/bofa_cc_sample.csv src/cashflow/cli.py
git commit -m "feat: BofA credit card CSV parser"
```

---

## Chunk 2: Income Storage + BofA Checking Parser

### Task 2: Store Income Function

**Files:**
- Modify: `src/cashflow/db.py`
- Create: `tests/test_income.py`

- [ ] **Step 1: Write failing tests for income storage**

```python
# tests/test_income.py
from datetime import date
from cashflow.seed import seed_all
from cashflow.db import store_income
from cashflow.queries import get_ytd_income, get_ytd_surplus


def test_store_income_inserts_rows(db):
    seed_all(db)
    income_records = [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck",
         "description": "SPOTIFY USA INC DIRECT DEP", "source_id": "bofa-chk-abc123"},
    ]
    stored = store_income(db, income_records)
    assert stored == 1
    row = db.execute("SELECT * FROM income").fetchone()
    assert row["amount"] == 7584.14
    assert row["source"] == "fei_paycheck"


def test_store_income_skips_duplicates(db):
    seed_all(db)
    records = [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck",
         "description": "SPOTIFY", "source_id": "bofa-chk-abc123"},
    ]
    store_income(db, records)
    stored = store_income(db, records)
    assert stored == 0


def test_income_shows_in_ytd_surplus(db):
    seed_all(db)
    records = [
        {"date": date(2026, 1, 15), "amount": 7584.14, "source": "fei_paycheck",
         "description": "SPOTIFY", "source_id": "bofa-chk-1"},
        {"date": date(2026, 1, 30), "amount": 7584.14, "source": "fei_paycheck",
         "description": "SPOTIFY", "source_id": "bofa-chk-2"},
    ]
    store_income(db, records)
    income = get_ytd_income(db, 2026)
    assert income == 15168.28
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_income.py -v`
Expected: FAIL — `cannot import name 'store_income'`

- [ ] **Step 3: Implement store_income**

Add to `src/cashflow/db.py` (after `store_transactions`):

```python
def store_income(conn: sqlite3.Connection, records: list[dict]) -> int:
    """Store income records. Returns count of newly inserted rows.

    Each record is a dict with: date, amount, source, description, source_id.
    Skips duplicates (same source_id).
    """
    inserted = 0
    for rec in records:
        try:
            conn.execute(
                "INSERT INTO income (source_id, date, amount, source, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec["source_id"], rec["date"].isoformat(), rec["amount"],
                 rec["source"], rec.get("description", "")),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_income.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/cashflow/db.py tests/test_income.py
git commit -m "feat: store_income function for paycheck and income data"
```

---

### Task 3: BofA Checking Parser

BofA checking CSV format:
```
Description,,Summary Amt.
Beginning balance as of 01/01/2025,,"20,979.07"
Total credits,,"356,900.29"
Total debits,,"-369,906.77"
Ending balance as of 03/16/2026,,"7,972.59"

Date,Description,Amount,Running Bal.
01/02/2025,"NEWREZ-SHELLPOIN DES:ACH PMT...",-3450.37,"17,528.70"
01/15/2025,"SPOTIFY USA INC DES:DIRECT DEP...","7,421.60","18,431.79"
```

Key challenges:
- 5-line summary header before the real data (skip until `Date,Description,Amount,Running Bal.`)
- Amounts have commas in thousands (quoted strings)
- Both income (positive: Spotify deposits) and expenses (negative: bills)
- Inter-account transfers should be excluded (they're not real income or expenses)
- Paycheck detection: "SPOTIFY USA INC" + "DIRECT DEP" in description

**Files:**
- Create: `tests/fixtures/bofa_checking_sample.csv`
- Create: `src/cashflow/parsers/bofa_checking.py`
- Create: `tests/test_bofa_checking_parser.py`
- Modify: `src/cashflow/cli.py`

- [ ] **Step 1: Create fixture**

Create `tests/fixtures/bofa_checking_sample.csv`:
```csv
Description,,Summary Amt.
Beginning balance as of 01/01/2026,,"20,000.00"
Total credits,,"30,000.00"
Total debits,,"-25,000.00"
Ending balance as of 03/16/2026,,"25,000.00"

Date,Description,Amount,Running Bal.
01/02/2026,"NEWREZ-SHELLPOIN DES:ACH PMT ID:XXXXX73355 INDN:WANG FEI CO ID:XXXXX42226 PPD","-3,450.37","16,549.63"
01/07/2026,"DOMINION ENERGY DES:BILLPAY ID:XXXXX0791464 INDN:FEI WANG CO ID:XXXXX00160 PPD","-199.45","16,350.18"
01/13/2026,"Online Banking transfer to CHK 1797 Confirmation# XXXXX39415","-5,000.00","11,350.18"
01/15/2026,"SPOTIFY USA INC DES:DIRECT DEP ID:XXXXX62947558CC INDN:WANG,FEI CO ID:XXXXX11101 PPD","7,421.60","18,771.78"
01/15/2026,"SPOTIFY USA INC DES:DIRECT DEP ID:XXXXX62947548CC INDN:WANG,FEI CO ID:XXXXX11101 PPD","1,480.42","20,252.20"
01/15/2026,"Zelle payment to Ping Wang Conf# cktp231rh","-1,107.97","19,144.23"
01/17/2026,"CHASE CREDIT CRD DES:AUTOPAY ID:XXXXXXXXXX11834 INDN:WANG FEI CO ID:XXXXX39224 PPD","-2,418.80","16,725.43"
01/17/2026,"Interest Earned","0.18","16,725.61"
01/22/2026,"MSPBNA BANK DES:TRANSFER ID:XXXXXXXXXX96930 INDN:WANG,FEI CO ID:XXXXX50001 PPD","10,000.00","26,725.61"
```

Covers: mortgage, utility, inter-account transfer, Spotify paychecks (2 deposits), Zelle to parents, credit card autopay, interest, brokerage transfer.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_bofa_checking_parser.py
from pathlib import Path
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv

FIXTURE = Path(__file__).parent / "fixtures" / "bofa_checking_sample.csv"


def test_parse_returns_expenses_and_income():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    assert len(expenses) > 0
    assert len(income) > 0


def test_parse_skips_summary_header():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Beginning balance" in d for d in all_descs)


def test_parse_extracts_spotify_as_income():
    _, income = parse_bofa_checking_csv(FIXTURE)
    spotify = [r for r in income if "SPOTIFY" in r["description"]]
    assert len(spotify) == 2
    amounts = sorted([r["amount"] for r in spotify])
    assert amounts == [1480.42, 7421.60]


def test_parse_income_source_is_fei_paycheck():
    _, income = parse_bofa_checking_csv(FIXTURE)
    assert all(r["source"] == "fei_paycheck" for r in income)


def test_parse_skips_inter_account_transfers():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Online Banking transfer" in d for d in all_descs)


def test_parse_skips_credit_card_payments():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    descs = [t.description for t in expenses]
    assert not any("CREDIT CRD" in d or "AUTOPAY" in d for d in descs)


def test_parse_skips_brokerage_transfers():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("MSPBNA BANK" in d for d in all_descs)


def test_parse_keeps_real_expenses():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    merchants = [t.merchant for t in expenses]
    assert any("Newrez" in m or "Mortgage" in m for m in merchants)
    assert any("Dominion" in m for m in merchants)


def test_parse_keeps_zelle_as_expense():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    zelle = [t for t in expenses if "Zelle" in t.description or "Ping Wang" in t.description]
    assert len(zelle) == 1
    assert zelle[0].amount == 1107.97


def test_parse_handles_comma_amounts():
    _, income = parse_bofa_checking_csv(FIXTURE)
    big = [r for r in income if r["amount"] == 7421.60]
    assert len(big) == 1


def test_parse_skips_interest_earned():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Interest Earned" in d for d in all_descs)


def test_parse_sets_account_name():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    assert all(t.account_name == "Checking" for t in expenses)


def test_parse_source_ids_unique():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_ids = [t.source_id for t in expenses] + [r["source_id"] for r in income]
    assert len(all_ids) == len(set(all_ids))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_bofa_checking_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement parser**

```python
# src/cashflow/parsers/bofa_checking.py
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from cashflow.models import ParsedTransaction

# Patterns for transactions to SKIP (not real household expenses/income)
SKIP_PATTERNS = [
    re.compile(r"Online Banking transfer", re.IGNORECASE),
    re.compile(r"CREDIT CRD.*AUTOPAY", re.IGNORECASE),
    re.compile(r"CHASE CREDIT CRD", re.IGNORECASE),
    re.compile(r"APPLECARD GSBANK.*PAYMENT", re.IGNORECASE),
    re.compile(r"CAPITAL ONE.*CRCARDPMT", re.IGNORECASE),
    re.compile(r"BANK OF AMERICA CREDIT CARD", re.IGNORECASE),
    re.compile(r"AMERICAN EXPRESS.*ACH PMT", re.IGNORECASE),
    re.compile(r"MSPBNA BANK.*TRANSFER", re.IGNORECASE),
    re.compile(r"Interest Earned", re.IGNORECASE),
    re.compile(r"Beginning balance", re.IGNORECASE),
]

# Patterns for INCOME detection
INCOME_PATTERNS = [
    (re.compile(r"SPOTIFY USA INC.*DIRECT DEP", re.IGNORECASE), "fei_paycheck"),
]

MERCHANT_PATTERNS = [
    (re.compile(r"NEWREZ|SHELLPOIN", re.IGNORECASE), "Newrez Mortgage"),
    (re.compile(r"DOMINION ENERGY", re.IGNORECASE), "Dominion Energy"),
    (re.compile(r"ATT\b.*Payment", re.IGNORECASE), "AT&T"),
    (re.compile(r"NATIONWIDE.*EDI PYMNTS", re.IGNORECASE), "Nationwide Insurance"),
    (re.compile(r"MASS MUTUAL", re.IGNORECASE), "MassMutual Insurance"),
    (re.compile(r"Zelle payment to", re.IGNORECASE), "Zelle"),
    (re.compile(r"VENMO", re.IGNORECASE), "Venmo"),
    (re.compile(r"VIRGINIA BEACH.*WATER", re.IGNORECASE), "VB Water"),
    (re.compile(r"VirginiaNaturalG", re.IGNORECASE), "Virginia Natural Gas"),
    (re.compile(r"HAMPTON ROADS SANITATION", re.IGNORECASE), "HRSD"),
]


def _normalize_merchant(description: str) -> str:
    for pattern, name in MERCHANT_PATTERNS:
        if pattern.search(description):
            return name
    # Fallback: first recognizable word chunk
    cleaned = re.split(r"\s+DES:", description)[0].strip()
    return cleaned if cleaned else description


def _make_source_id(date_str: str, description: str, amount_str: str) -> str:
    raw = f"{date_str}|{description[:50]}|{amount_str}"
    return f"bofa-chk-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _parse_amount(amount_str: str) -> float:
    """Parse BofA amount strings like '7,421.60' or '-3,450.37'."""
    return float(amount_str.replace(",", ""))


def _should_skip(description: str) -> bool:
    return any(p.search(description) for p in SKIP_PATTERNS)


def _detect_income(description: str) -> str | None:
    """Returns income source type if this is an income transaction, else None."""
    for pattern, source in INCOME_PATTERNS:
        if pattern.search(description):
            return source
    return None


def parse_bofa_checking_csv(path: Path) -> tuple[list[ParsedTransaction], list[dict]]:
    """Parse a BofA checking account CSV.

    Returns (expenses, income_records).
    - expenses: list of ParsedTransaction (positive = expense)
    - income_records: list of dicts ready for store_income()

    Skips inter-account transfers, credit card payments, brokerage transfers,
    and interest. Detects Spotify direct deposits as income.
    """
    expenses = []
    income_records = []

    with open(path, newline="", encoding="utf-8") as f:
        # Skip summary header — find the real header line
        for line in f:
            if line.startswith("Date,Description"):
                break
        else:
            return expenses, income_records

        reader = csv.DictReader(f, fieldnames=["Date", "Description", "Amount", "Running Bal."])
        for row in reader:
            if not row["Date"] or not row["Amount"]:
                continue

            description = row["Description"].strip().strip('"')
            amount_str = row["Amount"].strip().strip('"')
            date_str = row["Date"].strip()

            if _should_skip(description):
                continue

            amount = _parse_amount(amount_str)
            txn_date = datetime.strptime(date_str, "%m/%d/%Y").date()
            source_id = _make_source_id(date_str, description, amount_str)

            # Check if this is income
            income_source = _detect_income(description)
            if income_source and amount > 0:
                income_records.append({
                    "date": txn_date,
                    "amount": amount,
                    "source": income_source,
                    "description": description,
                    "source_id": source_id,
                })
                continue

            # Skip other positive amounts (non-income credits we don't track)
            if amount > 0:
                continue

            # Expense: flip sign (BofA negative -> our positive)
            expenses.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=-amount,
                    description=description,
                    merchant=_normalize_merchant(description),
                    source_id=source_id,
                    source_type="csv",
                    account_name="Checking",
                )
            )

    return expenses, income_records
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_bofa_checking_parser.py -v`
Expected: All 13 tests PASS

- [ ] **Step 6: Wire into CLI**

Read `src/cashflow/cli.py`. Add imports:
```python
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
from cashflow.db import store_income
```

In the ingest file loop, add an `elif` for checking CSVs. BofA checking files are named `stmt.csv` or `stmt (1).csv`:
```python
        elif "stmt" in csv_file.name.lower():
            check_expenses, check_income = parse_bofa_checking_csv(csv_file)
            if check_expenses:
                stored = store_transactions(conn, check_expenses)
                click.echo(f"  {stored} new checking expenses")
                total += stored
            if check_income:
                inc_stored = store_income(conn, check_income)
                click.echo(f"  {inc_stored} new income records")
                total += inc_stored
            continue
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/cashflow/parsers/bofa_checking.py tests/test_bofa_checking_parser.py tests/fixtures/bofa_checking_sample.csv src/cashflow/cli.py
git commit -m "feat: BofA checking parser with income detection (Spotify paychecks)"
```

---

## Summary

After completing Plan 3b, you have:
- **BofA credit card parser** — handles both 8690 and 9341 cards, merchant normalization
- **BofA checking parser** — extracts real expenses AND detects Spotify paycheck deposits as income
- **Income storage** — `store_income` function populates the income table
- **`cashflow status` now shows real surplus** — income from paychecks minus all expenses
- Skips: inter-account transfers, credit card autopays, brokerage transfers, interest
- ~90+ automated tests

**The big unlock:** With checking CSV parsing, `cashflow status` will show real surplus numbers for the first time — actual Spotify paychecks minus actual expenses. The $40k annual surplus goal becomes trackable.
