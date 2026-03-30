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
SKIP_DESCRIPTIONS = {"DAILY CASH ADJUSTMENT"}


def _make_source_id(row: dict) -> str:
    raw = f"{row['Transaction Date']}|{row['Description']}|{row['Amount (USD)']}|{row['Purchased By']}"
    return f"apple-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_apple_card_csv(path: Path) -> list[ParsedTransaction]:
    """Parse an Apple Card CSV export.

    Amounts are positive for purchases, negative for credits/payments.
    Payments and Daily Cash Adjustments are skipped.
    Credits (returns) are kept as negative amounts.
    No sign flip needed.
    """
    transactions = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                txn_type = row["Type"].strip()
                description = row["Description"].strip().strip('"')

                if txn_type in SKIP_TYPES:
                    continue
                if description.upper() in SKIP_DESCRIPTIONS:
                    continue

                amount = float(row["Amount (USD)"])
                txn_date = datetime.strptime(row["Transaction Date"], "%m/%d/%Y").date()
                merchant = row["Merchant"].strip().strip('"')
                purchased_by = row["Purchased By"].strip().strip('"')
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None
            who = CARDHOLDER_MAP.get(purchased_by, "shared")

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=merchant,
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Apple Card",
                    who=who,
                )
            )

    return transactions
