from pathlib import Path
from cashflow.parsers.robinhood import parse_robinhood_csv

FIXTURE = Path(__file__).parent / "fixtures" / "robinhood_sample.csv"


def test_parse_returns_transactions():
    txns = parse_robinhood_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_robinhood_csv(FIXTURE)
    assert not any("PAYMENT" in t.description for t in txns)


def test_parse_skips_declined():
    txns = parse_robinhood_csv(FIXTURE)
    assert not any("Noodle Man" in t.merchant for t in txns)


def test_parse_skips_negative_amounts():
    """Points redemptions and payments have negative amounts."""
    txns = parse_robinhood_csv(FIXTURE)
    assert all(t.amount > 0 for t in txns)


def test_parse_correct_count():
    """Fixture: 9 rows - 1 payment - 2 declined - 1 points redemption = 5 kept."""
    txns = parse_robinhood_csv(FIXTURE)
    assert len(txns) == 5


def test_parse_detects_fred():
    txns = parse_robinhood_csv(FIXTURE)
    fred_txns = [t for t in txns if t.who == "fred"]
    assert len(fred_txns) >= 1


def test_parse_detects_wife():
    txns = parse_robinhood_csv(FIXTURE)
    wife_txns = [t for t in txns if t.who == "wife"]
    assert len(wife_txns) >= 1


def test_parse_source_ids_unique():
    txns = parse_robinhood_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_robinhood_csv(FIXTURE)
    assert all(t.account_name == "Robinhood Gold" for t in txns)


def test_parse_uses_description_when_available():
    txns = parse_robinhood_csv(FIXTURE)
    mcdonalds = [t for t in txns if t.merchant == "McDonald's"][0]
    assert "MCDONALD'S F7695" in mcdonalds.description


def test_parse_falls_back_to_merchant_for_description():
    txns = parse_robinhood_csv(FIXTURE)
    starbucks = [t for t in txns if t.merchant == "Starbucks"][0]
    assert starbucks.description == "Starbucks"


def test_parse_keeps_fees():
    txns = parse_robinhood_csv(FIXTURE)
    fees = [t for t in txns if "Gold Annual" in t.merchant]
    assert len(fees) == 1
    assert fees[0].amount == 50.00
