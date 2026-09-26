from datetime import date

import pytest

from cashflow.plans import (
    add_plan,
    defer_plan,
    set_status,
    update_plan,
    summarize,
    monthly_free_cash,
)
from cashflow.seed import seed_all


@pytest.fixture
def conn(db):
    seed_all(db)
    return db


def _history(conn, slug):
    return conn.execute(
        "SELECT h.* FROM plan_history h JOIN plans p ON h.plan_id = p.id WHERE p.slug = ? ORDER BY h.id",
        (slug,),
    ).fetchall()


def test_expected_cost_is_probability_times_midpoint(conn):
    add_plan(conn, "windows", "Upstairs windows", "home", cost_low=10000, cost_high=15000, probability=0.5)
    [line] = summarize(conn).lines
    assert line.expected == pytest.approx(0.5 * 12500)
    assert line.worst == 15000


def test_pick_one_parent_sums_children_expected_and_takes_max_worst(conn):
    add_plan(conn, "bookshelf", "Dining room bookshelf", "home", pick_one=True)
    add_plan(conn, "bookshelf-diy", "DIY", "home", parent="bookshelf", cost_low=1000, cost_high=2000, probability=0.6)
    add_plan(conn, "bookshelf-custom", "Custom", "home", parent="bookshelf", cost_low=5000, cost_high=8000, probability=0.3)
    parent = next(l for l in summarize(conn).lines if l.slug == "bookshelf")
    assert parent.expected == pytest.approx(0.6 * 1500 + 0.3 * 6500)
    assert parent.worst == 8000


def test_totals_count_parents_not_children_twice(conn):
    add_plan(conn, "bookshelf", "Bookshelf", "home", pick_one=True)
    add_plan(conn, "bookshelf-diy", "DIY", "home", parent="bookshelf", cost_low=1000, cost_high=2000, probability=1.0)
    add_plan(conn, "gwl", "Great Wolf Lodge", "trip", cost_low=600, cost_high=600, probability=1.0)
    summary = summarize(conn)
    assert summary.expected_total == pytest.approx(1500 + 600)
    assert summary.worst_total == pytest.approx(2000 + 600)


def test_pick_one_children_probabilities_cannot_exceed_one(conn):
    add_plan(conn, "summer-2027", "Summer 2027", "trip", pick_one=True)
    add_plan(conn, "rixos", "Rixos", "trip", parent="summer-2027", cost_low=8000, cost_high=10000, probability=0.6)
    with pytest.raises(ValueError, match="exceed 1"):
        add_plan(conn, "cruise", "Icon of the Seas", "trip", parent="summer-2027", cost_low=9000, cost_high=12000, probability=0.5)


def test_children_require_a_pick_one_parent(conn):
    add_plan(conn, "windows", "Windows", "home", cost_low=10000, cost_high=15000, probability=0.5)
    with pytest.raises(ValueError, match="pick-one"):
        add_plan(conn, "windows-front", "Front", "home", parent="windows", cost_low=1, cost_high=2, probability=0.5)


def test_unpriced_plan_is_flagged_and_excluded_from_totals(conn):
    add_plan(conn, "front-leak", "Front-of-house leak", "home", probability=1.0, necessity=True)
    summary = summarize(conn)
    [line] = summary.lines
    assert line.expected is None
    assert summary.expected_total == 0
    assert [l.slug for l in summary.unpriced] == ["front-leak"]


def test_done_and_dropped_plans_are_excluded(conn):
    add_plan(conn, "a", "A", "other", cost_low=100, cost_high=100, probability=1.0)
    add_plan(conn, "b", "B", "other", cost_low=200, cost_high=200, probability=1.0)
    add_plan(conn, "c", "C", "other", cost_low=400, cost_high=400, probability=1.0)
    set_status(conn, "a", "done")
    set_status(conn, "b", "dropped")
    summary = summarize(conn)
    assert [l.slug for l in summary.lines] == ["c"]
    assert summary.expected_total == 400


def test_set_status_records_history(conn):
    add_plan(conn, "gwl", "Great Wolf Lodge", "trip", cost_low=600, cost_high=900, probability=1.0)
    set_status(conn, "gwl", "committed", note="booked Nov 14-16")
    [created, committed] = _history(conn, "gwl")
    assert created["to_status"] == "idea"
    assert (committed["from_status"], committed["to_status"], committed["note"]) == ("idea", "committed", "booked Nov 14-16")


def test_invalid_status_rejected(conn):
    add_plan(conn, "gwl", "Great Wolf Lodge", "trip")
    with pytest.raises(ValueError, match="status"):
        set_status(conn, "gwl", "someday")


def test_defer_moves_earliest_and_records_why(conn):
    add_plan(conn, "sienna", "2027 Toyota Sienna", "vehicle", cost_low=45000, cost_high=55000,
             probability=0.7, earliest=date(2027, 3, 1))
    defer_plan(conn, "sienna", date(2028, 1, 1), note="Odyssey got tires + timing belt")
    [line] = summarize(conn).lines
    assert line.status == "deferred"
    assert line.earliest == date(2028, 1, 1)
    deferral = _history(conn, "sienna")[-1]
    assert deferral["old_earliest"] == "2027-03-01"
    assert deferral["new_earliest"] == "2028-01-01"
    assert deferral["note"] == "Odyssey got tires + timing belt"


def test_times_deferred_is_tracked(conn):
    add_plan(conn, "windows", "Windows", "home", cost_low=10000, cost_high=15000, probability=0.5,
             earliest=date(2027, 1, 1))
    defer_plan(conn, "windows", date(2027, 6, 1))
    defer_plan(conn, "windows", date(2028, 1, 1))
    [line] = summarize(conn).lines
    assert line.times_deferred == 2


def test_update_plan_revalidates_pick_one_probabilities(conn):
    add_plan(conn, "summer-2027", "Summer 2027", "trip", pick_one=True)
    add_plan(conn, "rixos", "Rixos", "trip", parent="summer-2027", cost_low=8000, cost_high=10000, probability=0.5)
    add_plan(conn, "japan", "Japan", "trip", parent="summer-2027", cost_low=15000, cost_high=20000, probability=0.2)
    update_plan(conn, "japan", probability=0.5)
    with pytest.raises(ValueError, match="exceed 1"):
        update_plan(conn, "japan", probability=0.6)


def test_cost_low_cannot_exceed_high(conn):
    with pytest.raises(ValueError, match="cost"):
        add_plan(conn, "x", "X", "other", cost_low=5000, cost_high=1000, probability=0.5)


def _txn(conn, source_id, day, amount, one_off=False, reimbursed=0.0):
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, "
        "is_one_off, reimbursed_amount, status, source_type) "
        "VALUES (?, ?, ?, 't', 't', 1, ?, ?, 'confirmed', 'csv')",
        (source_id, day, amount, 1 if one_off else 0, reimbursed),
    )


def _income(conn, source_id, day, amount):
    conn.execute(
        "INSERT INTO income (source_id, date, amount, source) VALUES (?, ?, ?, 'paycheck')",
        (source_id, day, amount),
    )


def test_monthly_free_cash_uses_last_three_complete_months_and_skips_one_offs(conn):
    for month in ("06", "07", "08"):
        _income(conn, f"inc-{month}", f"2026-{month}-15", 15000)
        _txn(conn, f"base-{month}", f"2026-{month}-10", 10000)
    _txn(conn, "japan", "2026-06-20", 9000, one_off=True)
    _txn(conn, "fsa", "2026-07-20", 300, reimbursed=300)
    _txn(conn, "current-month", "2026-09-05", 50000)
    _income(conn, "old", "2026-05-15", 99999)
    conn.commit()
    free = monthly_free_cash(conn, today=date(2026, 9, 26))
    assert free.income == pytest.approx(15000)
    assert free.baseline_burn == pytest.approx(10000)
    assert free.free == pytest.approx(5000)


def test_funding_gap_accumulates_by_earliest_date(conn):
    add_plan(conn, "gwl", "Great Wolf Lodge", "trip", cost_low=1000, cost_high=1000, probability=1.0,
             earliest=date(2026, 11, 1))
    add_plan(conn, "windows", "Windows", "home", cost_low=12000, cost_high=12000, probability=1.0,
             earliest=date(2027, 1, 1))
    add_plan(conn, "someday", "Someday thing", "purchase", cost_low=500, cost_high=500, probability=0.5)
    summary = summarize(conn, today=date(2026, 9, 26), monthly_free=2000)
    by_slug = {l.slug: l for l in summary.lines}
    # Nov is 2 months out: 2 * 2000 = 4000 available vs 1000 cumulative -> no gap
    assert by_slug["gwl"].cumulative_expected == pytest.approx(1000)
    assert by_slug["gwl"].gap == 0
    # Jan is 4 months out: 4 * 2000 = 8000 available vs 13000 cumulative -> 5000 gap
    assert by_slug["windows"].cumulative_expected == pytest.approx(13000)
    assert by_slug["windows"].gap == pytest.approx(5000)
    assert by_slug["someday"].cumulative_expected is None
