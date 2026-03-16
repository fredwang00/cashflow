import hashlib
import re
from datetime import datetime, date
from pathlib import Path

from cashflow.models import ParsedTransaction

DATE_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}, \d{4}$")
AMOUNT_RE = re.compile(r"^-?\$[\d,]+\.\d{2}$")

CARDHOLDER_MAP = {
    "FEI WANG": "fred",
    "WENDY RIZZO": "wife",
}


def _parse_amount(amount_str: str) -> float:
    return float(amount_str.replace("$", "").replace(",", ""))


def _make_source_id(txn_date: date, description: str, amount: float, who: str) -> str:
    raw = f"{txn_date.isoformat()}|{description}|{amount}|{who}"
    return f"citi-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_citi(path: Path) -> list[ParsedTransaction]:
    """Parse a Citi/Costco card screen scrape.

    Format: date line, cardholder name, description, amount — repeating.
    Skips autopay payments. Stops at 'End of Activity'.
    Detects who (fred/wife) from cardholder name.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    transactions = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Stop at end marker
        if line == "End of Activity":
            break

        # Look for date line
        if not DATE_RE.match(line):
            i += 1
            continue

        date_str = line
        txn_date = datetime.strptime(date_str, "%b %d, %Y").date()
        i += 1

        # Next: cardholder name
        if i >= len(lines):
            break
        cardholder = lines[i].strip()
        who = CARDHOLDER_MAP.get(cardholder, "shared")
        i += 1

        # Next: description
        if i >= len(lines):
            break
        description = lines[i].strip()
        i += 1

        # Next: amount
        if i >= len(lines):
            break
        amount_line = lines[i].strip()
        if not AMOUNT_RE.match(amount_line):
            continue
        amount = _parse_amount(amount_line)
        i += 1

        # Skip payments
        if "AUTOPAY" in description.upper():
            continue

        # Negative amounts are payments/credits — skip
        if amount < 0:
            continue

        transactions.append(
            ParsedTransaction(
                date=txn_date,
                amount=amount,
                description=description,
                merchant=description.split(" #")[0].split(" 800-")[0].split(" 1-800")[0].strip(),
                source_id=_make_source_id(txn_date, description, amount, who),
                source_type="csv",
                account_name="Citi Costco",
                who=who,
            )
        )

    return transactions
