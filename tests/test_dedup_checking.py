import sqlite3

from click.testing import CliRunner

from cashflow.cli import cli


def test_checking_ingest_preserves_distinct_equal_payments(tmp_path, monkeypatch):
    """Equal-day payments to different recipients must both count as spending."""
    monkeypatch.setattr("cashflow.cli.categorize_by_llm", lambda conn: (0, 0))
    export = tmp_path / "bofa-checking.csv"
    export.write_text(
        "Date,Description,Amount,Running Bal.\n"
        "04/01/2026,Zelle payment to Alice Conf# aaa,-50.00,100.00\n"
        "04/01/2026,Zelle payment to Bob Conf# bbb,-50.00,50.00\n"
    )
    database = tmp_path / "test.db"
    runner = CliRunner()
    arguments = ["--db", str(database), "ingest", "--files", str(export)]
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*), SUM(amount) FROM transactions WHERE canonical_id IS NULL"
        ).fetchone() == (2, 100.0)

    # Reimporting the same source rows remains idempotent.
    result = runner.invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
