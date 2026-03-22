from pathlib import Path
from cashflow.parsers.paypal import parse_paypal_csv

FIXTURE = Path(__file__).parent / "fixtures" / "paypal_sample.csv"


def test_parse_paypal_csv_returns_debits_only():
    txns = parse_paypal_csv(FIXTURE)
    assert len(txns) == 2  # 2 debits, 2 credits in fixture


def test_parse_paypal_csv_amounts_positive():
    txns = parse_paypal_csv(FIXTURE)
    assert all(t.amount > 0 for t in txns)


def test_parse_paypal_csv_merchant_from_name():
    txns = parse_paypal_csv(FIXTURE)
    merchants = [t.merchant for t in txns]
    assert "Walsworth Publishing Company, Inc." in merchants
    assert "Ashby Orthodontics" in merchants


def test_parse_paypal_csv_dates():
    txns = parse_paypal_csv(FIXTURE)
    assert txns[0].date.isoformat() == "2025-01-08"
    assert txns[1].date.isoformat() == "2025-01-15"


def test_parse_paypal_csv_source_id_unique():
    txns = parse_paypal_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_paypal_csv_account_and_source_type():
    txns = parse_paypal_csv(FIXTURE)
    assert all(t.account_name == "PayPal" for t in txns)
    assert all(t.source_type == "csv" for t in txns)
