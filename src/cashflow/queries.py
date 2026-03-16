import sqlite3
from typing import Optional

def get_month_spending(conn: sqlite3.Connection, year: int, month: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM transactions "
        "WHERE canonical_id IS NULL AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
        (str(year), f"{month:02d}"),
    ).fetchone()
    return row["total"]

def get_ytd_spending(conn: sqlite3.Connection, year: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM transactions "
        "WHERE canonical_id IS NULL AND strftime('%Y', date) = ?",
        (str(year),),
    ).fetchone()
    return row["total"]

def get_ytd_income(conn: sqlite3.Connection, year: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0.0) as total FROM income WHERE strftime('%Y', date) = ?",
        (str(year),),
    ).fetchone()
    return row["total"]

def get_ytd_surplus(conn: sqlite3.Connection, year: int) -> float:
    return get_ytd_income(conn, year) - get_ytd_spending(conn, year)

def get_review_queue_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as c FROM transactions WHERE canonical_id IS NULL AND status = 'pending'"
    ).fetchone()
    return row["c"]

def get_goal(conn: sqlite3.Connection, goal_type: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM goals WHERE type = ?", (goal_type,)).fetchone()
