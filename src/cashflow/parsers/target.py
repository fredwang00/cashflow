import csv
import hashlib
from datetime import date
from pathlib import Path

from cashflow.models import ParsedTransaction


def _make_source_id(row: dict) -> str:
    raw = f"{row['Transaction Date']}|{row['Ref#']}|{row['Amount']}"
    return f"target-csv-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def _clean_row(row: dict) -> dict:
    """Strip BOM, extra quotes, and whitespace from CSV row keys and values."""
    return {
        k.strip().strip("\ufeff").strip('"'): v.strip() if v else v
        for k, v in row.items()
    }


def parse_target_csv(path: Path) -> list[ParsedTransaction]:
    """Parse a Target RedCard CSV export into transactions.

    Target CSVs use positive amounts for purchases and negative for
    payments/returns. Payments are skipped. Returns are kept as negative
    amounts (credits). No sign flip needed — matches spec convention.
    """
    transactions = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row = _clean_row(raw_row)
            amount = float(row["Amount"])
            txn_type = row["Transaction Type"].strip()

            # Skip payments
            if txn_type == "Payment":
                continue

            txn_date = date.fromisoformat(row["Transaction Date"])
            description = row["Description"].strip()

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant="Target",
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Target Card",
                )
            )

    return transactions
