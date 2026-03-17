from pathlib import Path
from click.testing import CliRunner
from cashflow.cli import cli

FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"


def test_review_runs_after_ingest(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()

    # Ingest first
    runner.invoke(cli, ["--db", str(db_path), "ingest", "--files", str(FIXTURE)])

    # Review — may have pending items or empty queue (if rules categorized everything)
    result = runner.invoke(
        cli, ["--db", str(db_path), "review"], input="s\ns\ns\ns\ns\ns\n"
    )
    assert result.exit_code == 0
    # Either shows transactions to review or reports empty queue
    assert "$" in result.output or "empty" in result.output.lower() or "review" in result.output.lower()


def test_review_empty_queue(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(cli, ["--db", str(db_path), "review"])
    assert result.exit_code == 0
    assert "empty" in result.output.lower() or "no" in result.output.lower()
