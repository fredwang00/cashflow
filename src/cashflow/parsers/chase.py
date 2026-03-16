import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from cashflow.models import ParsedTransaction

ORDER_NUMBER_RE = re.compile(r"Order Number\s+(\d{3}-\d{7}-\d{7})")
DIGITAL_ORDER_RE = re.compile(r"Order Number\s+(D\d{2}-\d{7}-\d{7})")

MERCHANT_PATTERNS = [
    (re.compile(r"Whole Foods", re.IGNORECASE), "Whole Foods"),
    (re.compile(r"AMAZON MKTPL", re.IGNORECASE), "Amazon Marketplace"),
    (re.compile(r"Amazon\.com", re.IGNORECASE), "Amazon.com"),
    (re.compile(r"Audible", re.IGNORECASE), "Audible"),
    (re.compile(r"Prime Video", re.IGNORECASE), "Prime Video"),
    (re.compile(r"Kindle Svcs", re.IGNORECASE), "Kindle"),
]

def _normalize_merchant(description: str) -> str:
    for pattern, name in MERCHANT_PATTERNS:
        if pattern.search(description):
            return name
    cleaned = re.split(r"[*#]", description)[0].strip()
    return cleaned if cleaned else description

def _extract_order_number(description: str) -> str | None:
    match = ORDER_NUMBER_RE.search(description)
    if match:
        return match.group(1)
    match = DIGITAL_ORDER_RE.search(description)
    if match:
        return match.group(1)
    return None

def _make_source_id(row: dict) -> str:
    raw = f"{row['Transaction Date']}|{row['Description']}|{row['Amount']}"
    return f"chase-csv-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

def parse_chase_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount = float(row["Amount"])
            if amount > 0:
                continue
            amount = -amount
            txn_date = datetime.strptime(row["Transaction Date"], "%m/%d/%Y").date()
            description = row["Description"]
            transactions.append(ParsedTransaction(
                date=txn_date, amount=amount, description=description,
                merchant=_normalize_merchant(description),
                source_id=_make_source_id(row), source_type="csv",
                account_name="Chase Prime Visa",
                order_number=_extract_order_number(description),
            ))
    return transactions
