import re
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from cashflow.queries import not_savings

DECISIONS = ("keep", "cancel", "ignore")
NEW_WITHIN_DAYS = 90
_STALE_AFTER_DAYS = {"monthly": 45, "annual": 400}
_KEY_WORDS = 3


def recurring_key(description: str) -> str:
    """Normalize a card description so every charge from one service shares a key.

    Digits and punctuation are dropped because processors embed per-charge IDs
    (SQSP* WORKSP#251068321); the first three words keep distinct services apart
    (UBER *ONE MEMBERSHIP vs UBER *TRIP).
    """
    return " ".join(re.sub(r"[^a-z]+", " ", description.lower()).split()[:_KEY_WORDS])


@dataclass
class Recurring:
    key: str
    label: str
    category: Optional[str]
    cadence: str
    count: int
    first_seen: date
    last_seen: date
    amount: float
    latest_amount: float
    price_increase: Optional[float]
    active: bool
    is_new: bool
    decision: Optional[str]
    decided_on: Optional[date]
    charged_after_cancel: Optional[date]

    @property
    def annual_cost(self) -> float:
        return self.amount * 12 if self.cadence == "monthly" else self.amount

    @property
    def monthly_cost(self) -> float:
        return self.annual_cost / 12


@dataclass
class Spike:
    category: str
    month: date
    month_total: float
    median: float

    @property
    def delta(self) -> float:
        return self.month_total - self.median


def _cadence(dates: list[date], amounts: list[float]) -> Optional[str]:
    gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
    if not gaps:
        return None
    typical = statistics.median(amounts)
    recent = amounts[-3:]
    if (
        len(dates) >= 3
        and sum(20 <= gap <= 40 for gap in gaps) / len(gaps) >= 0.75
        and max(recent) - min(recent) <= max(3.0, 0.35 * typical)
    ):
        return "monthly"
    if all(330 <= gap <= 400 for gap in gaps) and max(amounts) - min(amounts) <= max(5.0, 0.25 * typical):
        return "annual"
    return None


def _price_increase(amounts: list[float]) -> Optional[float]:
    prior = amounts[-7:-1]
    if not prior:
        return None
    baseline = statistics.median(prior)
    delta = amounts[-1] - baseline
    return delta if delta > max(0.5, 0.05 * baseline) else None


def record_decision(
    conn: sqlite3.Connection, key: str, decision: str, today: date, note: Optional[str] = None
) -> None:
    if decision not in DECISIONS:
        raise ValueError(f"Invalid decision '{decision}'; expected one of {', '.join(DECISIONS)}")
    with conn:
        conn.execute(
            "INSERT INTO recurring_reviews (key, decision, decided_on, note) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET decision = excluded.decision, "
            "decided_on = excluded.decided_on, note = excluded.note",
            (key, decision, today.isoformat(), note),
        )


def find_recurring(conn: sqlite3.Connection, today: date, include_ignored: bool = False) -> list[Recurring]:
    rows = conn.execute(
        "SELECT t.date, t.amount, t.description, c.name AS category FROM transactions t "
        "LEFT JOIN categories c ON c.id = t.category_id "
        "WHERE t.canonical_id IS NULL AND t.amount > 0 ORDER BY t.date, t.id"
    ).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[recurring_key(row["description"])].append(row)
    decisions = {
        r["key"]: r for r in conn.execute("SELECT key, decision, decided_on FROM recurring_reviews")
    }

    found = []
    for key, charges in groups.items():
        dates = [date.fromisoformat(c["date"]) for c in charges]
        amounts = [c["amount"] for c in charges]
        cadence = _cadence(dates, amounts)
        if cadence is None:
            continue
        review = decisions.get(key)
        decision = review["decision"] if review else None
        if decision == "ignore" and not include_ignored:
            continue
        decided_on = date.fromisoformat(review["decided_on"]) if review else None
        charged_after_cancel = None
        if decision == "cancel":
            charged_after_cancel = next((d for d in dates if d > decided_on), None)
        active = (today - dates[-1]).days <= _STALE_AFTER_DAYS[cadence]
        found.append(Recurring(
            key=key,
            label=charges[-1]["description"],
            category=charges[-1]["category"],
            cadence=cadence,
            count=len(charges),
            first_seen=dates[0],
            last_seen=dates[-1],
            amount=statistics.median(amounts[-3:]),
            latest_amount=amounts[-1],
            price_increase=_price_increase(amounts),
            active=active,
            is_new=active and (today - dates[0]).days <= NEW_WITHIN_DAYS,
            decision=decision,
            decided_on=decided_on,
            charged_after_cancel=charged_after_cancel,
        ))
    return sorted(found, key=lambda r: r.annual_cost, reverse=True)


def _month_start(index: int) -> date:
    return date(index // 12, index % 12 + 1, 1)


def category_spikes(
    conn: sqlite3.Connection, today: date, lookback: int = 6, min_increase: float = 100.0, ratio: float = 1.5
) -> list[Spike]:
    """Categories whose last complete month ran well above their prior median.

    One-offs are excluded so a planned trip doesn't read as a spending problem.
    """
    target = today.year * 12 + today.month - 2
    history = [_month_start(target - offset) for offset in range(lookback, 0, -1)]
    target_month = _month_start(target)
    rows = conn.execute(
        "SELECT c.name AS category, strftime('%Y-%m', t.date) AS month, "
        "SUM(t.amount - t.reimbursed_amount) AS total FROM transactions t "
        "JOIN categories c ON c.id = t.category_id "
        f"WHERE t.canonical_id IS NULL AND t.is_one_off = 0 AND {not_savings('t')} AND t.date >= ? AND t.date < ? "
        "GROUP BY c.name, month",
        (history[0].isoformat(), _month_start(target + 1).isoformat()),
    ).fetchall()
    totals: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        totals[row["category"]][row["month"]] = row["total"]

    spikes = []
    for category, by_month in totals.items():
        median = statistics.median(by_month.get(m.strftime("%Y-%m"), 0.0) for m in history)
        current = by_month.get(target_month.strftime("%Y-%m"), 0.0)
        if current - median >= min_increase and current >= ratio * median:
            spikes.append(Spike(category, target_month, current, median))
    return sorted(spikes, key=lambda s: s.delta, reverse=True)
