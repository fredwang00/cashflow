from pathlib import Path
from cashflow.parsers.bofa_cc import parse_bofa_cc_csv
FIXTURE = Path(__file__).parent / "fixtures" / "bofa_cc_sample.csv"

def test_parse_bofa_cc_returns_transactions():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert len(txns) > 0

def test_parse_bofa_cc_skips_payments():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert not any("PAYMENT - THANK YOU" in t.description for t in txns)

def test_parse_bofa_cc_flips_sign_for_purchases():
    txns = parse_bofa_cc_csv(FIXTURE)
    kroger = [t for t in txns if "KROGER" in t.description and t.amount > 0]
    assert len(kroger) >= 1
    assert kroger[0].amount == 41.76

def test_parse_bofa_cc_keeps_refunds_as_negative():
    txns = parse_bofa_cc_csv(FIXTURE)
    refunds = [t for t in txns if t.amount < 0]
    assert len(refunds) == 1
    assert refunds[0].amount == -8.06

def test_parse_bofa_cc_extracts_merchant():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert any("Kroger" in t.merchant for t in txns)

def test_parse_bofa_cc_source_id_uses_reference():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert all("bofa-cc-" in t.source_id for t in txns)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))

def test_parse_bofa_cc_sets_account_name():
    txns = parse_bofa_cc_csv(FIXTURE)
    assert all(t.account_name == "Bank of America" for t in txns)

def test_parse_bofa_cc_parses_dates():
    txns = parse_bofa_cc_csv(FIXTURE)
    carol = [t for t in txns if "CAROL" in t.description][0]
    assert str(carol.date) == "2025-04-10"
