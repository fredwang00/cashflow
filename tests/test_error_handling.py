import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from cashflow.cli import cli, main
from cashflow.errors import ParseError
from cashflow.parsers.chase import parse_chase_csv
from cashflow.parsers.target import parse_target_csv
from cashflow.parsers.paypal import parse_paypal_csv


# --- ParseError ---


def test_parse_error_with_row():
    e = ParseError("chase.csv", 5, "bad amount")
    assert str(e) == "chase.csv row 5: bad amount"
    assert e.file == "chase.csv"
    assert e.row == 5


def test_parse_error_without_row():
    e = ParseError("report.xlsx", None, "cannot read Excel file")
    assert str(e) == "report.xlsx: cannot read Excel file"
    assert e.row is None


# --- Parser-level errors ---


def test_chase_parser_bad_amount(tmp_path):
    csv_file = tmp_path / "chase_bad.csv"
    csv_file.write_text(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "01/15/2025,01/16/2025,KROGER,Shopping,Sale,NOT_A_NUMBER,\n"
    )
    with pytest.raises(ParseError, match="chase_bad.csv row 2"):
        parse_chase_csv(csv_file)


def test_chase_parser_missing_column(tmp_path):
    csv_file = tmp_path / "chase_missing.csv"
    csv_file.write_text(
        "Transaction Date,Post Date,Description,Category,Type\n"
        "01/15/2025,01/16/2025,KROGER,Shopping,Sale\n"
    )
    with pytest.raises(ParseError, match="missing column"):
        parse_chase_csv(csv_file)


def test_chase_parser_bad_date(tmp_path):
    csv_file = tmp_path / "chase_baddate.csv"
    csv_file.write_text(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "not-a-date,01/16/2025,KROGER,Shopping,Sale,-25.00,\n"
    )
    with pytest.raises(ParseError, match="chase_baddate.csv row 2"):
        parse_chase_csv(csv_file)


def test_target_parser_bad_amount(tmp_path):
    csv_file = tmp_path / "target_bad.csv"
    csv_file.write_text(
        "Transaction Date,Ref#,Description,Amount,Transaction Type\n"
        "2025-03-01,123,TARGET STORE,OOPS,Purchase\n"
    )
    with pytest.raises(ParseError, match="target_bad.csv row 2"):
        parse_target_csv(csv_file)


def test_paypal_parser_bad_gross(tmp_path):
    csv_file = tmp_path / "paypal_bad.csv"
    csv_file.write_text(
        "Date,Name,Gross,Balance Impact,Status,Transaction ID\n"
        "01/15/2025,ACME,BROKEN,Debit,Completed,TXN123\n"
    )
    with pytest.raises(ParseError, match="paypal_bad.csv row 2"):
        parse_paypal_csv(csv_file)


# --- CLI global error handler ---


def test_cli_catches_parse_error(tmp_path):
    """A bad CSV produces a clean error, not a traceback."""
    db_path = tmp_path / "test.db"
    bad_csv = tmp_path / "chase_bad.csv"
    bad_csv.write_text(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "01/15/2025,01/16/2025,KROGER,Shopping,Sale,NOT_A_NUMBER,\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(bad_csv)])
    assert result.exit_code != 0
    assert "Bad data in" in result.output
    assert "Row 2" in result.output
    assert "Traceback" not in result.output


def test_cli_debug_flag_shows_traceback(tmp_path):
    """--debug re-raises so the traceback is visible."""
    db_path = tmp_path / "test.db"
    bad_csv = tmp_path / "chase_bad.csv"
    bad_csv.write_text(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "01/15/2025,01/16/2025,KROGER,Shopping,Sale,NOT_A_NUMBER,\n"
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["--debug", "--db", str(db_path), "ingest", "--files", str(bad_csv)])
    assert result.exit_code != 0
    # When --debug re-raises, Click's test runner captures the exception
    assert result.exception is not None


def test_cli_file_not_found(tmp_path):
    """Missing file referenced inside a valid directory shows clean error."""
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    # Click's exists=True validation catches this before our handler,
    # but it still gives a clean message (Click's built-in)
    result = runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", "/nonexistent/path.csv"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output


def test_cli_normal_commands_still_work(tmp_path):
    """Verify the error handler doesn't break normal operation."""
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "$" in result.output
