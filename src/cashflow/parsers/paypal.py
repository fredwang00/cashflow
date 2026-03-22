import csv
import hashlib
from datetime import datetime
from pathlib import Path

from cashflow.models import ParsedTransaction


def parse_paypal_csv(path: Path) -> list[ParsedTransaction]:
    txns = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Balance Impact") != "Debit":
                continue
            if row.get("Status") not in ("Completed", "Pending"):
                continue

            dt = datetime.strptime(row["Date"], "%m/%d/%Y").date()
            gross = float(row["Gross"].replace(",", ""))
            amount = abs(gross)
            name = row.get("Name", "").strip()
            merchant = name if name else "PayPal"
            description = row.get("Item Title") or row.get("Subject") or row.get("Note") or merchant
            txn_id = row.get("Transaction ID", "")

            source_id = hashlib.sha256(
                f"paypal:{txn_id}:{dt.isoformat()}:{gross}".encode()
            ).hexdigest()[:16]

            txns.append(ParsedTransaction(
                date=dt,
                amount=amount,
                description=description.strip(),
                merchant=merchant,
                source_id=source_id,
                source_type="csv",
                account_name="PayPal",
            ))
    return txns
