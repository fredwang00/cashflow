from click.testing import CliRunner
from pathlib import Path
from cashflow.cli import cli

def test_status_command_runs(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "ceiling" in result.output.lower() or "$" in result.output

def test_ingest_then_status(tmp_path):
    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(fixture)])
    assert result.exit_code == 0
    assert "new transactions" in result.output
    result = runner.invoke(cli, ["--db", str(db_path), "status"])
    assert result.exit_code == 0
    assert "$" in result.output

def test_tag_one_off(tmp_path):
    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()

    # Ingest first
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(fixture)])

    # Tag transaction 1 as one-off
    result = runner.invoke(
        cli, ["--db", str(db_path), "tag", "1", "--one-off", "NAS build"]
    )
    assert result.exit_code == 0
    assert "tagged" in result.output.lower() or "one-off" in result.output.lower()


def test_recategorize(tmp_path):
    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()

    # Ingest first
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(fixture)])

    # Add a target category
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES ('Consumer Electronics', 'want')")
    conn.commit()
    conn.close()

    # Recategorize transaction 1
    result = runner.invoke(
        cli, ["--db", str(db_path), "recategorize", "1", "Consumer Electronics"]
    )
    assert result.exit_code == 0
    assert "consumer electronics" in result.output.lower()

    # Verify in DB
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT c.name FROM transactions t JOIN categories c ON t.category_id = c.id WHERE t.id = 1"
    ).fetchone()
    assert row["name"] == "Consumer Electronics"


def test_recategorize_invalid_category(tmp_path):
    db_path = tmp_path / "test.db"
    fixture = Path(__file__).parent / "fixtures" / "chase_sample.csv"
    runner = CliRunner()

    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(fixture)])

    result = runner.invoke(
        cli, ["--db", str(db_path), "recategorize", "1", "Nonexistent Category"]
    )
    assert result.exit_code == 0
    assert "not found" in result.output.lower() or "no category" in result.output.lower()


def test_ingest_expense_report(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.db"
    fixture_xlsx = Path(__file__).parent / "fixtures" / "expense_report_sample.xlsx"
    runner = CliRunner()

    # Seed DB and insert a transaction that matches the fixture (2025-04-12, $53.94)
    runner.invoke(cli, ["--db", str(db_path), "status"])  # triggers seed
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    acct_id = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
        "VALUES ('er-test-1', '2025-04-12', 53.94, 'UBER *TRIP', 'Uber', ?, 'confirmed', 100, 'fred', 'csv')",
        (acct_id,),
    )
    conn.commit()
    conn.close()

    # Ingest expense report
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--expense-report", str(fixture_xlsx)]
    )
    assert result.exit_code == 0
    assert "1 matched" in result.output

    # Verify the flag was actually set
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT is_reimbursed FROM transactions WHERE source_id = 'er-test-1'").fetchone()
    assert row["is_reimbursed"] == 1
    conn.close()


def test_recategorize_invalid_txn(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()

    result = runner.invoke(
        cli, ["--db", str(db_path), "recategorize", "9999", "Groceries"]
    )
    assert result.exit_code == 0
    assert "not found" in result.output.lower()
