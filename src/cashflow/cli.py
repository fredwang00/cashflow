import click
from datetime import date
from pathlib import Path
from cashflow.db import get_connection, store_transactions
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv
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
    csv_files = [path] if path.is_file() else sorted(path.glob("*.csv"))
    for csv_file in csv_files:
        click.echo(f"Parsing {csv_file.name}...")
        if "chase" in csv_file.name.lower():
            txns = parse_chase_csv(csv_file)
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
