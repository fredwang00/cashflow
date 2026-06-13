import csv
import hashlib
import string
from datetime import datetime
from pathlib import Path

from cashflow.errors import ParseError
from cashflow.models import ParsedTransaction

CARDHOLDER_MAP = {
    "FEI WANG": "fred",
    "WENDY RIZZO": "wife",
}


def _clean_merchant(description: str) -> str:
    cleaned = " ".join(description.split())
    return string.capwords(cleaned) if cleaned.isupper() else cleaned


def _make_source_id(row: dict) -> str:
    raw = f"{row['Date']}|{row['Description']}|{row['Amount']}|{row['Reference']}"
    return f"amex-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_amex_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                amount = float(row["Amount"])
                txn_date = datetime.strptime(row["Date"], "%m/%d/%Y").date()
                description = row["Description"].strip()
                merchant = _clean_merchant(description)
                card_member = row["Card Member"].strip().upper()
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None

            who = CARDHOLDER_MAP.get(card_member, "shared")

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=merchant,
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Amex Gold",
                    who=who,
                )
            )

    return transactions
