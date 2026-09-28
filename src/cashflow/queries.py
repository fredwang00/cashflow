import sqlite3
from typing import Optional

SAVINGS_CATEGORIES = ("Crypto/Investments", "Investments", "College Savings")


def not_savings(alias: str = "") -> str:
    """SQL condition that keeps money moved into savings or investments out of spending.

    Uncategorized transactions must still count, and `NULL NOT IN (...)` is NULL,
    so they are matched explicitly.
    """
    column = f"{alias}.category_id" if alias else "category_id"
    names = ", ".join(f"'{name}'" for name in SAVINGS_CATEGORIES)
    return f"({column} IS NULL OR {column} NOT IN (SELECT id FROM categories WHERE name IN ({names})))"


def get_month_spending(conn: sqlite3.Connection, year: int, month: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - reimbursed_amount), 0.0) as total FROM transactions "
        f"WHERE canonical_id IS NULL AND {not_savings()} AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
        (str(year), f"{month:02d}"),
    ).fetchone()
    return row["total"]

def get_ytd_spending(conn: sqlite3.Connection, year: int) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(amount - reimbursed_amount), 0.0) as total FROM transactions "
        f"WHERE canonical_id IS NULL AND {not_savings()} AND strftime('%Y', date) = ?",
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


FSA_ELIGIBLE_CATEGORIES = ("Medical", "Dental")

FSA_ELIGIBLE_MERCHANTS = (
    "whoop",
    "1800contacts",
    "contacts",
    "lenscrafters",
    "capsule",
    "rightway",
    "restorex",
    "leluv",
)


def get_fsa_candidates(conn: sqlite3.Connection, year: int) -> list[sqlite3.Row]:
    cat_placeholders = ",".join("?" * len(FSA_ELIGIBLE_CATEGORIES))
    merchant_clauses = " OR ".join(
        "LOWER(t.merchant) LIKE ?" for _ in FSA_ELIGIBLE_MERCHANTS
    )
    sql = f"""
        SELECT t.id, t.date, t.amount, t.merchant, t.description,
               a.name as account, c.name as category,
               t.is_reimbursed, t.reimbursed_amount
        FROM transactions t
        JOIN accounts a ON t.account_id = a.id
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.date >= ? AND t.date <= ?
          AND t.canonical_id IS NULL
          AND (
            c.name IN ({cat_placeholders})
            OR {merchant_clauses}
          )
        ORDER BY t.date
    """
    params: list = [
        f"{year}-01-01",
        f"{year}-12-31",
        *FSA_ELIGIBLE_CATEGORIES,
        *(f"%{m}%" for m in FSA_ELIGIBLE_MERCHANTS),
    ]
    return conn.execute(sql, params).fetchall()
