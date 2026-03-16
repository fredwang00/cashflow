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
    cleaned = re.split(r"\d{3}-\d{3}-\d{4}|\d{3}-\d{7}|\s{2,}", payee)[0].strip()
    return cleaned if cleaned else payee

def _make_source_id(row: dict) -> str:
    raw = f"{row['Posted Date']}|{row['Reference Number']}|{row['Amount']}"
    return f"bofa-cc-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

def parse_bofa_cc_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            amount = float(row["Amount"])
            payee = row["Payee"].strip().strip('"')
            if "PAYMENT" in payee.upper() and amount > 0:
                continue
            amount = -amount
            txn_date = datetime.strptime(row["Posted Date"], "%m/%d/%Y").date()
            transactions.append(ParsedTransaction(
                date=txn_date, amount=amount, description=payee,
                merchant=_normalize_merchant(payee),
                source_id=_make_source_id(row), source_type="csv",
                account_name="Bank of America",
            ))
    return transactions
