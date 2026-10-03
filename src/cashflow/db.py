import math
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".cashflow" / "cashflow.db"

def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    _migrate(conn)
    return conn

def _migrate(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "is_reimbursed" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN is_reimbursed BOOLEAN NOT NULL DEFAULT 0")
        conn.commit()
    if "reimbursed_amount" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN reimbursed_amount REAL NOT NULL DEFAULT 0")
        conn.execute("UPDATE transactions SET reimbursed_amount = amount WHERE is_reimbursed = 1")
        conn.commit()

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
    is_reimbursed BOOLEAN NOT NULL DEFAULT 0,
    reimbursed_amount REAL NOT NULL DEFAULT 0,
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
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    parent_id INTEGER REFERENCES plans(id),
    pick_one BOOLEAN NOT NULL DEFAULT 0,
    kind TEXT NOT NULL CHECK (kind IN ('trip', 'home', 'vehicle', 'purchase', 'gift', 'other')),
    status TEXT NOT NULL DEFAULT 'idea'
        CHECK (status IN ('idea', 'researching', 'planned', 'committed', 'deferred', 'done', 'dropped')),
    cost_low REAL,
    cost_high REAL,
    probability REAL CHECK (probability BETWEEN 0 AND 1),
    earliest DATE,
    latest DATE,
    necessity BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS plan_history (
    id INTEGER PRIMARY KEY,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    from_status TEXT,
    to_status TEXT NOT NULL,
    old_earliest DATE,
    new_earliest DATE,
    note TEXT
);
CREATE TABLE IF NOT EXISTS recurring_reviews (
    key TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('keep', 'cancel', 'ignore')),
    decided_on DATE NOT NULL,
    note TEXT
);
DROP VIEW IF EXISTS possible_dupes;
CREATE VIEW possible_dupes AS
SELECT a.id AS id_a, b.id AS id_b,
       a.date AS date_a, b.date AS date_b,
       a.amount AS amount,
       CAST(ABS(julianday(b.date) - julianday(a.date)) AS INTEGER) AS days_apart,
       a.merchant AS merchant_a, b.merchant AS merchant_b,
       acct_a.name AS account_a, acct_b.name AS account_b,
       a.source_id AS source_a, b.source_id AS source_b,
       a.who AS who_a, b.who AS who_b
FROM transactions a
JOIN transactions b ON a.id < b.id
JOIN accounts acct_a ON a.account_id = acct_a.id
JOIN accounts acct_b ON b.account_id = acct_b.id
WHERE a.canonical_id IS NULL AND b.canonical_id IS NULL
  AND a.amount > 0 AND b.amount > 0
  AND ABS(a.amount - b.amount) < 0.011
  AND ABS(julianday(a.date) - julianday(b.date)) <= 3
  AND SUBSTR(REPLACE(UPPER(a.merchant), ' ', ''), 1, 10)
    = SUBSTR(REPLACE(UPPER(b.merchant), ' ', ''), 1, 10)
  AND b.source_id NOT LIKE a.source_id || '-occurrence-%'
  AND a.source_id NOT LIKE b.source_id || '-occurrence-%';
"""

from cashflow.models import ParsedTransaction

def store_transactions(conn, txns: list[ParsedTransaction]) -> int:
    accounts = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM accounts")}
    unknown_accounts = {txn.account_name for txn in txns if txn.account_name not in accounts}
    if unknown_accounts:
        raise ValueError(f"Unknown accounts: {sorted(unknown_accounts)}. Check account names in seed.py.")
    inserted = 0
    with conn:
        for txn in txns:
            if not math.isfinite(txn.amount):
                raise ValueError("Transaction amount must be finite")
            existing = conn.execute(
                "SELECT date, amount, description, account_id FROM transactions WHERE source_id = ?",
                (txn.source_id,),
            ).fetchone()
            if existing and (existing["date"], existing["amount"], existing["description"], existing["account_id"]) != (
                txn.date.isoformat(), txn.amount, txn.description, accounts[txn.account_name]
            ):
                raise ValueError(f"Conflicting transaction source_id {txn.source_id}; reconcile the exports before importing")
            cursor = conn.execute(
                "INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) "
                "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?) ON CONFLICT(source_id) DO NOTHING",
                (txn.source_id, txn.date.isoformat(), txn.amount, txn.description, txn.merchant,
                 accounts[txn.account_name], txn.who, txn.source_type),
            )
            inserted += cursor.rowcount
    return inserted


def store_income(conn: sqlite3.Connection, records: list[dict]) -> int:
    inserted = 0
    with conn:
        for rec in records:
            if not math.isfinite(rec["amount"]):
                raise ValueError("Income amount must be finite")
            cursor = conn.execute(
                "INSERT INTO income (source_id, date, amount, source, description) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(source_id) DO NOTHING",
                (rec["source_id"], rec["date"].isoformat(), rec["amount"],
                 rec["source"], rec.get("description", "")),
            )
            inserted += cursor.rowcount
    return inserted
