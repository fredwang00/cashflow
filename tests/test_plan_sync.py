import sqlite3
from datetime import date

import pytest
from click.testing import CliRunner

from cashflow import plan_sync
from cashflow.cli import cli
from cashflow.daily_note import daily_note_fields
from cashflow.db import get_connection
from cashflow.plans import add_plan, summarize
from cashflow.seed import seed_all

CHINA = """---
name: China 2027
plan:
  slug: china-2027
  title: China + Hong Kong family trip
  kind: trip
  status: committed
  cost: 21.7k-29.5k
  p: 1
  window: 2027-06
  paid: 8026
  revisit: 2027-02-01
  go_no_go:
    - Passports renewed
    - Visas approved
---

# China 2027
"""

MINIVAN = """---
plan:
  slug: minivan
  title: Replace the Odyssey
  kind: vehicle
  status: researching
  necessity: true
  revisit: 2027-01-15
  go_no_go: ["Odyssey fails inspection or needs >$3k of work"]
  options:
    - slug: minivan-2027
      title: Sienna in 2027
      cost: [50000, 56000]
      p: 0.4
      window: [2027-03, 2027-12]
    - slug: minivan-2028
      title: Sienna in 2028
      cost: 50k-56k
      p: 0.6
      window: [2028-01, 2028-12]
---
"""

EUROPE = """---
plan:
  slug: europe-2028
  title: Europe on Avios
  kind: trip
  cost: 4k-8k
  p: 0.6
  window: [2028-04, 2028-06]
  points: {program: wf, needed: 136k}
---
"""


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "china-2027").mkdir(parents=True)
    (root / "projects/home/sienna").mkdir(parents=True)
    (root / "china-2027/README.md").write_text(CHINA)
    (root / "projects/home/sienna/decision.md").write_text(MINIVAN)
    (root / "europe.md").write_text(EUROPE)
    (root / "notes.md").write_text("---\nname: no plan here\n---\nplan: in the body, not a card\n")
    return root


@pytest.fixture
def conn(db):
    seed_all(db)
    return db


def _sync(conn, root):
    cards, errors = plan_sync.find_cards(root)
    assert errors == []
    result = plan_sync.diff(conn, cards)
    plan_sync.apply(conn, result)
    return result


def _row(conn, slug):
    return conn.execute("SELECT * FROM plans WHERE slug = ?", (slug,)).fetchone()


def test_cards_parse_costs_windows_points_and_options(vault):
    cards, errors = plan_sync.find_cards(vault)
    assert errors == []
    by_slug = {c.slug: c for c in cards}
    assert set(by_slug) == {"china-2027", "minivan", "minivan-2027", "minivan-2028", "europe-2028"}
    china = by_slug["china-2027"]
    assert (china.cost_low, china.cost_high) == (21700, 29500)
    assert china.earliest == "2027-06-01" and china.latest is None
    assert china.source_path == "china-2027/README.md"
    assert by_slug["minivan"].pick_one and by_slug["minivan-2028"].parent == "minivan"
    assert by_slug["minivan-2028"].kind == "vehicle"  # inherited
    assert by_slug["minivan-2028"].necessity
    assert (by_slug["europe-2028"].points_program, by_slug["europe-2028"].points_needed) == ("wf", 136000)


def test_sync_adds_plans_with_status_and_history(conn, vault):
    result = _sync(conn, vault)
    assert {c.action for c in result.changes} == {"add"}
    assert _row(conn, "china-2027")["status"] == "committed"
    assert _row(conn, "minivan-2027")["parent_id"] == _row(conn, "minivan")["id"]
    history = conn.execute("SELECT note FROM plan_history").fetchall()
    assert len(history) == 5
    assert all(h["note"].startswith("plan sync: ") for h in history)


def test_second_sync_is_a_no_op(conn, vault):
    _sync(conn, vault)
    cards, _ = plan_sync.find_cards(vault)
    result = plan_sync.diff(conn, cards)
    assert result.changes == []
    assert len(result.unchanged) == 5


def test_paid_is_left_out_of_expected_and_worst(conn, vault):
    _sync(conn, vault)
    china = next(l for l in summarize(conn).lines if l.slug == "china-2027")
    assert china.expected == pytest.approx((21700 + 29500) / 2 - 8026)
    assert china.worst == pytest.approx(29500 - 8026)
    assert china.paid == 8026


def test_status_change_and_deferral_are_recorded(conn, vault):
    _sync(conn, vault)
    path = vault / "europe.md"
    path.write_text(EUROPE.replace("  p: 0.6\n", "  p: 0.6\n  status: deferred\n").replace("[2028-04, 2028-06]", "[2029-04, 2029-06]"))
    _sync(conn, vault)
    path.write_text(path.read_text().replace("[2029-04, 2029-06]", "[2030-04, 2030-06]"))
    _sync(conn, vault)
    europe = next(l for l in summarize(conn).lines if l.slug == "europe-2028")
    assert europe.status == "deferred"
    assert europe.times_deferred == 2
    assert europe.earliest == date(2030, 4, 1)


def test_shifting_probability_between_options_is_allowed(conn, vault):
    _sync(conn, vault)
    path = vault / "projects/home/sienna/decision.md"
    path.write_text(MINIVAN.replace("p: 0.4", "p: TMP").replace("p: 0.6", "p: 0.4").replace("p: TMP", "p: 0.6"))
    result = _sync(conn, vault)
    assert {c.card.slug for c in result.changes} == {"minivan-2027", "minivan-2028"}
    assert _row(conn, "minivan-2027")["probability"] == 0.6


def test_bad_card_is_reported_and_others_still_sync(conn, vault):
    (vault / "bad.md").write_text("---\nplan:\n  slug: bad\n  kind: yacht\n---\n")
    cards, errors = plan_sync.find_cards(vault)
    assert len(cards) == 5
    assert len(errors) == 1 and "bad.md" in errors[0] and "kind" in errors[0]


@pytest.mark.parametrize("card, message", [
    ("  slug: x\n  kind: trip\n  cost: 5k-1k\n", "low exceeds high"),
    ("  slug: x\n  kind: trip\n  p: 2\n", "between 0 and 1"),
    ("  slug: x\n  kind: trip\n  window: [2027-06, 2027-01]\n", "latest is before earliest"),
    ("  slug: x\n  kind: trip\n  cost: 5k\n  options:\n    - {slug: y, cost: 1k}\n", "on its options"),
    ("  slug: x\n  kind: trip\n  options:\n    - {slug: y, p: 0.7}\n    - {slug: z, p: 0.5}\n", "more than 1"),
    ("  slug: Bad Slug\n  kind: trip\n", "lowercase"),
])
def test_invalid_cards_name_the_problem(tmp_path, card, message):
    (tmp_path / "x.md").write_text(f"---\nplan:\n{card}---\n")
    cards, errors = plan_sync.find_cards(tmp_path)
    assert cards == []
    assert message in errors[0]


def test_duplicate_slug_across_files_is_an_error(vault):
    (vault / "copy.md").write_text(EUROPE)
    cards, errors = plan_sync.find_cards(vault)
    assert any("already defined" in e for e in errors)
    assert sum(c.slug == "europe-2028" for c in cards) == 1


def test_removed_card_is_reported_not_deleted(conn, vault):
    _sync(conn, vault)
    (vault / "europe.md").unlink()
    cards, _ = plan_sync.find_cards(vault)
    result = plan_sync.diff(conn, cards)
    assert result.orphaned == ["europe-2028"]
    assert _row(conn, "europe-2028") is not None


def test_hand_added_plans_are_not_orphans(conn, vault):
    add_plan(conn, "windows", "Upstairs windows", "home")
    cards, _ = plan_sync.find_cards(vault)
    assert plan_sync.diff(conn, cards).orphaned == []


def test_due_plans_and_first_gap(conn, vault):
    _sync(conn, vault)
    summary = summarize(conn, today=date(2027, 1, 20), monthly_free=1000)
    assert [l.slug for l in summary.due] == ["minivan"]
    assert summary.first_gap.slug == "minivan-2027"  # the 2027 option (2027-03) comes before China (2027-06)


def test_existing_database_gets_plan_card_columns(tmp_path):
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(db_path)
    old.execute("CREATE TABLE plans (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, "
                "parent_id INTEGER, pick_one BOOLEAN NOT NULL DEFAULT 0, kind TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'idea', cost_low REAL, cost_high REAL, probability REAL, "
                "earliest DATE, latest DATE, necessity BOOLEAN NOT NULL DEFAULT 0, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)")
    old.execute("INSERT INTO plans (slug, title, kind) VALUES ('windows', 'Windows', 'home')")
    old.commit()
    old.close()
    conn = get_connection(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(plans)")}
    assert {"source_path", "paid", "revisit", "go_no_go", "points_program", "points_needed"} <= cols
    assert _row(conn, "windows")["paid"] == 0


def test_daily_note_fields_include_plans(conn, vault):
    _sync(conn, vault)
    fields = daily_note_fields(conn, date(2027, 1, 20))
    assert fields["plans_due"] == "minivan"
    assert fields["plans_gap"].startswith("minivan-2027 -$")  # no income in the test db, so the first plan is short
    assert "by 2027-03" in fields["plans_gap"]


def test_cli_dry_run_writes_nothing_then_sync_applies(tmp_path, vault):
    db_path = str(tmp_path / "cli.db")
    runner = CliRunner()
    dry = runner.invoke(cli, ["--db", db_path, "plan", "sync", "--root", str(vault), "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "+ china-2027 (committed)" in dry.output and "(dry run)" in dry.output
    assert get_connection(tmp_path / "cli.db").execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
    real = runner.invoke(cli, ["--db", db_path, "plan", "sync", "--root", str(vault)])
    assert real.exit_code == 0, real.output
    assert "applied" in real.output
    view = runner.invoke(cli, ["--db", db_path, "plan"])
    assert "Already paid" in view.output and "china-2027 $8,026" in view.output
    assert "europe-2028 136,000 wf" in view.output


def test_cli_sync_fails_loudly_on_bad_cards_but_applies_good_ones(tmp_path, vault):
    (vault / "bad.md").write_text("---\nplan:\n  slug: bad\n  kind: yacht\n---\n")
    db_path = str(tmp_path / "cli.db")
    result = CliRunner().invoke(cli, ["--db", db_path, "plan", "sync", "--root", str(vault)])
    assert result.exit_code != 0
    assert "bad.md" in result.output
    assert get_connection(tmp_path / "cli.db").execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 5


def test_pick_one_options_land_on_their_own_dates_in_the_gap(conn, vault):
    path = vault / "projects/home/sienna/decision.md"
    path.write_text(MINIVAN.replace("p: 0.4", "p: 0.05").replace("p: 0.6", "p: 0.95"))
    _sync(conn, vault)
    summary = summarize(conn, today=date(2026, 11, 4), monthly_free=0)
    by_slug = {l.slug: l for l in summary.lines}
    assert by_slug["minivan-2027"].cumulative_expected == pytest.approx(0.05 * 53000)
    # China (June 2027) sits between the two options; only 5% of the van counts before it
    assert by_slug["china-2027"].cumulative_expected == pytest.approx(0.05 * 53000 + (21700 + 29500) / 2 - 8026)
    assert by_slug["minivan-2028"].cumulative_expected == pytest.approx(
        by_slug["china-2027"].cumulative_expected + 0.95 * 53000)
    slugs = [l.slug for l in summary.lines if l.depth == 0]
    assert slugs.index("minivan") < slugs.index("china-2027")  # parent sorts by its earliest option


def test_next_step_syncs_and_daily_note_offers_needs_first(conn, vault):
    europe = vault / "europe.md"
    europe.write_text(EUROPE.replace("  p: 0.6\n", "  p: 0.6\n  next: Open Iberia Plus accounts\n"))
    minivan = vault / "projects/home/sienna/decision.md"
    minivan.write_text(MINIVAN.replace("  necessity: true\n", "  necessity: true\n  next: Note the Odyssey mileage\n"))
    _sync(conn, vault)
    summary = summarize(conn, today=date(2026, 11, 4), monthly_free=0)
    assert summary.next_up.slug == "minivan"  # a need beats a want even though Europe has a step too
    fields = daily_note_fields(conn, date(2026, 11, 4))
    assert fields["plans_next"] == "minivan: Note the Odyssey mileage"
    # changing the step is a normal update
    minivan.write_text(minivan.read_text().replace("Note the Odyssey mileage", "Book the inspection"))
    result = _sync(conn, vault)
    assert [c.fields["next_step"][1] for c in result.changes] == ["Book the inspection"]


def test_next_up_is_empty_without_steps(conn, vault):
    _sync(conn, vault)
    assert summarize(conn, today=date(2026, 11, 4)).next_up is None
    assert daily_note_fields(conn, date(2026, 11, 4))["plans_next"] == ""


def test_cli_lists_next_steps_with_todays_marked(tmp_path, vault):
    (vault / "europe.md").write_text(EUROPE.replace("  p: 0.6\n", "  p: 0.6\n  next: Open Iberia Plus accounts\n"))
    db_path = str(tmp_path / "cli.db")
    runner = CliRunner()
    runner.invoke(cli, ["--db", db_path, "plan", "sync", "--root", str(vault)])
    view = runner.invoke(cli, ["--db", db_path, "plan"])
    assert "Next steps:" in view.output
    assert "→ europe-2028: Open Iberia Plus accounts" in view.output
