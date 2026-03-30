from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import openpyxl

from cashflow.errors import ParseError


@dataclass
class ExpenseRow:
    date: date
    amount: float
    vendor: str
    expense_type: str


def _parse_amount(val: str) -> float:
    """Parse '$1,620.48' -> 1620.48"""
    return float(str(val).replace("$", "").replace(",", ""))


def _parse_date(val) -> date:
    """Handle both string dates ('04/12/2025') and native Excel datetime objects."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return datetime.strptime(str(val), "%m/%d/%Y").date()


def parse_expense_report(path: Path) -> list[ExpenseRow]:
    try:
        wb = openpyxl.load_workbook(path)
    except Exception as e:
        raise ParseError(path.name, None, f"cannot read Excel file: {e}") from None
    ws = wb.active
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:  # skip header
            continue
        if not row[0]:
            continue
        try:
            dt = _parse_date(row[0])
            amount = _parse_amount(row[5])  # Approved column
            vendor = str(row[3])
            expense_type = str(row[2])
        except (ValueError, TypeError, IndexError) as e:
            raise ParseError(path.name, i + 1, str(e)) from None
        rows.append(ExpenseRow(date=dt, amount=amount, vendor=vendor, expense_type=expense_type))
    return rows
