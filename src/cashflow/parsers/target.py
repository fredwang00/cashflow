import csv
import hashlib
from datetime import date
from pathlib import Path

from cashflow.errors import ParseError
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
        for row_num, raw_row in enumerate(reader, start=2):
            row = _clean_row(raw_row)
            try:
                amount = float(row["Amount"])
                txn_type = row["Transaction Type"].strip()

                # Skip payments
                if txn_type == "Payment":
                    continue

                txn_date = date.fromisoformat(row["Transaction Date"])
                description = row["Description"].strip()
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None

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
