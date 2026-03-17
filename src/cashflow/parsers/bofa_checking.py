import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from cashflow.models import ParsedTransaction

SKIP_PATTERNS = [
    re.compile(r"Online Banking transfer", re.IGNORECASE),
    re.compile(r"CREDIT CRD.*AUTOPAY", re.IGNORECASE),
    re.compile(r"CHASE CREDIT CRD", re.IGNORECASE),
    re.compile(r"APPLECARD GSBANK.*PAYMENT", re.IGNORECASE),
    re.compile(r"CAPITAL ONE.*CRCARDPMT", re.IGNORECASE),
    re.compile(r"BANK OF AMERICA CREDIT CARD", re.IGNORECASE),
    re.compile(r"AMERICAN EXPRESS.*ACH PMT", re.IGNORECASE),
    re.compile(r"CITI AUTOPAY", re.IGNORECASE),
    re.compile(r"TARGET CARD.*PAYMENT", re.IGNORECASE),
    re.compile(r"COINBASE", re.IGNORECASE),
    re.compile(r"SANTBK.*WEBXFR", re.IGNORECASE),
    re.compile(r"SANTBK.*TNTRANSFER", re.IGNORECASE),
    re.compile(r"OVERDRAFT PROTECTION", re.IGNORECASE),
    re.compile(r"Check \d+", re.IGNORECASE),
    re.compile(r"MSPBNA BANK.*TRANSFER", re.IGNORECASE),
    re.compile(r"Interest Earned", re.IGNORECASE),
    re.compile(r"Beginning balance", re.IGNORECASE),
]

INCOME_PATTERNS = [
    (re.compile(r"SPOTIFY USA INC.*(?:DIRECT DEP|PAYROLL)", re.IGNORECASE), "fei_paycheck"),
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
    cleaned = re.split(r"\s+DES:", description)[0].strip()
    return cleaned if cleaned else description

def _make_source_id(date_str: str, description: str, amount_str: str) -> str:
    raw = f"{date_str}|{description[:50]}|{amount_str}"
    return f"bofa-chk-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

def _parse_amount(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))

def _should_skip(description: str) -> bool:
    return any(p.search(description) for p in SKIP_PATTERNS)

def _detect_income(description: str) -> str | None:
    for pattern, source in INCOME_PATTERNS:
        if pattern.search(description):
            return source
    return None

def parse_bofa_checking_csv(path: Path) -> tuple[list[ParsedTransaction], list[dict]]:
    expenses = []
    income_records = []
    with open(path, newline="", encoding="utf-8") as f:
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
            income_source = _detect_income(description)
            if income_source and amount > 0:
                income_records.append({"date": txn_date, "amount": amount, "source": income_source, "description": description, "source_id": source_id})
                continue
            if amount > 0:
                continue
            expenses.append(ParsedTransaction(
                date=txn_date, amount=-amount, description=description,
                merchant=_normalize_merchant(description),
                source_id=source_id, source_type="csv", account_name="Checking",
            ))
    return expenses, income_records
