import pytest
from click.testing import CliRunner

from cashflow.cli import cli


@pytest.fixture
def run(tmp_path):
    db_path = str(tmp_path / "test.db")
    runner = CliRunner()

    def _run(*args, input=None):
        return runner.invoke(cli, ["--db", db_path, *args], input=input)

    return _run


def test_plan_add_and_view_shows_expected_cost(run):
    result = run("plan", "add", "windows", "Upstairs windows", "--kind", "home",
                 "--cost", "10k-15k", "--p", "0.5", "--from", "2027-04")
    assert result.exit_code == 0, result.output
    result = run("plan")
    assert result.exit_code == 0, result.output
    assert "Upstairs windows" in result.output
    assert "$10,000–15,000" in result.output
    assert "$6,250" in result.output  # 0.5 * (10,000 + 15,000) / 2


def test_plan_view_shows_pick_one_alternatives(run):
    run("plan", "add", "bookshelf", "Dining room bookshelf", "--kind", "home", "--pick-one")
    run("plan", "add", "bookshelf-diy", "DIY / Marketplace", "--kind", "home",
        "--parent", "bookshelf", "--cost", "1000-2000", "--p", "0.6")
    run("plan", "add", "bookshelf-custom", "Full custom", "--kind", "home",
        "--parent", "bookshelf", "--cost", "5000-8000", "--p", "0.3")
    result = run("plan")
    assert "pick one" in result.output
    assert "$2,850" in result.output  # 0.6 * 1,500 + 0.3 * 6,500


def test_plan_defer_shows_deferred_status(run):
    run("plan", "add", "sienna", "2027 Toyota Sienna", "--kind", "vehicle",
        "--cost", "45k-55k", "--p", "0.7", "--from", "2027-03")
    result = run("plan", "defer", "sienna", "2028-01", "--note", "Odyssey got tires + timing belt")
    assert result.exit_code == 0, result.output
    assert "2028-01-01" in result.output
    result = run("plan")
    assert "deferred" in result.output


def test_plan_status_and_set(run):
    run("plan", "add", "gwl", "Great Wolf Lodge", "--kind", "trip")
    assert run("plan", "set", "gwl", "--cost", "600-900", "--p", "1", "--from", "2026-11").exit_code == 0
    assert run("plan", "status", "gwl", "committed", "--note", "booked").exit_code == 0
    result = run("plan")
    assert "committed" in result.output
    assert "$750" in result.output


def test_plan_unpriced_is_called_out(run):
    run("plan", "add", "front-leak", "Front-of-house leak", "--kind", "home", "--p", "1", "--necessity")
    result = run("plan")
    assert "Needs estimate" in result.output
    assert "front-leak" in result.output


def test_plan_validation_errors_are_clean(run):
    run("plan", "add", "summer", "Summer 2027", "--kind", "trip", "--pick-one")
    run("plan", "add", "rixos", "Rixos", "--kind", "trip", "--parent", "summer", "--cost", "8k-10k", "--p", "0.7")
    result = run("plan", "add", "cruise", "Cruise", "--kind", "trip", "--parent", "summer", "--cost", "9k-12k", "--p", "0.5")
    assert result.exit_code != 0
    assert "exceed 1" in result.output
    assert "Traceback" not in result.output


def test_money_formats_negatives_with_leading_sign():
    from cashflow.plan_cli import _money
    assert _money(-18972.4) == "−$18,972"
    assert _money(541) == "$541"


def test_plan_bad_cost_format(run):
    result = run("plan", "add", "x", "X", "--kind", "other", "--cost", "lots")
    assert result.exit_code != 0
    assert "cost" in result.output.lower()
