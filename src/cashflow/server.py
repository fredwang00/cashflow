import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cashflow.db import DEFAULT_DB_PATH

STATIC_DIR = Path(__file__).parent / "static"


def _get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def create_app(db_path: str = str(DEFAULT_DB_PATH)) -> FastAPI:
    app = FastAPI(title="cashflow")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def api_status():
        conn = _get_db(db_path)
        today = date.today()
        y, m = today.year, today.month

        spending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
            "WHERE canonical_id IS NULL AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
            (str(y), f"{m:02d}"),
        ).fetchone()["total"]

        income = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM income WHERE strftime('%Y', date) = ?",
            (str(y),),
        ).fetchone()["total"]

        ytd_spending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
            "WHERE canonical_id IS NULL AND strftime('%Y', date) = ?",
            (str(y),),
        ).fetchone()["total"]

        review_count = conn.execute(
            "SELECT COUNT(*) as c FROM transactions WHERE canonical_id IS NULL AND status = 'pending'"
        ).fetchone()["c"]

        ceiling_row = conn.execute("SELECT amount FROM goals WHERE type = 'ceiling'").fetchone()
        ceiling = ceiling_row["amount"] if ceiling_row else 12000.0

        surplus_row = conn.execute("SELECT amount FROM goals WHERE type = 'surplus'").fetchone()
        surplus_goal = surplus_row["amount"] if surplus_row else 40000.0

        days_in_month = 31
        if m < 12:
            days_in_month = (date(y, m + 1, 1) - date(y, m, 1)).days
        days_left = days_in_month - today.day

        conn.close()
        return {
            "month_spending": round(spending, 2),
            "ceiling": ceiling,
            "pct": round(spending / ceiling * 100, 1) if ceiling > 0 else 0,
            "days_left": days_left,
            "days_in_month": days_in_month,
            "month_name": today.strftime("%B %Y"),
            "ytd_income": round(income, 2),
            "ytd_spending": round(ytd_spending, 2),
            "ytd_surplus": round(income - ytd_spending, 2),
            "surplus_goal": surplus_goal,
            "review_queue": review_count,
        }

    @app.get("/api/monthly/{year}/{month}")
    def api_monthly(year: int, month: int):
        conn = _get_db(db_path)
        txns = conn.execute(
            "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
            "t.is_one_off, t.one_off_label, c.name as category "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
            "ORDER BY t.date DESC",
            (str(year), f"{month:02d}"),
        ).fetchall()
        by_category = conn.execute(
            "SELECT c.name as category, ROUND(SUM(t.amount), 2) as total "
            "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
            "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
            "GROUP BY c.name ORDER BY total DESC",
            (str(year), f"{month:02d}"),
        ).fetchall()
        total = sum(t["amount"] for t in txns)
        conn.close()
        return {
            "year": year, "month": month, "total": round(total, 2),
            "transactions": [dict(t) for t in txns],
            "by_category": [dict(r) for r in by_category],
        }

    @app.get("/api/transactions")
    def api_transactions(year: int = 2026, month: int | None = None, limit: int = 100):
        conn = _get_db(db_path)
        if month:
            rows = conn.execute(
                "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
                "t.is_one_off, t.one_off_label, c.name as category "
                "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
                "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? AND strftime('%m', t.date) = ? "
                "ORDER BY t.date DESC LIMIT ?",
                (str(year), f"{month:02d}", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT t.id, t.date, t.amount, t.merchant, t.description, t.status, t.who, "
                "t.is_one_off, t.one_off_label, c.name as category "
                "FROM transactions t LEFT JOIN categories c ON t.category_id = c.id "
                "WHERE t.canonical_id IS NULL AND strftime('%Y', t.date) = ? "
                "ORDER BY t.date DESC LIMIT ?",
                (str(year), limit),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @app.get("/api/yearly/{year}")
    def api_yearly(year: int):
        conn = _get_db(db_path)
        months = []
        for mo in range(1, 13):
            sp = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM transactions "
                "WHERE canonical_id IS NULL AND strftime('%Y', date) = ? AND strftime('%m', date) = ?",
                (str(year), f"{mo:02d}"),
            ).fetchone()["total"]
            inc = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) as total FROM income "
                "WHERE strftime('%Y', date) = ? AND strftime('%m', date) = ?",
                (str(year), f"{mo:02d}"),
            ).fetchone()["total"]
            months.append({"month": mo, "spending": round(sp, 2), "income": round(inc, 2), "surplus": round(inc - sp, 2)})
        ytd_income = sum(m["income"] for m in months)
        ytd_spending = sum(m["spending"] for m in months)
        conn.close()
        return {"year": year, "months": months, "ytd_income": round(ytd_income, 2), "ytd_spending": round(ytd_spending, 2), "ytd_surplus": round(ytd_income - ytd_spending, 2)}

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app
