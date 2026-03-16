from cashflow.seed import seed_categories, seed_accounts, seed_goals, seed_all

def test_seed_categories_creates_necessities(db):
    seed_categories(db)
    rows = db.execute("SELECT name FROM categories WHERE type = 'necessity' ORDER BY name").fetchall()
    names = [r["name"] for r in rows]
    assert "Mortgage" in names
    assert "Auto Insurance" in names
    assert "Verizon" in names

def test_seed_categories_creates_wants(db):
    seed_categories(db)
    rows = db.execute("SELECT name FROM categories WHERE type = 'want' AND parent_id IS NULL ORDER BY name").fetchall()
    names = [r["name"] for r in rows]
    assert "Groceries" in names
    assert "Restaurants" in names
    assert "Kids Activities" in names

def test_seed_categories_creates_subscriptions_as_children(db):
    seed_categories(db)
    parent = db.execute("SELECT id FROM categories WHERE name = 'Subscriptions'").fetchone()
    assert parent is not None
    children = db.execute("SELECT name FROM categories WHERE parent_id = ?", (parent["id"],)).fetchall()
    names = [r["name"] for r in children]
    assert "CAROL Bike" in names
    assert "Amazon Prime" in names
    assert "Audible" in names

def test_seed_categories_creates_amazon_mixed(db):
    seed_categories(db)
    row = db.execute("SELECT * FROM categories WHERE name = 'Amazon - Mixed'").fetchone()
    assert row is not None
    assert row["type"] == "want"

def test_seed_accounts(db):
    seed_accounts(db)
    rows = db.execute("SELECT name FROM accounts ORDER BY name").fetchall()
    names = [r["name"] for r in rows]
    assert "Chase Prime Visa" in names
    assert "Chase Freedom" in names
    assert "Capital One" in names
    assert "Bank of America" in names
    assert "Target Card" in names
    assert "Checking" in names

def test_seed_goals(db):
    seed_goals(db)
    ceiling = db.execute("SELECT * FROM goals WHERE type = 'ceiling'").fetchone()
    assert ceiling["amount"] == 12000.0
    assert ceiling["period"] == "monthly"
    surplus = db.execute("SELECT * FROM goals WHERE type = 'surplus'").fetchone()
    assert surplus["amount"] == 40000.0
    assert surplus["period"] == "yearly"

def test_seed_all_is_idempotent(db):
    seed_all(db)
    count_1 = db.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    seed_all(db)
    count_2 = db.execute("SELECT COUNT(*) as c FROM categories").fetchone()["c"]
    assert count_1 == count_2
