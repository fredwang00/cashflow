import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from cashflow.errors import ParseError
from cashflow.models import ParsedTransaction

SKIP_DESCRIPTIONS = {"AUTOMATIC PAYMENT - THANK YOU"}


def _clean_merchant(description: str) -> str:
    cleaned = re.split(r"\d{10,}", description)[0].strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if not cleaned:
        cleaned = description.strip()
    return cleaned


def _make_source_id(row: dict) -> str:
    raw = f"{row['DATE']}|{row['DESCRIPTION']}|{row['AMOUNT']}"
    return f"wf-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_wells_fargo_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                description = row["DESCRIPTION"].strip()
                if description in SKIP_DESCRIPTIONS:
                    continue

                amount = -float(row["AMOUNT"])
                txn_date = datetime.strptime(row["DATE"], "%m/%d/%Y").date()
                merchant = _clean_merchant(description)
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=merchant,
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Wells Fargo",
                    who="fred",
                )
            )

    return transactions
