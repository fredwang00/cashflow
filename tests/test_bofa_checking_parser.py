from pathlib import Path
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
FIXTURE = Path(__file__).parent / "fixtures" / "bofa_checking_sample.csv"

def test_parse_returns_expenses_and_income():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    assert len(expenses) > 0
    assert len(income) > 0

def test_parse_skips_summary_header():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Beginning balance" in d for d in all_descs)

def test_parse_extracts_spotify_as_income():
    _, income = parse_bofa_checking_csv(FIXTURE)
    spotify = [r for r in income if "SPOTIFY" in r["description"]]
    assert len(spotify) == 2
    amounts = sorted([r["amount"] for r in spotify])
    assert amounts == [1480.42, 7421.60]

def test_parse_income_source_is_fei_paycheck():
    _, income = parse_bofa_checking_csv(FIXTURE)
    assert all(r["source"] == "fei_paycheck" for r in income)

def test_parse_skips_inter_account_transfers():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Online Banking transfer" in d for d in all_descs)

def test_parse_skips_credit_card_payments():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    assert not any("CREDIT CRD" in t.description or "AUTOPAY" in t.description for t in expenses)

def test_parse_skips_brokerage_transfers():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("MSPBNA BANK" in d for d in all_descs)

def test_parse_keeps_real_expenses():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    merchants = [t.merchant for t in expenses]
    assert any("Newrez" in m or "Mortgage" in m for m in merchants)
    assert any("Dominion" in m for m in merchants)

def test_parse_keeps_zelle_as_expense():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    zelle = [t for t in expenses if "Zelle" in t.description or "Ping Wang" in t.description]
    assert len(zelle) == 1
    assert zelle[0].amount == 1107.97

def test_parse_handles_comma_amounts():
    _, income = parse_bofa_checking_csv(FIXTURE)
    big = [r for r in income if r["amount"] == 7421.60]
    assert len(big) == 1

def test_parse_skips_interest_earned():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_descs = [t.description for t in expenses] + [r["description"] for r in income]
    assert not any("Interest Earned" in d for d in all_descs)

def test_parse_sets_account_name():
    expenses, _ = parse_bofa_checking_csv(FIXTURE)
    assert all(t.account_name == "Checking" for t in expenses)

def test_parse_source_ids_unique():
    expenses, income = parse_bofa_checking_csv(FIXTURE)
    all_ids = [t.source_id for t in expenses] + [r["source_id"] for r in income]
    assert len(all_ids) == len(set(all_ids))
