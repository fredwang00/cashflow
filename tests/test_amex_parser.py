from pathlib import Path
from cashflow.parsers.amex import parse_amex_csv

FIXTURE = Path(__file__).parent / "fixtures" / "amex_sample.csv"


def test_parse_returns_transactions():
    txns = parse_amex_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_keeps_fees():
    txns = parse_amex_csv(FIXTURE)
    fees = [t for t in txns if "MEMBERSHIP FEE" in t.description]
    assert len(fees) == 1
    assert fees[0].amount == 325.00


def test_parse_correct_count():
    """Fixture has 6 rows, all kept (fees are real expenses)."""
    txns = parse_amex_csv(FIXTURE)
    assert len(txns) == 6


def test_parse_keeps_credits_as_negative():
    txns = parse_amex_csv(FIXTURE)
    credits = [t for t in txns if t.amount < 0]
    assert len(credits) == 1
    assert credits[0].amount == -47.50


def test_parse_detects_fred():
    txns = parse_amex_csv(FIXTURE)
    fred_txns = [t for t in txns if t.who == "fred"]
    assert len(fred_txns) >= 1


def test_parse_detects_wife():
    txns = parse_amex_csv(FIXTURE)
    wife_txns = [t for t in txns if t.who == "wife"]
    assert len(wife_txns) == 1


def test_parse_source_ids_unique():
    txns = parse_amex_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_amex_csv(FIXTURE)
    assert all(t.account_name == "Amex Gold" for t in txns)


def test_parse_handles_multiline_fields():
    txns = parse_amex_csv(FIXTURE)
    pho = [t for t in txns if t.amount == 22.26][0]
    assert pho.who == "fred"
