import sqlite3
import pytest

@pytest.fixture
def db():
    """In-memory SQLite database with schema applied."""
    from cashflow.db import create_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    yield conn
    conn.close()
