from pathlib import Path
from cashflow.parsers.target import parse_target_csv

FIXTURE = Path(__file__).parent / "fixtures" / "target_sample.csv"


def test_parse_target_csv_returns_transactions():
    txns = parse_target_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_target_csv_skips_payments():
    txns = parse_target_csv(FIXTURE)
    descriptions = [t.description for t in txns]
    assert not any("AUTO PAYMENT" in d for d in descriptions)


def test_parse_target_csv_keeps_returns_as_credits():
    txns = parse_target_csv(FIXTURE)
    returns = [t for t in txns if t.amount < 0]
    assert len(returns) == 1
    assert returns[0].amount == -12.48


def test_parse_target_csv_keeps_positive_amounts():
    txns = parse_target_csv(FIXTURE)
    sales = [t for t in txns if t.amount > 0]
    assert len(sales) == 4


def test_parse_target_csv_parses_iso_dates():
    txns = parse_target_csv(FIXTURE)
    first = [t for t in txns if t.amount == 66.43][0]
    assert str(first.date) == "2026-03-11"


def test_parse_target_csv_normalizes_merchant():
    txns = parse_target_csv(FIXTURE)
    assert all(t.merchant == "Target" for t in txns)


def test_parse_target_csv_source_id_is_unique():
    txns = parse_target_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_target_csv_sets_account_name():
    txns = parse_target_csv(FIXTURE)
    assert all(t.account_name == "Target Card" for t in txns)


def test_parse_target_csv_sets_source_type():
    txns = parse_target_csv(FIXTURE)
    assert all(t.source_type == "csv" for t in txns)
