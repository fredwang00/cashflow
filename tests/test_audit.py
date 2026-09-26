from datetime import date, timedelta

import pytest

from cashflow.audit import (
    category_spikes,
    find_recurring,
    recurring_key,
    record_decision,
)
from cashflow.seed import seed_all

TODAY = date(2026, 9, 26)


@pytest.fixture
def conn(db):
    seed_all(db)
    return db


_counter = 0


def _txn(conn, day, amount, description, category="Shopping", one_off=False):
    global _counter
    _counter += 1
    conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'want')", (category,))
    cat = conn.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()
    conn.execute(
        "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, category_id, "
        "is_one_off, status, source_type) VALUES (?, ?, ?, ?, ?, 1, ?, ?, 'confirmed', 'csv')",
        (f"t{_counter}", day.isoformat(), amount, description, description[:10], cat["id"], int(one_off)),
    )
    conn.commit()


def _monthly(conn, description, amounts, last=date(2026, 9, 16), category="Streaming"):
    for i, amount in enumerate(reversed(amounts)):
        _txn(conn, last - timedelta(days=30 * i), amount, description, category)


def _by_key(items):
    return {item.key: item for item in items}


def test_recurring_key_strips_charge_ids_but_keeps_distinct_services():
    assert recurring_key("SQSP* WORKSP#251068321 SQUARESPACE.CNY") == recurring_key("SQSP* WORKSP#246992230 SQUARESPACE.CNY")
    assert recurring_key("UBER *ONE MEMBERSHIP UBERAmsterdam") != recurring_key("UBER *TRIP HELP.UBER.COMCA")


def test_monthly_charge_with_drifting_amount_is_recurring(conn):
    _monthly(conn, "UBER *ONE MEMBERSHIP UBERAmsterdam", [3.08, 4.40, 4.55], category="Auto")
    [uber] = find_recurring(conn, TODAY)
    assert uber.cadence == "monthly"
    assert uber.active
    assert uber.monthly_cost == pytest.approx(4.40)
    assert uber.annual_cost == pytest.approx(4.40 * 12)


def test_irregular_habit_is_not_recurring(conn):
    start = date(2026, 1, 1)
    for offset in (0, 6, 50, 70, 115, 121, 170):
        _txn(conn, start + timedelta(days=offset), 10.09, "BURGER KING #4512", "Fast Food")
    assert find_recurring(conn, TODAY) == []


def test_many_charges_per_month_are_not_recurring(conn):
    start = date(2026, 6, 1)
    for offset in range(0, 90, 3):
        _txn(conn, start + timedelta(days=offset), 30.0, "UBER *TRIP HELP.UBER.COMCA", "Auto")
    assert find_recurring(conn, TODAY) == []


def test_annual_charge_is_recurring(conn):
    _txn(conn, date(2025, 4, 2), 79.0, "PUBLICGOODS.COM PUBLICGOODS")
    _txn(conn, date(2026, 4, 2), 79.0, "PUBLICGOODS.COM PUBLICGOODS")
    [pg] = find_recurring(conn, TODAY)
    assert pg.cadence == "annual"
    assert pg.annual_cost == pytest.approx(79.0)
    assert pg.monthly_cost == pytest.approx(79.0 / 12)


def test_stopped_charge_is_inactive(conn):
    _monthly(conn, "GOOGLE *YOUTUBE TV", [82.99] * 6, last=date(2026, 1, 31))
    [yttv] = find_recurring(conn, TODAY)
    assert not yttv.active


def test_new_recurring_charge_is_flagged(conn):
    _monthly(conn, "UBER *ONE MEMBERSHIP", [4.40] * 3, last=date(2026, 9, 16))
    _monthly(conn, "CRUNCHYROLL CA", [7.99] * 12, last=date(2026, 9, 17))
    items = _by_key(find_recurring(conn, TODAY))
    assert items[recurring_key("UBER *ONE MEMBERSHIP")].is_new
    assert not items[recurring_key("CRUNCHYROLL CA")].is_new


def test_price_increase_is_flagged(conn):
    _monthly(conn, "GOOGLE *YOUTUBEPREMIUM CA", [17.99] * 5 + [22.99])
    [yt] = find_recurring(conn, TODAY)
    assert yt.price_increase == pytest.approx(5.0)


def test_steady_price_has_no_increase(conn):
    _monthly(conn, "CRUNCHYROLL CA", [7.99] * 6)
    [cr] = find_recurring(conn, TODAY)
    assert cr.price_increase is None


def test_refunds_and_linked_duplicates_are_ignored(conn):
    _monthly(conn, "CRUNCHYROLL CA", [7.99] * 3)
    _txn(conn, date(2026, 9, 18), -7.99, "CRUNCHYROLL CA")
    _txn(conn, date(2026, 9, 16), 7.99, "CRUNCHYROLL CA")
    duplicate_id = conn.execute("SELECT MAX(id) FROM transactions").fetchone()[0]
    conn.execute("UPDATE transactions SET canonical_id = 1 WHERE id = ?", (duplicate_id,))
    conn.commit()
    [cr] = find_recurring(conn, TODAY)
    assert cr.count == 3


def test_decisions_are_attached_and_ignored_are_hidden(conn):
    _monthly(conn, "CRUNCHYROLL CA", [7.99] * 6)
    _txn(conn, date(2025, 8, 6), 38.65, "TILLYS VIRGINIA BEACVA", "Clothing")
    _txn(conn, date(2026, 8, 6), 38.65, "TILLYS VIRGINIA BEACVA", "Clothing")
    record_decision(conn, recurring_key("CRUNCHYROLL CA"), "keep", today=TODAY)
    record_decision(conn, recurring_key("TILLYS VIRGINIA BEACVA"), "ignore", today=TODAY)
    [cr] = find_recurring(conn, TODAY)
    assert cr.decision == "keep"


def test_charge_after_cancel_is_flagged(conn):
    _monthly(conn, "SQSP* WORKSP#1 SQUARESPACE.CNY", [8.40] * 6, last=date(2026, 8, 17))
    record_decision(conn, recurring_key("SQSP* WORKSP#1 SQUARESPACE.CNY"), "cancel", today=date(2026, 8, 20))
    [before] = find_recurring(conn, TODAY)
    assert before.charged_after_cancel is None
    _txn(conn, date(2026, 9, 17), 8.40, "SQSP* WORKSP#251068321 SQUARESPACE.CNY", "Streaming")
    [after] = find_recurring(conn, TODAY)
    assert after.charged_after_cancel == date(2026, 9, 17)


def test_invalid_decision_rejected(conn):
    with pytest.raises(ValueError, match="decision"):
        record_decision(conn, "anything", "maybe", today=TODAY)


def test_category_spike_against_six_month_median(conn):
    for month in range(2, 8):
        _txn(conn, date(2026, month, 10), 400.0, "COSTCO WHSE", "Groceries")
        _txn(conn, date(2026, month, 12), 150.0, "TARGET", "Shopping")
    _txn(conn, date(2026, 8, 10), 950.0, "COSTCO WHSE", "Groceries")
    _txn(conn, date(2026, 8, 12), 180.0, "TARGET", "Shopping")
    _txn(conn, date(2026, 9, 5), 5000.0, "COSTCO WHSE", "Groceries")
    spikes = category_spikes(conn, TODAY)
    assert [(s.category, s.month_total, s.median) for s in spikes] == [("Groceries", 950.0, 400.0)]


def test_category_spike_ignores_one_offs(conn):
    for month in range(2, 8):
        _txn(conn, date(2026, month, 10), 100.0, "DELTA", "Travel")
    _txn(conn, date(2026, 8, 10), 100.0, "DELTA", "Travel")
    _txn(conn, date(2026, 8, 11), 4000.0, "ANA JAPAN", "Travel", one_off=True)
    assert category_spikes(conn, TODAY) == []
