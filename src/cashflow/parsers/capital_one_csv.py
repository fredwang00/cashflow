import csv
import hashlib
from datetime import date
from pathlib import Path

from cashflow.errors import ParseError
from cashflow.models import ParsedTransaction

# Card number → who attribution
# Add new card numbers here as they're discovered
CARD_WHO = {
    "4429": "fred",   # Fei's Venture card (current)
    "6983": "fred",   # Fei's Venture card (old number, same account)
    "8440": "fred",   # Fei's authorized card on Wendy's account
    "2542": "wife",   # Wendy's card
    "9341": "wife",   # Wendy's BofA card (used in bofa_cc parser too)
    "8690": "fred",   # Fei's BofA card
}


def _make_source_id(row: dict) -> str:
    raw = f"{row['Transaction Date']}|{row['Description']}|{row['Debit']}|{row['Card No.']}"
    return f"capone-csv-{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


def parse_capital_one_csv(path: Path) -> list[ParsedTransaction]:
    """Parse a Capital One CSV export (Transaction Date, Posted Date, Card No.,
    Description, Category, Debit, Credit).

    Debit column = purchases (positive amounts).
    Credit column = payments/refunds — payments skipped, refunds kept negative.
    No sign flip needed for purchases.
    """
    transactions = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                description = row["Description"].strip()
                debit = row["Debit"].strip()
                credit = row["Credit"].strip()
                card_no = row["Card No."].strip()

                # Skip payments (credit with no debit, usually autopay description)
                if credit and not debit:
                    if "PAYMENT" in description.upper() or "AUTOPAY" in description.upper():
                        continue
                    # Non-payment credit = refund, keep as negative
                    amount = -float(credit)
                elif debit:
                    amount = float(debit)
                else:
                    continue

                txn_date = date.fromisoformat(row["Transaction Date"])
            except KeyError as e:
                raise ParseError(path.name, row_num, f"missing column {e}") from None
            except ValueError as e:
                raise ParseError(path.name, row_num, str(e)) from None
            who = CARD_WHO.get(card_no, "shared")

            transactions.append(
                ParsedTransaction(
                    date=txn_date,
                    amount=amount,
                    description=description,
                    merchant=description,
                    source_id=_make_source_id(row),
                    source_type="csv",
                    account_name="Capital One Venture",
                    who=who,
                )
            )

    return transactions
