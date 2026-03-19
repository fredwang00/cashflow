from pathlib import Path
from cashflow.parsers.expense_report import parse_expense_report

FIXTURE = Path(__file__).parent / "fixtures" / "expense_report_sample.xlsx"

def test_parse_expense_report():
    rows = parse_expense_report(FIXTURE)
    assert len(rows) == 3
    assert rows[0].date.isoformat() == "2025-04-12"
    assert rows[0].amount == 53.94
    assert rows[0].vendor == "Uber Technologies"

def test_parse_expense_report_amounts():
    rows = parse_expense_report(FIXTURE)
    amounts = [r.amount for r in rows]
    assert 2025.60 in amounts  # comma-formatted dollar amount parsed correctly
