import re
import click
from datetime import date
from pathlib import Path
from cashflow.db import get_connection, store_transactions, store_income
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv
from cashflow.parsers.amazon import parse_amazon_orders
from cashflow.parsers.target import parse_target_csv
from cashflow.parsers.bofa_cc import parse_bofa_cc_csv
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
from cashflow.parsers.capital_one import parse_capital_one
from cashflow.parsers.citi import parse_citi
from cashflow.parsers.apple_card import parse_apple_card_csv
from cashflow.reconcile import store_amazon_orders, reconcile_amazon
from cashflow.queries import get_month_spending, get_ytd_surplus, get_review_queue_count, get_goal
from cashflow.categorize import categorize_by_rules, categorize_by_llm, confirm_transaction, get_pending_for_review

@click.group()
@click.option("--db", type=click.Path(), default=None, help="Path to SQLite database (default: ~/.cashflow/cashflow.db).")
@click.pass_context
def cli(ctx, db):
    """Household financial dashboard."""
    ctx.ensure_object(dict)
    db_path = Path(db) if db else None
    conn = get_connection(db_path) if db_path else get_connection()
    seed_all(conn)
    ctx.obj["conn"] = conn

@cli.command()
@click.option("--files", type=click.Path(exists=True), help="Path to CSV inbox directory or file.")
@click.option("--email", is_flag=True, help="Poll Gmail for new emails. (Not yet implemented.)")
@click.option("--auto", is_flag=True, help="Run both email and file ingestion.")
@click.pass_context
def ingest(ctx, files, email, auto):
    """Ingest transactions from CSV files or email."""
    conn = ctx.obj["conn"]
    if email or auto:
        click.echo("Email ingestion not yet implemented.")
    if not files and not auto:
        click.echo("No source specified. Use --files PATH or --email.")
        return
    path = Path(files) if files else None
    if path is None:
        return
    total = 0
    if path.is_file():
        csv_files = [path]
    else:
        csv_files = sorted(path.glob("*.csv")) + sorted(path.glob("*.CSV")) + sorted(path.glob("*.txt"))
    for csv_file in csv_files:
        click.echo(f"Parsing {csv_file.name}...")
        if "chase" in csv_file.name.lower():
            txns = parse_chase_csv(csv_file)
        elif "amazon" in csv_file.name.lower():
            orders = parse_amazon_orders(csv_file)
            items_stored = store_amazon_orders(conn, orders)
            click.echo(f"  {items_stored} new Amazon items from {len(orders)} orders")
            total += items_stored
            continue
        elif "stmt" in csv_file.name.lower():
            check_expenses, check_income = parse_bofa_checking_csv(csv_file)
            if check_expenses:
                stored = store_transactions(conn, check_expenses)
                click.echo(f"  {stored} new checking expenses")
                total += stored
            if check_income:
                inc_stored = store_income(conn, check_income)
                click.echo(f"  {inc_stored} new income records")
                total += inc_stored
            continue
        elif re.search(r"_\d{4}\.csv$", csv_file.name, re.IGNORECASE):
            txns = parse_bofa_cc_csv(csv_file)
        elif "capital" in csv_file.name.lower():
            txns = parse_capital_one(csv_file)
        elif "citi" in csv_file.name.lower():
            txns = parse_citi(csv_file)
        elif "apple" in csv_file.name.lower():
            txns = parse_apple_card_csv(csv_file)
        elif "transaction" in csv_file.name.lower():
            txns = parse_target_csv(csv_file)
        else:
            click.echo(f"  Skipped — no parser for {csv_file.name}")
            continue
        stored = store_transactions(conn, txns)
        click.echo(f"  {stored} new transactions ({len(txns) - stored} duplicates skipped)")
        total += stored
    click.echo(f"\nDone. {total} transactions ingested.")
    if total > 0:
        click.echo("Categorizing...")
        rules_matched, rules_unmatched = categorize_by_rules(conn)
        click.echo(f"  Rules: {rules_matched} matched, {rules_unmatched} unmatched")

        if rules_unmatched > 0:
            try:
                llm_confirmed, llm_pending = categorize_by_llm(conn)
                click.echo(f"  LLM: {llm_confirmed} auto-confirmed, {llm_pending} need review")
            except Exception as e:
                click.echo(f"  LLM categorization skipped: {e}")

    # Reconcile Amazon items with transactions
    matched = reconcile_amazon(conn)
    if matched > 0:
        click.echo(f"  Reconciled: {matched} Amazon items linked to transactions")

@cli.command()
@click.pass_context
def status(ctx):
    """Show current month burn rate and YTD surplus."""
    conn = ctx.obj["conn"]
    today = date.today()
    year, month = today.year, today.month
    spending = get_month_spending(conn, year, month)
    ceiling = get_goal(conn, "ceiling")
    ceiling_amt = ceiling["amount"] if ceiling else 12000.0
    days_in_month = (date(year, month % 12 + 1, 1) - date(year, month, 1)).days if month < 12 else 31
    days_left = days_in_month - today.day
    pct = (spending / ceiling_amt * 100) if ceiling_amt > 0 else 0
    if pct < 80:
        color = "green"
    elif pct < 95:
        color = "yellow"
    else:
        color = "red"
    month_name = today.strftime("%B %Y")
    click.secho(f"{month_name}: ${spending:,.0f} / ${ceiling_amt:,.0f} ceiling ({pct:.0f}%) — {days_left} days left", fg=color)
    surplus = get_ytd_surplus(conn, year)
    surplus_goal = get_goal(conn, "surplus")
    surplus_amt = surplus_goal["amount"] if surplus_goal else 40000.0
    months_elapsed = month
    pace = (surplus / months_elapsed * 12) if months_elapsed > 0 else 0
    surplus_pct = (surplus / surplus_amt * 100) if surplus_amt > 0 else 0
    click.secho(
        f"YTD surplus: ${surplus:,.0f} / ${surplus_amt:,.0f} goal ({surplus_pct:.0f}%) — on pace for ${pace:,.0f}",
        fg="green" if surplus_pct >= (months_elapsed / 12 * 100) else "yellow",
    )
    queue = get_review_queue_count(conn)
    if queue > 0:
        click.secho(f"Review queue: {queue} items", fg="yellow")
    else:
        click.secho("Review queue: empty", fg="green")

@cli.command()
@click.pass_context
def review(ctx):
    """Interactively review and categorize pending transactions."""
    conn = ctx.obj["conn"]

    pending = get_pending_for_review(conn)
    if not pending:
        click.secho("Review queue is empty.", fg="green")
        return

    categories = conn.execute(
        "SELECT id, name, type FROM categories ORDER BY type, name"
    ).fetchall()
    cat_list = [(c["id"], c["name"], c["type"]) for c in categories]

    click.echo(f"\n{len(pending)} transactions to review:\n")

    reviewed = 0
    for txn in pending:
        click.secho(f"  {txn['date']}  ${txn['amount']:>9,.2f}  {txn['merchant']}", fg="white", bold=True)
        click.echo(f"  {txn['description']}")
        if txn["suggested_category"]:
            click.secho(f"  Suggested: {txn['suggested_category']} ({txn['confidence']}% confidence)", fg="cyan")

        click.echo()
        for i, (cat_id, cat_name, cat_type) in enumerate(cat_list, 1):
            marker = "N" if cat_type == "necessity" else "W"
            click.echo(f"    {i:>3}. [{marker}] {cat_name}")

        click.echo()
        choice = click.prompt(
            "  Enter number to categorize, [a]ccept suggestion, [s]kip, [q]uit",
            default="s",
        )

        if choice.lower() == "q":
            break
        elif choice.lower() == "s":
            continue
        elif choice.lower() == "a" and txn["suggested_category"]:
            confirm_transaction(conn, txn["id"], txn["category_id"])
            click.secho(f"  Confirmed: {txn['suggested_category']}", fg="green")
            reviewed += 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(cat_list):
                cat_id, cat_name, _ = cat_list[idx]
                confirm_transaction(conn, txn["id"], cat_id)
                click.secho(f"  Categorized: {cat_name}", fg="green")
                reviewed += 1
            else:
                click.secho("  Invalid number, skipping.", fg="yellow")
        else:
            click.secho("  Skipped.", fg="yellow")

        click.echo()

    click.echo(f"\nReviewed {reviewed} transactions.")

@cli.command()
@click.argument("txn_id", type=int)
@click.option("--one-off", type=str, help="Label this transaction as a one-off expense.")
@click.pass_context
def tag(ctx, txn_id, one_off):
    """Tag a transaction (e.g., as a one-off expense)."""
    conn = ctx.obj["conn"]

    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        click.secho(f"Transaction {txn_id} not found.", fg="red")
        return

    if one_off:
        conn.execute(
            "UPDATE transactions SET is_one_off = 1, one_off_label = ? WHERE id = ?",
            (one_off, txn_id),
        )
        conn.commit()
        click.secho(
            f"Tagged #{txn_id} as one-off: \"{one_off}\" "
            f"(${txn['amount']:,.2f} on {txn['date']})",
            fg="green",
        )

@cli.group()
@click.pass_context
def rule(ctx):
    """Manage merchant categorization rules."""
    pass


@rule.command("list")
@click.pass_context
def rule_list(ctx):
    """List all merchant rules."""
    conn = ctx.obj["conn"]
    rows = conn.execute(
        "SELECT mr.pattern, c.name as category, mr.source, mr.match_count, mr.confidence "
        "FROM merchant_rules mr JOIN categories c ON mr.category_id = c.id "
        "ORDER BY mr.match_count DESC"
    ).fetchall()
    if not rows:
        click.echo("No merchant rules defined.")
        return
    click.echo(f"\n{'Pattern':<35} {'Category':<25} {'Source':<8} {'Matches':>7}")
    click.echo("-" * 80)
    for r in rows:
        click.echo(f"{r['pattern']:<35} {r['category']:<25} {r['source']:<8} {r['match_count']:>7}")
    click.echo(f"\n{len(rows)} rules total.")


@rule.command("set")
@click.argument("pattern")
@click.argument("category_name")
@click.pass_context
def rule_set(ctx, pattern, category_name):
    """Create or update a merchant rule. Recategorizes matching transactions."""
    conn = ctx.obj["conn"]

    cat = conn.execute("SELECT id, name FROM categories WHERE name = ?", (category_name,)).fetchone()
    if not cat:
        # Try case-insensitive match
        cat = conn.execute("SELECT id, name FROM categories WHERE LOWER(name) = LOWER(?)", (category_name,)).fetchone()
    if not cat:
        click.secho(f"Category '{category_name}' not found. Available:", fg="red")
        for r in conn.execute("SELECT name FROM categories ORDER BY type, name").fetchall():
            click.echo(f"  {r['name']}")
        return

    # Upsert rule
    existing = conn.execute("SELECT id FROM merchant_rules WHERE pattern = ?", (pattern,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE merchant_rules SET category_id = ?, source = 'manual' WHERE id = ?",
            (cat["id"], existing["id"]),
        )
        click.echo(f"Updated rule: '{pattern}' -> {cat['name']}")
    else:
        conn.execute(
            "INSERT INTO merchant_rules (pattern, category_id, source, confidence) VALUES (?, ?, 'manual', 100)",
            (pattern, cat["id"]),
        )
        click.echo(f"Created rule: '{pattern}' -> {cat['name']}")

    # Apply to matching transactions
    updated = conn.execute(
        "UPDATE transactions SET category_id = ?, status = 'confirmed', confidence = 100 "
        "WHERE canonical_id IS NULL AND LOWER(merchant) LIKE '%' || LOWER(?) || '%'",
        (cat["id"], pattern),
    ).rowcount
    conn.commit()

    if updated > 0:
        click.secho(f"  Recategorized {updated} transactions.", fg="green")


@rule.command("apply")
@click.pass_context
def rule_apply(ctx):
    """Re-run all merchant rules on pending uncategorized transactions."""
    conn = ctx.obj["conn"]
    matched, unmatched = categorize_by_rules(conn)
    click.echo(f"Rules matched: {matched}, unmatched: {unmatched}")


@rule.command("add-category")
@click.argument("name")
@click.argument("type", type=click.Choice(["necessity", "want"]))
@click.pass_context
def rule_add_category(ctx, name, type):
    """Add a new spending category."""
    conn = ctx.obj["conn"]
    try:
        conn.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, type))
        conn.commit()
        click.secho(f"Added category: {name} ({type})", fg="green")
    except Exception:
        click.secho(f"Category '{name}' already exists.", fg="yellow")


@cli.command()
@click.option("--port", default=8080, help="Port to serve on.")
@click.pass_context
def dashboard(ctx, port):
    """Open the financial dashboard in a browser."""
    import threading
    import webbrowser
    import uvicorn
    from cashflow.server import create_app

    db_path = str(ctx.obj["conn"].execute("PRAGMA database_list").fetchone()[2])
    ctx.obj["conn"].close()

    app = create_app(db_path)
    threading.Timer(1.0, webbrowser.open, args=[f"http://localhost:{port}"]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
