from pathlib import Path
from cashflow.parsers.citi import parse_citi

FIXTURE = Path(__file__).parent / "fixtures" / "citi_sample.txt"


def test_parse_returns_transactions():
    txns = parse_citi(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_citi(FIXTURE)
    assert not any("AUTOPAY" in t.description for t in txns)


def test_parse_extracts_date():
    txns = parse_citi(FIXTURE)
    exxon = [t for t in txns if "EXXON" in t.description][0]
    assert str(exxon.date) == "2025-01-02"


def test_parse_extracts_amount():
    txns = parse_citi(FIXTURE)
    exxon = [t for t in txns if "EXXON" in t.description][0]
    assert exxon.amount == 52.88


def test_parse_handles_comma_amounts():
    txns = parse_citi(FIXTURE)
    tv = [t for t in txns if "Samsung" in t.description][0]
    assert tv.amount == 1467.12


def test_parse_detects_wife():
    txns = parse_citi(FIXTURE)
    outschool = [t for t in txns if "OUTSCHOOL" in t.description][0]
    assert outschool.who == "wife"


def test_parse_detects_fred():
    txns = parse_citi(FIXTURE)
    exxon = [t for t in txns if "EXXON" in t.description][0]
    assert exxon.who == "fred"


def test_parse_stops_at_end_of_activity():
    txns = parse_citi(FIXTURE)
    # Should not include summary lines after "End of Activity"
    assert not any("Total Activity" in t.description for t in txns)


def test_parse_source_ids_unique():
    txns = parse_citi(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_citi(FIXTURE)
    assert all(t.account_name == "Citi Costco" for t in txns)


def test_parse_correct_count():
    """5 non-payment transactions in fixture."""
    txns = parse_citi(FIXTURE)
    assert len(txns) == 5
