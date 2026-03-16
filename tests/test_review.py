from pathlib import Path
from click.testing import CliRunner
from cashflow.cli import cli

FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"


def test_review_shows_pending_transactions(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()

    # Ingest first (without API key, LLM will be skipped)
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(FIXTURE)])

    # Review with 's' to skip all
    result = runner.invoke(
        cli, ["--db", str(db_path), "review"], input="s\ns\ns\ns\ns\ns\n"
    )
    assert result.exit_code == 0
    assert "merchant" in result.output.lower() or "$" in result.output


def test_review_empty_queue(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "review"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "no" in result.output.lower()
