import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

STATUSES = ("idea", "researching", "planned", "committed", "deferred", "done", "dropped")
INACTIVE_STATUSES = ("done", "dropped")
KINDS = ("trip", "home", "vehicle", "purchase", "gift", "other")


@dataclass
class PlanLine:
    slug: str
    title: str
    kind: str
    status: str
    depth: int
    pick_one: bool
    necessity: bool
    cost_low: Optional[float]
    cost_high: Optional[float]
    probability: Optional[float]
    earliest: Optional[date]
    latest: Optional[date]
    expected: Optional[float]
    worst: Optional[float]
    times_deferred: int
    cumulative_expected: Optional[float] = None
    gap: Optional[float] = None


@dataclass
class PlanSummary:
    lines: list[PlanLine]
    expected_total: float
    worst_total: float
    unpriced: list[PlanLine]


@dataclass
class FreeCash:
    income: float
    baseline_burn: float
    months: int

    @property
    def free(self) -> float:
        return self.income - self.baseline_burn


def _get_plan(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM plans WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown plan '{slug}'")
    return row


def _validate_estimate(cost_low, cost_high, probability) -> None:
    if cost_low is not None and cost_high is not None and cost_low > cost_high:
        raise ValueError(f"cost_low {cost_low:,.0f} exceeds cost_high {cost_high:,.0f}")
    if probability is not None and not 0 <= probability <= 1:
        raise ValueError(f"probability {probability} must be between 0 and 1")


def _check_alternatives(conn, parent_id: int, probability: Optional[float], exclude_id: Optional[int] = None) -> None:
    if probability is None:
        return
    others = conn.execute(
        "SELECT COALESCE(SUM(probability), 0) FROM plans "
        f"WHERE parent_id = ? AND id IS NOT ? AND status NOT IN ({','.join('?' * len(INACTIVE_STATUSES))})",
        (parent_id, exclude_id, *INACTIVE_STATUSES),
    ).fetchone()[0]
    if others + probability > 1 + 1e-9:
        raise ValueError(
            f"pick-one alternatives would exceed 1 ({others:g} already assigned + {probability:g})"
        )


def _record(conn, plan_id, from_status, to_status, old_earliest=None, new_earliest=None, note=None) -> None:
    conn.execute(
        "INSERT INTO plan_history (plan_id, from_status, to_status, old_earliest, new_earliest, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (plan_id, from_status, to_status, old_earliest, new_earliest, note),
    )


def _iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None


def add_plan(
    conn: sqlite3.Connection,
    slug: str,
    title: str,
    kind: str,
    *,
    parent: Optional[str] = None,
    pick_one: bool = False,
    cost_low: Optional[float] = None,
    cost_high: Optional[float] = None,
    probability: Optional[float] = None,
    earliest: Optional[date] = None,
    latest: Optional[date] = None,
    necessity: bool = False,
) -> int:
    if kind not in KINDS:
        raise ValueError(f"Invalid kind '{kind}'; expected one of {', '.join(KINDS)}")
    _validate_estimate(cost_low, cost_high, probability)
    parent_id = None
    if parent:
        parent_row = _get_plan(conn, parent)
        if not parent_row["pick_one"]:
            raise ValueError(f"'{parent}' is not a pick-one plan; only pick-one plans have alternatives")
        parent_id = parent_row["id"]
        _check_alternatives(conn, parent_id, probability)
    with conn:
        cursor = conn.execute(
            "INSERT INTO plans (slug, title, parent_id, pick_one, kind, cost_low, cost_high, probability, "
            "earliest, latest, necessity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, title, parent_id, int(pick_one), kind, cost_low, cost_high, probability,
             _iso(earliest), _iso(latest), int(necessity)),
        )
        _record(conn, cursor.lastrowid, None, "idea", new_earliest=_iso(earliest))
    return cursor.lastrowid


def update_plan(
    conn: sqlite3.Connection,
    slug: str,
    *,
    cost_low: Optional[float] = None,
    cost_high: Optional[float] = None,
    probability: Optional[float] = None,
    earliest: Optional[date] = None,
    latest: Optional[date] = None,
) -> None:
    """Update estimate fields; arguments left as None are unchanged."""
    plan = _get_plan(conn, slug)
    new_low = plan["cost_low"] if cost_low is None else cost_low
    new_high = plan["cost_high"] if cost_high is None else cost_high
    new_probability = plan["probability"] if probability is None else probability
    _validate_estimate(new_low, new_high, new_probability)
    if plan["parent_id"] is not None and probability is not None:
        _check_alternatives(conn, plan["parent_id"], probability, exclude_id=plan["id"])
    with conn:
        conn.execute(
            "UPDATE plans SET cost_low = ?, cost_high = ?, probability = ?, "
            "earliest = COALESCE(?, earliest), latest = COALESCE(?, latest) WHERE id = ?",
            (new_low, new_high, new_probability, _iso(earliest), _iso(latest), plan["id"]),
        )


def set_status(conn: sqlite3.Connection, slug: str, status: str, note: Optional[str] = None) -> None:
    if status not in STATUSES:
        raise ValueError(f"Invalid status '{status}'; expected one of {', '.join(STATUSES)}")
    plan = _get_plan(conn, slug)
    with conn:
        conn.execute("UPDATE plans SET status = ? WHERE id = ?", (status, plan["id"]))
        _record(conn, plan["id"], plan["status"], status, note=note)


def defer_plan(conn: sqlite3.Connection, slug: str, until: date, note: Optional[str] = None) -> None:
    plan = _get_plan(conn, slug)
    latest = plan["latest"]
    # A window that ends before the new start date no longer means anything.
    if latest and date.fromisoformat(latest) < until:
        latest = None
    with conn:
        conn.execute(
            "UPDATE plans SET status = 'deferred', earliest = ?, latest = ? WHERE id = ?",
            (until.isoformat(), latest, plan["id"]),
        )
        _record(conn, plan["id"], plan["status"], "deferred",
                old_earliest=plan["earliest"], new_earliest=until.isoformat(), note=note)


def _to_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _leaf_estimate(row) -> tuple[Optional[float], Optional[float]]:
    low, high, probability = row["cost_low"], row["cost_high"], row["probability"]
    if low is None or high is None:
        return None, None
    worst = high if probability is None or probability > 0 else None
    if probability is None:
        return None, worst
    return probability * (low + high) / 2, worst


def _line(row, depth, expected, worst, times_deferred, earliest=None) -> PlanLine:
    return PlanLine(
        slug=row["slug"], title=row["title"], kind=row["kind"], status=row["status"], depth=depth,
        pick_one=bool(row["pick_one"]), necessity=bool(row["necessity"]),
        cost_low=row["cost_low"], cost_high=row["cost_high"], probability=row["probability"],
        earliest=earliest or _to_date(row["earliest"]), latest=_to_date(row["latest"]),
        expected=expected, worst=worst, times_deferred=times_deferred,
    )


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month


def summarize(
    conn: sqlite3.Connection,
    today: Optional[date] = None,
    monthly_free: Optional[float] = None,
) -> PlanSummary:
    rows = conn.execute(
        "SELECT * FROM plans "
        f"WHERE status NOT IN ({','.join('?' * len(INACTIVE_STATUSES))}) ORDER BY earliest IS NULL, earliest, id",
        INACTIVE_STATUSES,
    ).fetchall()
    deferrals = dict(conn.execute(
        "SELECT plan_id, COUNT(*) FROM plan_history WHERE to_status = 'deferred' GROUP BY plan_id"
    ).fetchall())
    children: dict[int, list] = {}
    for row in rows:
        if row["parent_id"] is not None:
            children.setdefault(row["parent_id"], []).append(row)

    top_level: list[PlanLine] = []
    lines: list[PlanLine] = []
    unpriced: list[PlanLine] = []
    for row in rows:
        if row["parent_id"] is not None:
            continue
        if row["pick_one"]:
            kids = children.get(row["id"], [])
            kid_lines = []
            for kid in kids:
                expected, worst = _leaf_estimate(kid)
                kid_lines.append(_line(kid, 1, expected, worst, deferrals.get(kid["id"], 0)))
            priced = [k.expected for k in kid_lines if k.expected is not None]
            worsts = [k.worst for k in kid_lines if k.worst is not None]
            kid_dates = [k.earliest for k in kid_lines if k.earliest]
            parent = _line(
                row, 0,
                sum(priced) if priced else None,
                max(worsts) if worsts else None,
                deferrals.get(row["id"], 0),
                earliest=_to_date(row["earliest"]) or (min(kid_dates) if kid_dates else None),
            )
            lines += [parent, *kid_lines]
            top_level.append(parent)
            unpriced += [k for k in kid_lines if k.expected is None]
        else:
            expected, worst = _leaf_estimate(row)
            line = _line(row, 0, expected, worst, deferrals.get(row["id"], 0))
            lines.append(line)
            top_level.append(line)
            if expected is None:
                unpriced.append(line)

    if today is not None and monthly_free is not None:
        cumulative = 0.0
        for line in sorted((l for l in top_level if l.earliest), key=lambda l: l.earliest):
            cumulative += line.expected or 0
            available = max(0, _months_between(today, line.earliest)) * monthly_free
            line.cumulative_expected = cumulative
            line.gap = max(0.0, cumulative - available)

    return PlanSummary(
        lines=lines,
        expected_total=sum(l.expected for l in top_level if l.expected is not None),
        worst_total=sum(l.worst for l in top_level if l.worst is not None),
        unpriced=unpriced,
    )


def monthly_free_cash(conn: sqlite3.Connection, today: date, months: int = 3) -> FreeCash:
    """Average income and baseline burn over the last `months` complete months.

    Baseline burn excludes one-off spending and nets out reimbursements.
    """
    end = date(today.year, today.month, 1)
    start_index = today.year * 12 + today.month - 1 - months
    start = date(start_index // 12, start_index % 12 + 1, 1)
    window = (start.isoformat(), end.isoformat())
    burn = conn.execute(
        "SELECT COALESCE(SUM(amount - reimbursed_amount), 0) FROM transactions "
        "WHERE canonical_id IS NULL AND is_one_off = 0 AND date >= ? AND date < ?",
        window,
    ).fetchone()[0]
    income = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM income WHERE date >= ? AND date < ?",
        window,
    ).fetchone()[0]
    return FreeCash(income=income / months, baseline_burn=burn / months, months=months)
