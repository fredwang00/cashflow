import sqlite3

NECESSITIES = [
    "Mortgage", "Mom&Dad Payment", "Auto Insurance", "Gas & Fuel",
    "Service & Parts", "Nat Gas + Electricity", "CVB Public Utility",
    "Hampton Roads Sanitation", "Verizon", "AT&T", "Term Life Insurance",
    "Water Delivery", "YouTube TV", "YouTube Premium", "Credit Card Fees",
]
WANTS = [
    "Groceries", "Fast Food", "Restaurants", "Kids Activities", "Outschool",
    "Clothing", "Landscaping", "Home Improvement", "Soda Stream", "Coffee",
    "Shopping", "Gifts", "Birthdays & Holidays", "Christmas", "Amazon - Mixed",
]
SUBSCRIPTIONS = [
    "CAROL Bike", "Patreon", "Crunchyroll", "Google One", "iCloud+",
    "Amazon Prime", "Audible", "Ashby Payment", "AppleCard Payment",
]
ACCOUNTS = [
    ("Chase Prime Visa", "credit", "Chase"),
    ("Chase Freedom", "credit", "Chase"),
    ("Capital One", "credit", "Capital One"),
    ("Capital One Venture", "credit", "Capital One"),
    ("Capital One Wendy", "credit", "Capital One"),
    ("Bank of America", "credit", "BofA"),
    ("Target Card", "credit", "Target"),
    ("Citi Costco", "credit", "Citi"),
    ("Apple Card", "credit", "Apple"),
    ("Checking", "debit", "Chase"),
    ("PayPal", "cash", "PayPal"),
]
GOALS = [
    ("Monthly Ceiling", "ceiling", 12000.0, "monthly", None),
    ("Annual Surplus", "surplus", 40000.0, "yearly", None),
]

def seed_categories(conn: sqlite3.Connection) -> None:
    for name in NECESSITIES:
        conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'necessity')", (name,))
    for name in WANTS:
        conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, 'want')", (name,))
    conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES ('Subscriptions', 'want')")
    parent_id = conn.execute("SELECT id FROM categories WHERE name = 'Subscriptions'").fetchone()[0]
    for name in SUBSCRIPTIONS:
        conn.execute("INSERT OR IGNORE INTO categories (name, parent_id, type) VALUES (?, ?, 'want')", (name, parent_id))
    conn.commit()

def seed_accounts(conn: sqlite3.Connection) -> None:
    for name, acct_type, institution in ACCOUNTS:
        conn.execute("INSERT OR IGNORE INTO accounts (name, type, institution, is_active) VALUES (?, ?, ?, 1)", (name, acct_type, institution))
    conn.commit()

def seed_goals(conn: sqlite3.Connection) -> None:
    for name, goal_type, amount, period, target_date in GOALS:
        conn.execute("INSERT OR IGNORE INTO goals (name, type, amount, period, target_date) VALUES (?, ?, ?, ?, ?)", (name, goal_type, amount, period, target_date))
    conn.commit()

def seed_all(conn: sqlite3.Connection) -> None:
    seed_categories(conn)
    seed_accounts(conn)
    seed_goals(conn)
