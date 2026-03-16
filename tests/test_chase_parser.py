from pathlib import Path
from cashflow.parsers.chase import parse_chase_csv

FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"

def test_parse_chase_csv_returns_transactions():
    txns = parse_chase_csv(FIXTURE)
    assert len(txns) > 0

def test_parse_chase_csv_skips_payments():
    txns = parse_chase_csv(FIXTURE)
    descriptions = [t.description for t in txns]
    assert not any("AUTOMATIC PAYMENT" in d for d in descriptions)

def test_parse_chase_csv_flips_sign():
    txns = parse_chase_csv(FIXTURE)
    assert all(t.amount > 0 for t in txns)

def test_parse_chase_csv_extracts_order_number():
    txns = parse_chase_csv(FIXTURE)
    amazon_txns = [t for t in txns if t.order_number is not None]
    assert len(amazon_txns) >= 4
    assert any(t.order_number == "112-0026560-9545020" for t in amazon_txns)

def test_parse_chase_csv_normalizes_merchant():
    txns = parse_chase_csv(FIXTURE)
    wf = [t for t in txns if "Whole Foods" in t.merchant]
    assert len(wf) == 1
    assert wf[0].merchant == "Whole Foods"

def test_parse_chase_csv_source_id_is_unique():
    txns = parse_chase_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))

def test_parse_chase_csv_sets_account_name():
    txns = parse_chase_csv(FIXTURE)
    assert all(t.account_name == "Chase Prime Visa" for t in txns)

def test_parse_chase_csv_sets_source_type():
    txns = parse_chase_csv(FIXTURE)
    assert all(t.source_type == "csv" for t in txns)
