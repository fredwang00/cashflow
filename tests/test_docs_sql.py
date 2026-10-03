"""Every SQL recipe in docs/adhoc-queries.md must parse against the real schema.

Guards the docs against drift: a renamed column or table (e.g. writing
`account` instead of `account_id`) fails here, not in a user's terminal.
"""
import re
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs" / "adhoc-queries.md"


def _sql_statements(text):
    blocks = re.findall(r"```sql\n(.*?)```", text, flags=re.DOTALL)
    statements = []
    for block in blocks:
        for part in block.split(";"):
            lines = [ln for ln in part.splitlines() if not ln.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if stmt:
                statements.append(stmt)
    return statements


def test_docs_have_a_rich_set_of_recipes():
    statements = _sql_statements(DOCS.read_text())
    assert len(statements) >= 12, f"expected >= 12 SQL recipes, found {len(statements)}"


def test_docs_sql_is_read_only(db):
    for stmt in _sql_statements(DOCS.read_text()):
        first_word = stmt.lstrip().split(None, 1)[0].upper()
        assert first_word in ("SELECT", "WITH"), (
            f"docs SQL blocks must be read-only SELECT/WITH statements, got: {stmt[:80]}"
        )


def test_docs_sql_parses_against_schema(db):
    statements = _sql_statements(DOCS.read_text())
    assert statements, "no SQL recipes found in docs/adhoc-queries.md"
    for stmt in statements:
        # EXPLAIN prepares the statement without executing it; raises
        # OperationalError on unknown columns/tables/syntax.
        db.execute("EXPLAIN " + stmt)
