import csv
import hashlib
from datetime import datetime
from pathlib import Path

from cashflow.errors import ParseError
from cashflow.models import ParsedTransaction

CARDHOLDER_MAP = {
    "Fei Wang": "fred",
    "Wendy Rizzo": "wife",
}

SKIP_TYPES = {"Payment"}
SKIP_STATUSES = {"Declined"}


def _make_source_id(row: dict) -> str:
    raw = f"{row['Date']}|{row['Time']}|{row['Merchant']}|{row['Amount']}|{row['Cardholder']}"
    return f"robinhood-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_robinhood_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                txn_type = row["Type"].strip()
                status = row["Status"].strip()

                if txn_type in SKIP_TYPES:
                    continue
                if status in SKIP_STATUSES:
                    continue

                amount = float(row["Amount"])
                if amount < 0:
                    continue

                txn_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                merchant = row["Merchant"].strip()
                description = row.get("Description", "").strip() or merchant
                cardholder = row["Cardholder"].strip()
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None

            who = CARDHOLDER_MAP.get(cardholder, "shared")

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=merchant,
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Robinhood Gold",
                    who=who,
                )
            )

    return transactions
