import json
import re
import sqlite3
from datetime import date

from cashflow.audit import find_recurring
from cashflow.audit_cli import find_alarms
from cashflow.plans import monthly_free_cash
from cashflow.queries import get_goal, get_month_spending, get_review_queue_count

DEFAULT_CEILING = 12000.0


def daily_note_fields(conn: sqlite3.Connection, today: date) -> dict[str, object]:
    """Cashflow state for the daily note's frontmatter, one line per key."""
    ceiling = get_goal(conn, "ceiling")
    alarms = find_alarms(find_recurring(conn, today))
    return {
        "spend_mtd": round(get_month_spending(conn, today.year, today.month)),
        "spend_ceiling": round(ceiling["amount"] if ceiling else DEFAULT_CEILING),
        "free_cash": round(monthly_free_cash(conn, today).free),
        "review_queue": get_review_queue_count(conn),
        "cash_alarms": " | ".join(message for message, _ in alarms),
    }


def update_frontmatter(text: str, fields: dict[str, object]) -> str:
    """Set each key in the note's YAML frontmatter, replacing existing values in place."""
    opening = text.index("---")
    closing = text.index("\n---", opening + 3) + 1
    frontmatter = text[:closing]
    for key, value in fields.items():
        # A JSON string is a valid YAML double-quoted scalar, so text containing ": " stays parseable.
        rendered = json.dumps(value) if isinstance(value, str) else value
        line = f"{key}: {rendered}"
        pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
        if pattern.search(frontmatter):
            frontmatter = pattern.sub(lambda _: line, frontmatter)
        else:
            frontmatter += line + "\n"
    return frontmatter + text[closing:]
