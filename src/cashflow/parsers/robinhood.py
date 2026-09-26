from collections import Counter
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
POSTED_STATUS = "Posted"


def _make_source_id(row: dict) -> str:
    cardholder = row["Cardholder"].strip().title()
    raw = f"{row['Date']}|{row['Time']}|{row['Merchant']}|{row['Amount']}|{cardholder}"
    return f"robinhood-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_robinhood_csv(path: Path) -> list[ParsedTransaction]:
    transactions = []
    occurrences = Counter()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                txn_type = row["Type"].strip()
                status = row["Status"].strip()

                if txn_type in SKIP_TYPES:
                    continue
                if status != POSTED_STATUS:
                    continue

                amount = float(row["Amount"])
                if (row["Merchant"].strip().lower() == "points redeemed"
                        or row.get("Description", "").strip().upper() == "POINTS REDEEMED"):
                    continue

                txn_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                merchant = row["Merchant"].strip()
                description = row.get("Description", "").strip() or merchant
                cardholder = row["Cardholder"].strip().title()
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None

            who = CARDHOLDER_MAP.get(cardholder, "shared")

            source_id = _make_source_id(row)
            occurrences[source_id] += 1
            if occurrences[source_id] > 1:
                source_id += f"-occurrence-{occurrences[source_id]}"

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=merchant,
                    source_id=source_id,
                    source_type="csv",
                    account_name="Robinhood Gold",
                    who=who,
                )
            )

    return transactions
