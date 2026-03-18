from pathlib import Path
from cashflow.parsers.capital_one_csv import parse_capital_one_csv

FIXTURE = Path(__file__).parent / "fixtures" / "capital_one_csv_sample.csv"
FILE_4429 = Path("/Users/fwang/Downloads/capital-one-venture-4429.csv")
FILE_ALT = Path("/Users/fwang/Downloads/capital-one-venture-alt.csv")


def test_parse_returns_transactions():
    txns = parse_capital_one_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_capital_one_csv(FIXTURE)
    assert not any("AUTOPAY" in t.description for t in txns)


def test_parse_extracts_amount():
    txns = parse_capital_one_csv(FIXTURE)
    kyushu = [t for t in txns if "KYUSHU" in t.description][0]
    assert kyushu.amount == 264.31


def test_parse_iso_dates():
    txns = parse_capital_one_csv(FIXTURE)
    kyushu = [t for t in txns if "KYUSHU" in t.description][0]
    assert str(kyushu.date) == "2025-12-29"


def test_parse_detects_fred_from_card_4429():
    txns = parse_capital_one_csv(FIXTURE)
    delta = [t for t in txns if "DELTA" in t.description][0]
    assert delta.who == "fred"
    assert delta.amount == 1102.50


def test_parse_detects_fred_from_card_6983():
    txns = parse_capital_one_csv(FIXTURE)
    kyushu = [t for t in txns if "KYUSHU" in t.description][0]
    assert kyushu.who == "fred"


def test_parse_detects_fred_from_card_8440():
    txns = parse_capital_one_csv(FIXTURE)
    olympic = [t for t in txns if "OLYMPIC" in t.description][0]
    assert olympic.who == "fred"


def test_parse_source_ids_unique():
    txns = parse_capital_one_csv(FIXTURE)
    ids = [t.source_id for t in txns]
    assert len(ids) == len(set(ids))


def test_parse_sets_account_name():
    txns = parse_capital_one_csv(FIXTURE)
    assert all(t.account_name == "Capital One Venture" for t in txns)


def test_parse_correct_count():
    """Fixture: 6 purchases + 1 Delta + 1 Olympic - 2 autopay = 8 transactions."""
    txns = parse_capital_one_csv(FIXTURE)
    assert len(txns) == 8


# Smoke tests against real files (skipped if files not present)
def test_smoke_4429_file():
    if not FILE_4429.exists():
        return
    txns = parse_capital_one_csv(FILE_4429)
    assert len(txns) > 200
    delta = [t for t in txns if "DELTA" in t.description.upper()]
    assert len(delta) > 0, "Expected Delta flight charges"
    amounts = [t.amount for t in txns]
    assert all(a != 0 for a in amounts)


def test_smoke_alt_file():
    if not FILE_ALT.exists():
        return
    txns = parse_capital_one_csv(FILE_ALT)
    assert len(txns) > 100
    greece = [t for t in txns if any(kw in t.description.upper()
              for kw in ["PEYK", "SPILIOS", "TRAFFIC", "ROKA", "STROGILLI"])]
    assert len(greece) > 0, "Expected Greece/Turkey charges"
