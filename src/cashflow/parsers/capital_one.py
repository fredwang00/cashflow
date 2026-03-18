import hashlib
import re
from datetime import datetime, date
from pathlib import Path

from cashflow.models import ParsedTransaction

MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

STATEMENT_RE = re.compile(r"Statement Ending (\w+ \d+, \d+)")
AMOUNT_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")
MONTH_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")
DAY_RE = re.compile(r"^\d{1,2}$")

SKIP_CATEGORIES = {"Payment", "Fee"}
SKIP_DESCRIPTIONS = {"CREDIT-TRAVEL REWARD", "CAPITAL ONE MEMBER FEE"}

UI_CHROME = {
    "Print", "Date", "Description", "Category", "Card", "Amount", "Details",
    "Download Transactions", "View Statement", "Pending", "More Information",
    "Pending Transactions", "Posted Transactions Since Your Last Statement",
    "All TransactionsPayment Activity", "Scheduled Payments",
    "Search/filter transactions", "Filter", "View spend analyzer",
    "Manage AutoPay", "AUTOPAY SETTINGS",
    "There are no pending transactions.",
    "There are no transactions to show for this statement.",
    "There are no transactions since your last statement.",
}

CARDHOLDER_RE = re.compile(r"^(Fei W\.|Wendy R\.)", re.IGNORECASE)
CARDHOLDER_WHO = {
    "fei": "fred",
    "wendy": "wife",
}


def _parse_amount(amount_str: str) -> float:
    """Parse '$183.38' or '-$321.71' or '$3,770.49'."""
    cleaned = amount_str.replace("$", "").replace(",", "")
    return float(cleaned)


def _make_source_id(txn_date: date, description: str, amount: float) -> str:
    raw = f"{txn_date.isoformat()}|{description}|{amount}"
    return f"capone-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _infer_year(month: int, statement_date: date | None) -> int:
    """Infer the transaction year from the enclosing statement period.

    If the transaction month is greater than the statement month,
    it belongs to the previous year (e.g., Dec transaction in a
    Jan statement = previous year December).
    """
    if statement_date is None:
        return date.today().year

    if month > statement_date.month:
        return statement_date.year - 1
    return statement_date.year


def parse_capital_one(path: Path, account_name: str = "Capital One") -> list[ParsedTransaction]:
    """Parse a Capital One screen scrape into transactions.

    Skips payments, travel credit rewards, and pending transactions.
    Infers year from Statement Ending boundaries.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    transactions = []
    statement_date = None  # Current statement context
    i = 0

    # Skip everything before "Posted Transactions" section
    while i < len(lines):
        line = lines[i].strip()
        if line == "Posted Transactions Since Your Last Statement":
            i += 1
            break
        i += 1
    else:
        return transactions

    while i < len(lines):
        line = lines[i].strip()

        # Check for statement boundary
        stmt_match = STATEMENT_RE.match(line)
        if stmt_match:
            statement_date = datetime.strptime(stmt_match.group(1), "%b %d, %Y").date()
            i += 1
            continue

        # Skip UI chrome, empty lines, and cardholder name lines
        if not line or line in UI_CHROME or line.startswith("Total:") or CARDHOLDER_RE.match(line):
            i += 1
            continue

        # Look for month line
        if MONTH_RE.match(line):
            month_str = line
            month = MONTH_MAP[month_str]
            i += 1

            # Next should be day
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                break

            day_line = lines[i].strip()
            if not DAY_RE.match(day_line):
                continue
            day = int(day_line)
            i += 1

            # Skip blank lines
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                break

            # Next non-blank: description
            description = lines[i].strip()
            i += 1

            # Skip if it looks like UI chrome or AutoPay
            if description in UI_CHROME or "AutoPay" in description:
                # Skip remaining fields of this transaction
                while i < len(lines):
                    if AMOUNT_RE.match(lines[i].strip()):
                        i += 1
                        break
                    i += 1
                continue

            # Next: category
            if i >= len(lines):
                break
            category = lines[i].strip()
            i += 1

            # Next: card info — extract who from cardholder name
            if i >= len(lines):
                break
            card_line = lines[i].strip()
            who = "shared"
            if card_line.lower().startswith("fei"):
                who = "fred"
            elif card_line.lower().startswith("wendy"):
                who = "wife"
            i += 1

            # Next: amount
            if i >= len(lines):
                break
            amount_line = lines[i].strip()
            if not AMOUNT_RE.match(amount_line):
                continue
            amount = _parse_amount(amount_line)
            i += 1

            # Skip payments and credits
            if category in SKIP_CATEGORIES:
                continue
            if description in SKIP_DESCRIPTIONS:
                continue

            # Determine year
            year = _infer_year(month, statement_date)
            txn_date = date(year, month, day)

            # Negative amounts are credits — keep as negative
            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=description,
                    source_id=_make_source_id(txn_date, description, amount),
                    source_type="csv",
                    account_name=account_name,
                    who=who,
                )
            )
        else:
            i += 1

    return transactions
