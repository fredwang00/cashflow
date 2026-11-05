"""Sync plans from `plan:` cards in clearwater frontmatter.

The project doc is the source of truth; the plans table is a cache that keeps history
(status changes, deferrals) so `cashflow plan` can weigh plans against free cash.

Card format (in any Markdown file's YAML frontmatter):

    plan:
      slug: china-2027
      title: China + Hong Kong family trip
      kind: trip
      status: committed
      cost: 21.7k-29.5k        # number, "low-high" with optional k, or [low, high]
      p: 1
      window: [2027-06, 2027-06]   # earliest, latest start (YYYY-MM or YYYY-MM-DD)
      paid: 8026               # already spent; only the rest counts as future cash
      revisit: 2027-02-01
      go_no_go: ["Passports renewed", "Visas approved"]
      points: {program: wf, needed: 136000}

A pick-one plan lists mutually exclusive alternatives under `options:`; each option takes
the same fields and inherits `kind` from the parent.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from cashflow.plans import INACTIVE_STATUSES, KINDS, STATUSES, _record

FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\s*(?:\n|\Z)", re.DOTALL)
SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", "tmp"}
SYNCED_FIELDS = (
    "title", "kind", "parent_id", "pick_one", "necessity", "cost_low", "cost_high", "probability",
    "earliest", "latest", "paid", "revisit", "go_no_go", "points_program", "points_needed", "source_path",
)


class CardError(ValueError):
    pass


@dataclass
class Card:
    slug: str
    title: str
    kind: str
    status: str = "idea"
    parent: Optional[str] = None
    pick_one: bool = False
    necessity: bool = False
    cost_low: Optional[float] = None
    cost_high: Optional[float] = None
    probability: Optional[float] = None
    earliest: Optional[str] = None
    latest: Optional[str] = None
    paid: float = 0.0
    revisit: Optional[str] = None
    go_no_go: Optional[str] = None  # JSON list, as stored
    points_program: Optional[str] = None
    points_needed: Optional[int] = None
    source_path: Optional[str] = None


@dataclass
class Change:
    card: Card
    action: str  # "add" | "update"
    fields: dict = field(default_factory=dict)  # name -> (old, new)
    status: Optional[tuple] = None  # (old, new)
    deferred: bool = False


@dataclass
class SyncResult:
    changes: list[Change] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _amount(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace("$", "").replace(",", "")
    multiplier = 1000 if text.endswith("k") else 1
    return float(text.rstrip("k")) * multiplier


def _cost(value) -> tuple[Optional[float], Optional[float]]:
    if value is None:
        return None, None
    if isinstance(value, (list, tuple)):
        parts = list(value)
    elif isinstance(value, str):
        parts = value.split("-")
    else:
        parts = [value]
    if not 1 <= len(parts) <= 2:
        raise CardError(f"cost {value!r}: expected an amount, 'low-high', or [low, high]")
    try:
        amounts = [_amount(p) for p in parts]
    except ValueError:
        raise CardError(f"cost {value!r}: not a number")
    if amounts[0] > amounts[-1]:
        raise CardError(f"cost {value!r}: low exceeds high")
    return amounts[0], amounts[-1]


def _day(value, what: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text if len(text) > 7 else f"{text}-01").isoformat()
    except ValueError:
        raise CardError(f"{what} {value!r}: expected YYYY-MM or YYYY-MM-DD")


def _window(value) -> tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, None
    parts = list(value) if isinstance(value, (list, tuple)) else [value]
    if not 1 <= len(parts) <= 2:
        raise CardError(f"window {value!r}: expected one date or [earliest, latest]")
    earliest, latest = _day(parts[0], "window"), _day(parts[-1], "window") if len(parts) == 2 else None
    if earliest and latest and latest < earliest:
        raise CardError(f"window {value!r}: latest is before earliest")
    return earliest, latest


def _card(data: dict, source: str, parent: Optional[dict] = None) -> Card:
    if not isinstance(data, dict):
        raise CardError("plan card must be a mapping")
    slug = data.get("slug")
    if not slug or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(slug)):
        raise CardError(f"slug {slug!r}: expected lowercase-with-dashes")
    kind = data.get("kind") or (parent or {}).get("kind")
    if kind not in KINDS:
        raise CardError(f"{slug}: kind {kind!r} must be one of {', '.join(KINDS)}")
    status = data.get("status", (parent or {}).get("status", "idea"))
    if status not in STATUSES:
        raise CardError(f"{slug}: status {status!r} must be one of {', '.join(STATUSES)}")
    probability = data.get("p")
    if probability is not None and not 0 <= float(probability) <= 1:
        raise CardError(f"{slug}: p {probability} must be between 0 and 1")
    go_no_go = data.get("go_no_go")
    if go_no_go is not None and not (isinstance(go_no_go, list) and all(isinstance(g, str) for g in go_no_go)):
        raise CardError(f"{slug}: go_no_go must be a list of strings")
    points = data.get("points") or {}
    if not isinstance(points, dict):
        raise CardError(f"{slug}: points must be a mapping like {{program: wf, needed: 136000}}")
    cost_low, cost_high = _cost(data.get("cost"))
    earliest, latest = _window(data.get("window"))
    return Card(
        slug=slug,
        title=str(data.get("title") or slug),
        kind=kind,
        status=status,
        parent=parent["slug"] if parent else None,
        pick_one=bool(data.get("options")),
        necessity=bool(data.get("necessity", (parent or {}).get("necessity", False))),
        cost_low=cost_low,
        cost_high=cost_high,
        probability=float(probability) if probability is not None else None,
        earliest=earliest,
        latest=latest,
        paid=_amount(data.get("paid") or 0),
        revisit=_day(data.get("revisit"), f"{slug}: revisit"),
        go_no_go=json.dumps(go_no_go) if go_no_go else None,
        points_program=points.get("program"),
        points_needed=int(_amount(points["needed"])) if points.get("needed") is not None else None,
        source_path=source,
    )


def parse_cards(data: dict, source: str) -> list[Card]:
    """A card and its pick-one options, parent first."""
    parent = _card(data, source)
    options = data.get("options") or []
    if not isinstance(options, list):
        raise CardError(f"{parent.slug}: options must be a list")
    if options and (parent.cost_low is not None or parent.probability is not None):
        raise CardError(f"{parent.slug}: a pick-one plan carries cost and p on its options, not itself")
    children = [_card(option, source, parent=data) for option in options]
    total = sum(c.probability or 0 for c in children if c.status not in INACTIVE_STATUSES)
    if total > 1 + 1e-9:
        raise CardError(f"{parent.slug}: option probabilities sum to {total:g}, more than 1")
    return [parent, *children]


def find_cards(root: Path) -> tuple[list[Card], list[str]]:
    """Every plan card under root, plus per-file errors (one bad card doesn't block the rest)."""
    cards, errors, seen = [], [], {}
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = FRONTMATTER.match(text)
        if not match or not re.search(r"^plan:", match.group(1), re.MULTILINE):
            continue
        rel = str(path.relative_to(root))
        try:
            meta = yaml.safe_load(match.group(1)) or {}
            file_cards = parse_cards(meta["plan"], rel)
        except (yaml.YAMLError, CardError, KeyError, TypeError, ValueError) as e:
            errors.append(f"{rel}: {e}")
            continue
        for card in file_cards:
            if card.slug in seen:
                errors.append(f"{rel}: slug '{card.slug}' already defined in {seen[card.slug]}")
                break
            seen[card.slug] = rel
        else:
            cards.extend(file_cards)
    return cards, errors


def _row_values(row) -> dict:
    return {name: row[name] for name in SYNCED_FIELDS}


def _card_values(card: Card, parent_id) -> dict:
    values = {name: getattr(card, name) for name in SYNCED_FIELDS if name != "parent_id"}
    values["parent_id"] = parent_id
    values["pick_one"] = int(card.pick_one)
    values["necessity"] = int(card.necessity)
    return values


def diff(conn, cards: list[Card]) -> SyncResult:
    """What syncing would change. Read-only."""
    result = SyncResult()
    rows = {r["slug"]: r for r in conn.execute("SELECT * FROM plans").fetchall()}
    ids = {slug: r["id"] for slug, r in rows.items()}
    for card in cards:
        row = rows.get(card.slug)
        if row is None:
            result.changes.append(Change(card, "add", status=(None, card.status) if card.status != "idea" else None))
            continue
        parent_pending = bool(card.parent) and card.parent not in ids  # parent is new in this sync
        parent_id = ids.get(card.parent) if card.parent else None
        old = _row_values(row)
        new = _card_values(card, parent_id)
        changed = {k: (old[k], new[k]) for k in SYNCED_FIELDS if _differs(old[k], new[k])}
        if parent_pending:
            changed["parent_id"] = (row["parent_id"], card.parent)
        status = (row["status"], card.status) if row["status"] != card.status else None
        later = card.earliest and row["earliest"] and card.earliest > row["earliest"]
        deferred = card.status == "deferred" and bool(later or (status and status[1] == "deferred"))
        if changed or status:
            result.changes.append(Change(card, "update", changed, status, deferred))
        else:
            result.unchanged.append(card.slug)
    carded = {c.slug for c in cards}
    result.orphaned = [
        slug for slug, r in rows.items()
        if r["source_path"] and slug not in carded and r["status"] not in INACTIVE_STATUSES
    ]
    return result


def _differs(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) > 1e-9
    return (a if a != "" else None) != (b if b != "" else None)


def apply(conn, result: SyncResult) -> None:
    """Write a diff in one transaction, recording status changes and deferrals in plan_history."""
    with conn:
        for change in result.changes:
            card = change.card
            parent_id = None
            if card.parent:
                parent_id = conn.execute("SELECT id FROM plans WHERE slug = ?", (card.parent,)).fetchone()["id"]
            values = _card_values(card, parent_id)
            note = f"plan sync: {card.source_path}"
            if change.action == "add":
                columns = ["slug", "status", *values]
                cursor = conn.execute(
                    f"INSERT INTO plans ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                    (card.slug, card.status, *values.values()),
                )
                _record(conn, cursor.lastrowid, None, card.status, new_earliest=card.earliest, note=note)
                continue
            row = conn.execute("SELECT * FROM plans WHERE slug = ?", (card.slug,)).fetchone()
            conn.execute(
                f"UPDATE plans SET status = ?, {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                (card.status, *values.values(), row["id"]),
            )
            if change.deferred:
                _record(conn, row["id"], row["status"], "deferred",
                        old_earliest=row["earliest"], new_earliest=card.earliest, note=note)
            elif change.status:
                _record(conn, row["id"], row["status"], card.status, note=note)
