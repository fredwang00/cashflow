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
