from pathlib import Path

import pytest
from click.testing import CliRunner

from cashflow.cli import cli
from cashflow.db import get_connection
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
from cashflow.queries import get_month_spending
from cashflow.reimburse import link_recorded_reimbursements
from cashflow.seed import seed_all

HEADER = "Date,Description,Amount,Running Bal.\n"


def _checking_csv(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    path = tmp_path / "stmt.csv"
    lines = [f'{day},"{desc}","{amount}","0.00"' for day, desc, amount in rows]
    path.write_text(HEADER + "\n".join(lines) + "\n")
    return path


def _parse(tmp_path, rows):
    return parse_bofa_checking_csv(_checking_csv(tmp_path, rows))


def test_zelle_from_a_person_becomes_a_credit(tmp_path):
    expenses, income = _parse(tmp_path, [
        ("04/13/2026", 'Zelle payment from JANE DOE for Hotel"; Conf# 0K51L1Q4P', "141.00"),
    ])
    [credit] = expenses
    assert credit.amount == -141.00
    assert credit.merchant == "Zelle from JANE DOE"
    assert income == []


@pytest.mark.parametrize("description, merchant", [
    ("BKOFAMERICA MOBILE 04/13 3690802079 DEPOSIT *MOBILE CA", "Check deposit"),
    ("BKOFAMERICA ATM 02/10 #000002736 DEPOSIT PEMBROKE VIRGINIA BEAC VA", "Check deposit"),
    ("Bank of America DES:CASHREWARD ID:WANG INDN:0000000612649523000000 CO ID:2002290", "BofA Cash Rewards"),
    ("Transfer Virginia Lottery Credit via Trustly from Virginia Lottery", "Virginia Lottery"),
    ("VA DEPT TAXATION DES:VASTTAXRFD ID:XXXXX0554 INDN:DOE CO ID:15", "VA DEPT TAXATION"),
])
def test_other_deposits_become_credits_with_readable_merchants(tmp_path, description, merchant):
    [credit], _ = _parse(tmp_path, [("04/13/2026", description, "100.00")])
    assert credit.amount == -100.00
    assert credit.merchant == merchant


@pytest.mark.parametrize("description", [
    "MSPBNA DES:ACH TRNSFR ID:24197233395 INDN:775829877 CO ID:1391321258 PPD",
    "SANTANDER BANK DES:PAYMENT ID:Jane Doe INDN:Jane Doe CO ID:F089778871 WEB",
    "APPLE CASH DES:BANK XFER ID:Jane Doe INDN:Jane Doe CO ID:6192912998 WEB",
    "Transfer PAYPAL",
    "PAYPAL DES:TRANSFER ID:1050959705765 INDN:JANE DOE CO ID:PAYPALSD11 PPD",
    "SPOTIFY USA INC- DES:PAYMENT ID:11765234/MP INDN:JANE DOE CO ID:1900003687 PPD",
])
def test_deposits_from_own_accounts_and_expense_reports_are_skipped(tmp_path, description):
    expenses, income = _parse(tmp_path, [("06/16/2026", description, "2,000.00")])
    assert expenses == []
    assert income == []


def test_payroll_is_still_income_and_debits_still_expenses(tmp_path):
    expenses, income = _parse(tmp_path, [
        ("01/15/2026", "SPOTIFY USA INC DES:DIRECT DEP ID:XXXXX62947558CC INDN:DOE CO ID:XXXXX11101 PPD", "7,421.60"),
        ("01/16/2026", "Zelle payment to Alveraz Lawn Care Conf# abc123", "-55.00"),
    ])
    assert [r["amount"] for r in income] == [7421.60]
    [payment] = expenses
    assert payment.amount == 55.00
    assert payment.merchant == "Zelle"


def test_same_day_credits_that_differ_only_by_confirmation_are_all_kept(tmp_path):
    prefix = 'Zelle payment from Sequoia Data Breach Settlement for "Your Sequoia Data Breach settlement payment was"; Conf# '
    expenses, _ = _parse(tmp_path, [
        ("08/31/2026", prefix + "g000rmfxi", "42.53"),
        ("08/31/2026", prefix + "l000rmv6p", "42.53"),
    ])
    assert len({t.source_id for t in expenses}) == 2


def test_reimporting_overlapping_exports_does_not_duplicate_credits(tmp_path):
    db_path = tmp_path / "test.db"
    row = ("06/15/2026", 'Zelle payment from ROLL ALVAREZ for Overpay for grass seeding"; Conf# wrgvs2231', "2,500.00")
    first = tmp_path / "a"; first.mkdir()
    second = tmp_path / "b"; second.mkdir()
    runner = CliRunner()
    for folder in (first, second):
        path = _checking_csv(folder, [row])
        result = runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(path)])
        assert result.exit_code == 0, result.output
    conn = get_connection(db_path)
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE amount < 0").fetchone()[0] == 1
    conn.close()


@pytest.fixture
def conn(db):
    seed_all(db)
    return db


def _txn(conn, source_id, day, amount, reimbursed=0.0, account="Apple Card"):
    account_id = conn.execute("SELECT id FROM accounts WHERE name = ?", (account,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, "
        "reimbursed_amount, status, source_type) VALUES (?, ?, ?, 'd', 'm', ?, ?, 'confirmed', 'csv')",
        (source_id, day, amount, account_id, reimbursed),
    )
    conn.commit()
    return conn.execute("SELECT id FROM transactions WHERE source_id = ?", (source_id,)).fetchone()["id"]


def _canonical(conn, txn_id):
    return conn.execute("SELECT canonical_id FROM transactions WHERE id = ?", (txn_id,)).fetchone()[0]


def test_credit_matching_a_recorded_reimbursement_is_linked(conn):
    tesla = _txn(conn, "tesla", "2026-03-25", 1377.30, reimbursed=877.30)
    check = _txn(conn, "check", "2026-04-13", -877.30, account="Checking")
    assert link_recorded_reimbursements(conn) == 1
    assert _canonical(conn, check) == tesla


def test_credit_without_a_recorded_reimbursement_stays(conn):
    _txn(conn, "tesla", "2026-03-25", 1377.30, reimbursed=877.30)
    zelle = _txn(conn, "zelle", "2026-04-13", -141.00, account="Checking")
    assert link_recorded_reimbursements(conn) == 0
    assert _canonical(conn, zelle) is None


def test_credit_long_after_the_reimbursed_charge_is_not_linked(conn):
    _txn(conn, "old", "2025-10-01", 900.0, reimbursed=500.0)
    credit = _txn(conn, "check", "2026-04-13", -500.0, account="Checking")
    assert link_recorded_reimbursements(conn) == 0
    assert _canonical(conn, credit) is None


def test_ambiguous_reimbursement_match_is_left_for_review(conn):
    _txn(conn, "a", "2026-03-01", 100.0, reimbursed=50.0)
    _txn(conn, "b", "2026-03-05", 80.0, reimbursed=50.0)
    credit = _txn(conn, "check", "2026-03-20", -50.0, account="Checking")
    assert link_recorded_reimbursements(conn) == 0
    assert _canonical(conn, credit) is None


def test_ingest_counts_credits_once_even_when_reimbursement_was_recorded(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    seed_all(conn)
    _txn(conn, "tesla", "2026-03-25", 1377.30, reimbursed=877.30)
    conn.close()
    csv_path = _checking_csv(tmp_path, [
        ("04/13/2026", "BKOFAMERICA MOBILE 04/13 3690802079 DEPOSIT *MOBILE CA", "877.30"),
        ("04/14/2026", "Zelle payment from JANE DOE Conf# 022UE7OLP", "141.00"),
    ])
    result = CliRunner().invoke(cli, ["--db", str(db_path), "ingest", "--files", str(csv_path)])
    assert result.exit_code == 0, result.output
    assert "1 matched a reimbursement already recorded" in result.output
    conn = get_connection(db_path)
    assert get_month_spending(conn, 2026, 4) == pytest.approx(-141.00)
    conn.close()
