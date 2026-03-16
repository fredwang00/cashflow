from pathlib import Path
from click.testing import CliRunner
from cashflow.cli import cli

CHASE_FIXTURE = Path(__file__).parent / "fixtures" / "chase_sample.csv"
AMAZON_FIXTURE = Path(__file__).parent / "fixtures" / "amazon_orders_sample.txt"


def test_ingest_amazon_orders(tmp_path):
    db_path = tmp_path / "test.db"
    runner = CliRunner()
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--files", str(AMAZON_FIXTURE)]
    )
    assert result.exit_code == 0
    assert "Amazon items" in result.output


def test_ingest_directory_with_mixed_files(tmp_path):
    db_path = tmp_path / "test.db"
    inbox = tmp_path / "inbox"
    inbox.mkdir()

    import shutil
    shutil.copy(CHASE_FIXTURE, inbox / "chase-prime-mar-2026.csv")
    shutil.copy(AMAZON_FIXTURE, inbox / "amazon-orders-fred.txt")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--db", str(db_path), "ingest", "--files", str(inbox)]
    )
    assert result.exit_code == 0
    assert "new transactions" in result.output
    assert "Amazon items" in result.output
