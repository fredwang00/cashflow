from pathlib import Path

import pytest

from cashflow.errors import ParseError
from cashflow.parsers.wells_fargo import parse_wells_fargo_csv

FIXTURE = Path(__file__).parent / "fixtures" / "wells_fargo_sample.csv"


def test_parse_returns_transactions():
    txns = parse_wells_fargo_csv(FIXTURE)
    assert len(txns) > 0


def test_parse_skips_payments():
    txns = parse_wells_fargo_csv(FIXTURE)
    assert not any("AUTOMATIC PAYMENT" in t.description for t in txns)


def test_parse_correct_count():
    """Fixture has 7 rows: 1 payment skipped = 6 kept."""
    txns = parse_wells_fargo_csv(FIXTURE)
    assert len(txns) == 6


def test_parse_flips_sign_for_purchases():
    txns = parse_wells_fargo_csv(FIXTURE)
    aa = [t for t in txns if "AMERICAN AIR" in t.description][0]
    assert aa.amount == 2126.63


def test_parse_keeps_credits_as_negative():
    txns = parse_wells_fargo_csv(FIXTURE)
    credits = [t for t in txns if t.amount < 0]
    assert len(credits) >= 1
    trip_refund = [t for t in txns if "Trip.com" in t.merchant and t.amount < 0][0]
    assert trip_refund.amount == -873.03


def test_parse_keeps_annual_fee():
    txns = parse_wells_fargo_csv(FIXTURE)
    fees = [t for t in txns if "ANNUAL FEE" in t.description]
    assert len(fees) == 1
    assert fees[0].amount == 95.00


def test_parse_source_ids_unique():
    txns = parse_wells_fargo_csv(FIXTURE)
    source_ids = [t.source_id for t in txns]
    assert len(source_ids) == len(set(source_ids))


def test_parse_sets_account_name():
    txns = parse_wells_fargo_csv(FIXTURE)
    assert all(t.account_name == "Wells Fargo" for t in txns)


def test_parse_defaults_to_fred():
    txns = parse_wells_fargo_csv(FIXTURE)
    assert all(t.who == "fred" for t in txns)


def test_parse_cleans_merchant():
    txns = parse_wells_fargo_csv(FIXTURE)
    aa = [t for t in txns if t.amount == 2126.63][0]
    assert "AMERICAN AIR" in aa.merchant
    assert "0012328548002" not in aa.merchant


@pytest.mark.parametrize("row", ['03/24/2026', '03/24/2026,Store,-10.00,,Posted,extra'])
def test_malformed_row_reports_file_and_row(tmp_path, row):
    path = tmp_path / "malformed.csv"
    path.write_text('DATE,DESCRIPTION,AMOUNT,CHECK #,STATUS' + "\n" + row + "\n")
    with pytest.raises(ParseError) as error:
        parse_wells_fargo_csv(path)
    assert error.value.file == "malformed.csv"
    assert error.value.row == 2
    assert "column" in error.value.message
