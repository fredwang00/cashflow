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
