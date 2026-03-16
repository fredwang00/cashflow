import sqlite3
import pytest
from cashflow.db import create_schema

def test_create_schema_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    expected = ["accounts", "amazon_items", "budgets", "categories", "goals", "income", "ingest_state", "merchant_rules", "transactions"]
    assert tables == expected
    conn.close()

def test_transactions_source_id_is_unique():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute("INSERT INTO accounts (name, type, institution, is_active) VALUES ('Test', 'credit', 'Test', 1)")
    conn.execute("INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES ('abc', '2026-01-01', 100.0, 'test', 'test', 1, 'confirmed', 100, 'fred', 'csv')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES ('abc', '2026-01-02', 200.0, 'test2', 'test2', 1, 'confirmed', 100, 'fred', 'csv')")
    conn.close()

def test_budgets_unique_constraint():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute("INSERT INTO categories (name, type) VALUES ('Groceries', 'want')")
    conn.execute("INSERT INTO budgets (category_id, year, month, amount) VALUES (1, 2026, 3, 1200.0)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO budgets (category_id, year, month, amount) VALUES (1, 2026, 3, 1500.0)")
    conn.close()

def test_canonical_id_self_reference():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    conn.execute("INSERT INTO accounts (name, type, institution, is_active) VALUES ('Test', 'credit', 'Test', 1)")
    conn.execute("INSERT INTO transactions (source_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES ('email-1', '2026-01-01', 50.0, 'test', 'Amazon', 1, 'confirmed', 100, 'fred', 'email')")
    conn.execute("INSERT INTO transactions (source_id, canonical_id, date, amount, description, merchant, account_id, status, confidence, who, source_type) VALUES ('csv-1', 1, '2026-01-01', 50.0, 'AMAZON MKTPL', 'Amazon', 1, 'confirmed', 100, 'fred', 'csv')")
    rows = conn.execute("SELECT * FROM transactions WHERE canonical_id IS NULL").fetchall()
    assert len(rows) == 1
    conn.close()
