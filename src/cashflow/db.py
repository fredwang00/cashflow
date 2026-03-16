import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".cashflow" / "cashflow.db"

def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    return conn

def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES categories(id),
    type TEXT NOT NULL CHECK (type IN ('necessity', 'want'))
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('credit', 'debit', 'cash')),
    institution TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    source_id TEXT UNIQUE NOT NULL,
    canonical_id INTEGER REFERENCES transactions(id),
    date DATE NOT NULL,
    amount REAL NOT NULL,
    description TEXT NOT NULL,
    merchant TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    is_one_off BOOLEAN NOT NULL DEFAULT 0,
    one_off_label TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed')),
    confidence INTEGER NOT NULL DEFAULT 0,
    who TEXT NOT NULL DEFAULT 'shared' CHECK (who IN ('fred', 'wife', 'shared')),
    source_type TEXT NOT NULL CHECK (source_type IN ('email', 'csv', 'amazon_report', 'manual')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS amazon_items (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER REFERENCES transactions(id),
    order_number TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price REAL NOT NULL,
    order_date DATE NOT NULL,
    account TEXT NOT NULL CHECK (account IN ('fred', 'wife')),
    category_id INTEGER REFERENCES categories(id),
    is_subscribe_save BOOLEAN NOT NULL DEFAULT 0,
    delivery_frequency TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    amount REAL NOT NULL,
    UNIQUE (category_id, year, month)
);
CREATE TABLE IF NOT EXISTS merchant_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT UNIQUE NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'learned')),
    confidence INTEGER NOT NULL DEFAULT 100,
    match_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY,
    source_id TEXT UNIQUE NOT NULL,
    date DATE NOT NULL,
    amount REAL NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    pay_period TEXT
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('ceiling', 'surplus', 'sinking', 'invest')),
    amount REAL NOT NULL,
    period TEXT CHECK (period IN ('monthly', 'yearly')),
    target_date DATE
);
CREATE TABLE IF NOT EXISTS ingest_state (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    last_sync DATETIME,
    cursor TEXT,
    metadata TEXT
);
"""

from cashflow.models import ParsedTransaction

def store_transactions(conn, txns: list[ParsedTransaction]) -> int:
    accounts = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM accounts").fetchall()}
    inserted = 0
    for txn in txns:
        account_id = accounts.get(txn.account_name)
        if account_id is None:
            continue
        try:
            conn.execute(
                "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 'shared', ?)",
                (txn.source_id, txn.date.isoformat(), txn.amount, txn.description, txn.merchant, account_id, txn.source_type),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted

def store_income(conn: sqlite3.Connection, records: list[dict]) -> int:
    inserted = 0
    for rec in records:
        try:
            conn.execute(
                "INSERT INTO income (source_id, date, amount, source, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec["source_id"], rec["date"].isoformat(), rec["amount"],
                 rec["source"], rec.get("description", "")),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return inserted
