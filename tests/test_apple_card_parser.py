from pathlib import Path
from cashflow.parsers.apple_card import parse_apple_card_csv

FIXTURE = Path(__file__).parent / "fixtures" / "apple_card_sample.csv"


def test_parse_returns_transactions():
    txns = parse_apple_card_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_apple_card_csv(FIXTURE)
    assert not any("ACH DEPOSIT" in t.description for t in txns)


def test_parse_skips_daily_cash_adjustment():
    txns = parse_apple_card_csv(FIXTURE)
    assert not any("DAILY CASH" in t.description for t in txns)


def test_parse_keeps_credits_as_negative():
    txns = parse_apple_card_csv(FIXTURE)
    credits = [t for t in txns if t.amount < 0]
    assert len(credits) == 1
    assert credits[0].amount == -196.10


def test_parse_keeps_installments():
    txns = parse_apple_card_csv(FIXTURE)
    installments = [t for t in txns if "INSTALLMENT" in t.description.upper()]
    assert len(installments) == 1
    assert installments[0].amount == 47.83


def test_parse_uses_merchant_column():
    txns = parse_apple_card_csv(FIXTURE)
    apple_mall = [t for t in txns if t.amount == 401.74][0]
    assert apple_mall.merchant == "Apple Lynnhaven Mall"


def test_parse_detects_wife():
    txns = parse_apple_card_csv(FIXTURE)
    wife_txns = [t for t in txns if t.who == "wife"]
    assert len(wife_txns) == 2


def test_parse_detects_fred():
    txns = parse_apple_card_csv(FIXTURE)
    fred_txns = [t for t in txns if t.who == "fred"]
    assert len(fred_txns) >= 1


def test_parse_source_ids_unique():
    txns = parse_apple_card_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_apple_card_csv(FIXTURE)
    assert all(t.account_name == "Apple Card" for t in txns)


def test_parse_correct_count():
    """Fixture: skip payment + skip daily cash = 5 kept (credit, store, 2 wife purchases, installment)."""
    txns = parse_apple_card_csv(FIXTURE)
    assert len(txns) == 5
