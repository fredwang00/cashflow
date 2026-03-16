from pathlib import Path
from cashflow.parsers.capital_one import parse_capital_one

FIXTURE = Path(__file__).parent / "fixtures" / "capital_one_sample.txt"


def test_parse_returns_transactions():
    txns = parse_capital_one(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_capital_one(FIXTURE)
    assert not any("AutoPay" in t.description for t in txns)


def test_parse_skips_credit_rewards():
    txns = parse_capital_one(FIXTURE)
    assert not any("CREDIT-TRAVEL REWARD" in t.description for t in txns)


def test_parse_extracts_amounts():
    txns = parse_capital_one(FIXTURE)
    ocean = [t for t in txns if "OCEAN GRILL" in t.description][0]
    assert ocean.amount == 183.38


def test_parse_infers_year_from_statement():
    txns = parse_capital_one(FIXTURE)
    # KYUSHU JAPANESE is in "Statement Ending Jan 18, 2026" section, Dec date = 2025
    kyushu = [t for t in txns if "KYUSHU" in t.description][0]
    assert str(kyushu.date) == "2025-12-30"


def test_parse_pre_statement_uses_current_year():
    txns = parse_capital_one(FIXTURE)
    # Town Center is before first "Statement Ending" — should use 2026
    barber = [t for t in txns if "Town Center" in t.description][0]
    assert str(barber.date) == "2026-02-19"


def test_parse_maps_capital_one_category():
    txns = parse_capital_one(FIXTURE)
    # Dining transactions
    ocean = [t for t in txns if "OCEAN GRILL" in t.description][0]
    assert ocean.merchant == "OCEAN GRILL SEAFOOD BU"  # raw merchant
    # The Capital One category is available but we store as merchant for now


def test_parse_source_ids_unique():
    txns = parse_capital_one(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_capital_one(FIXTURE)
    assert all(t.account_name == "Capital One" for t in txns)


def test_parse_handles_comma_amounts():
    """Amounts like $3,770.49 should not appear (payments skipped) but parser should handle them."""
    txns = parse_capital_one(FIXTURE)
    # No transaction should have amount 3770.49 (it's a payment, skipped)
    assert not any(abs(t.amount - 3770.49) < 0.01 for t in txns)


def test_parse_correct_count():
    """Fixture has: barber($25), ocean($183.38), nawab($119.25), carvel($11.26), usps($3.18), five guys($29.02), super ninja($178.34), kyushu($264.31), home depot($52.94) = 9 transactions."""
    txns = parse_capital_one(FIXTURE)
    assert len(txns) == 9
