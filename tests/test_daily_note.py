import json

from click.testing import CliRunner

from cashflow.cli import cli
from cashflow.daily_note import update_frontmatter
from cashflow.db import get_connection
from cashflow.seed import seed_all

NOTE = """---
date: 2026-09-28
recovery: 94
positions: BMNR 27.56 (-1.7%)
---

## training
- spend_mtd: this line is in the body and must not change
"""


def test_existing_keys_are_replaced_and_new_keys_added_before_closing_marker():
    text = NOTE.replace("recovery: 94\n", "recovery: 94\nspend_mtd: 1\n")
    updated = update_frontmatter(text, {"spend_mtd": 14817, "free_cash": 1881})
    frontmatter, body = updated.split("\n---\n", 1)
    assert "spend_mtd: 14817" in frontmatter
    assert "spend_mtd: 1\n" not in frontmatter
    assert frontmatter.endswith("free_cash: 1881")
    assert "positions: BMNR 27.56 (-1.7%)" in frontmatter
    assert "- spend_mtd: this line is in the body and must not change" in body


def test_text_values_are_quoted_so_the_frontmatter_stays_valid_yaml():
    # morning.py reads this frontmatter with yaml.safe_load; an unquoted "des: price up" breaks it.
    message = 'newrez des: price up $209.14 | "quoted"'
    updated = update_frontmatter(NOTE, {"cash_alarms": message, "free_cash": 1881})
    [line] = [l for l in updated.splitlines() if l.startswith("cash_alarms:")]
    assert json.loads(line.removeprefix("cash_alarms: ")) == message
    assert "free_cash: 1881\n" in updated


def test_updating_twice_does_not_duplicate_keys():
    once = update_frontmatter(NOTE, {"free_cash": 1881})
    twice = update_frontmatter(once, {"free_cash": 1900})
    assert twice.count("free_cash:") == 1
    assert "free_cash: 1900" in twice


def _db_with_spending(tmp_path, extra_rows=()):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    seed_all(conn)
    account_id = conn.execute("SELECT id FROM accounts WHERE name = 'Checking'").fetchone()["id"]
    rows = [
        ("jun", "2026-06-10", 3000.0),
        ("jul", "2026-07-10", 3000.0),
        ("aug", "2026-08-10", 3000.0),
        ("sep", "2026-09-05", 1250.0),
        *extra_rows,
    ]
    for source_id, day, amount in rows:
        conn.execute(
            "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, "
            "status, source_type) VALUES (?, ?, ?, ?, 'm', ?, 'confirmed', 'csv')",
            (source_id, day, amount, source_id, account_id),
        )
    for month in ("06", "07", "08"):
        conn.execute(
            "INSERT INTO income (date, amount, source, description, source_id) VALUES (?, 5000, 'paycheck', 'p', ?)",
            (f"2026-{month}-15", f"pay-{month}"),
        )
    conn.commit()
    conn.close()
    return db_path


def _run(db_path, daily_dir, day="2026-09-28"):
    return CliRunner().invoke(cli, ["--db", str(db_path), "daily-note", "--dir", str(daily_dir), "--date", day])


def test_daily_note_writes_cashflow_state_into_frontmatter(tmp_path):
    db_path = _db_with_spending(tmp_path)
    note = tmp_path / "2026-09-28.md"
    note.write_text(NOTE)
    result = _run(db_path, tmp_path)
    assert result.exit_code == 0, result.output
    text = note.read_text()
    assert "spend_mtd: 1250\n" in text
    assert "spend_ceiling: 12000\n" in text
    assert "free_cash: 2000\n" in text  # 5,000 income − 3,000 burn, averaged over Jun–Aug
    assert "review_queue: 0\n" in text
    assert "recovery: 94\n" in text


def test_daily_note_leaves_missing_note_for_the_morning_template(tmp_path):
    db_path = _db_with_spending(tmp_path)
    result = _run(db_path, tmp_path)
    assert result.exit_code == 0, result.output
    assert "No daily note" in result.output
    assert not (tmp_path / "2026-09-28.md").exists()


def test_daily_note_lists_audit_alarms(tmp_path):
    uber = [(f"UBER *ONE MEMBERSHIP {m}", f"2026-{m}-15", 4.40) for m in ("07", "08", "09")]
    db_path = _db_with_spending(tmp_path, uber)
    note = tmp_path / "2026-09-28.md"
    note.write_text(NOTE)
    assert _run(db_path, tmp_path).exit_code == 0
    [alarms] = [line for line in note.read_text().splitlines() if line.startswith("cash_alarms:")]
    assert "new recurring charge" in alarms
