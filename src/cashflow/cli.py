import csv
import json
import math
from calendar import monthrange
import sqlite3
import click
from datetime import date
from pathlib import Path
from cashflow.db import get_connection, store_transactions, store_income
from cashflow.errors import ParseError
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv
from cashflow.parsers.amazon import parse_amazon_orders
from cashflow.parsers.target import parse_target_csv
from cashflow.parsers.bofa_cc import parse_bofa_cc_csv
from cashflow.parsers.bofa_checking import parse_bofa_checking_csv
from cashflow.parsers.capital_one_csv import parse_capital_one_csv
from cashflow.parsers.citi import parse_citi
from cashflow.parsers.apple_card import parse_apple_card_csv
from cashflow.parsers.paypal import parse_paypal_csv
from cashflow.parsers.amex import parse_amex_csv
from cashflow.parsers.robinhood import parse_robinhood_csv
from cashflow.parsers.wells_fargo import parse_wells_fargo_csv
from cashflow.parsers.expense_report import parse_expense_report
from cashflow.reimburse import link_recorded_reimbursements, match_expense_report
from cashflow.reconcile import store_amazon_orders, reconcile_amazon
from cashflow.dedup_paypal import link_paypal_to_cards
from cashflow.queries import get_month_spending, get_ytd_surplus, get_review_queue_count, get_goal, get_fsa_candidates
from cashflow.categorize import categorize_by_rules, categorize_by_llm, confirm_transaction, get_pending_for_review
from cashflow.plan_cli import plan
from cashflow.audit_cli import audit
from cashflow.daily_note import daily_note_fields, update_frontmatter

PARSERS = {
    "chase": parse_chase_csv, "bofa_cc": parse_bofa_cc_csv,
    "capital": parse_capital_one_csv, "citi": parse_citi,
    "apple": parse_apple_card_csv, "amex": parse_amex_csv,
    "robinhood": parse_robinhood_csv, "wells": parse_wells_fargo_csv,
    "paypal": parse_paypal_csv, "target": parse_target_csv,
}
CSV_HEADERS = {
    "chase": {"Transaction Date", "Description", "Type", "Amount"},
    "bofa_cc": {"Posted Date", "Reference Number", "Payee", "Amount"},
    "checking": {"Date", "Description", "Amount", "Running Bal."},
    "capital": {"Transaction Date", "Card No.", "Debit", "Credit"},
    "apple": {"Transaction Date", "Purchased By", "Amount (USD)"},
    "amex": {"Date", "Card Member", "Reference", "Amount"},
    "robinhood": {"Date", "Time", "Cardholder", "Amount", "Status", "Type"},
    "wells": {"DATE", "DESCRIPTION", "AMOUNT"},
    "paypal": {"Date", "Gross", "Balance Impact", "Transaction ID"},
    "target": {"Transaction Date", "Ref#", "Transaction Type", "Amount"},
}


def _detect_source(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        if "amazon" in path.name.lower():
            return "amazon"
        if "citi" in path.name.lower():
            return "citi"
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.reader(stream)
        for index, row in enumerate(reader):
            headers = {value.strip().strip('"') for value in row}
            for source, required in CSV_HEADERS.items():
                if required <= headers and (index == 0 or source == "checking"):
                    return source
            # Checking exports have a short balance-summary preamble.
            if index >= 20:
                break
    raise ParseError(path.name, None, "unrecognized export format; use a supported bank CSV or named amazon/citi .txt scrape")


def _record_import(conn, path: Path) -> None:
    conn.execute(
        "INSERT INTO ingest_state (source, last_sync) VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        (str(path.resolve()),),
    )
    conn.commit()


def _format_error(e):
    """Format an exception into user-friendly error lines.

    Returns (lines, exit_code) where lines are (message, color) tuples.
    """
    if isinstance(e, ParseError):
        lines = [(f"Bad data in {e.file}", "red")]
        if e.row is not None:
            lines.append((f"  Row {e.row}: {e.message}", "red"))
        else:
            lines.append((f"  {e.message}", "red"))
        return lines, 1
    if isinstance(e, FileNotFoundError):
        return [(f"File not found: {e.filename}", "red")], 1
    if isinstance(e, PermissionError):
        return [(f"Permission denied: {e.filename}", "red")], 1
    if isinstance(e, sqlite3.DatabaseError):
        return [
            (f"Database error: {e}", "red"),
            ("  Is the database file corrupt? Try: cashflow --db /path/to/new.db status", "yellow"),
        ], 1
    return [(f"Error: {e}", "red")], 1


class CashflowGroup(click.Group):
    """Click group that catches exceptions and shows clean errors."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except click.exceptions.Exit:
            raise
        except click.exceptions.Abort:
            raise
        except click.ClickException:
            raise
        except Exception as e:
            debug = ctx.params.get("debug", False)
            if debug:
                raise
            lines, code = _format_error(e)
            for msg, color in lines:
                click.secho(msg, fg=color)
            if not isinstance(e, (ParseError, FileNotFoundError, PermissionError, sqlite3.DatabaseError)):
                click.secho("Run with --debug for full traceback.", fg="yellow")
            ctx.exit(code)


@click.group(cls=CashflowGroup)
@click.option("--db", type=click.Path(), default=None, help="Path to SQLite database (default: ~/.cashflow/cashflow.db).")
@click.option("--debug", is_flag=True, help="Show full tracebacks on error.")
@click.pass_context
def cli(ctx, db, debug):
    """Household financial dashboard."""
    ctx.ensure_object(dict)
    db_path = Path(db) if db else None
    conn = get_connection(db_path) if db_path else get_connection()
    seed_all(conn)
    ctx.obj["conn"] = conn
    ctx.call_on_close(conn.close)


def main():
    """Entry point for the cashflow CLI."""
    cli()

@cli.command()
@click.option("--files", type=click.Path(exists=True), multiple=True, help="Path to CSV file or inbox directory. Can be repeated.")
@click.option("--email", is_flag=True, help="Poll Gmail for new emails. (Not yet implemented.)")
@click.option("--auto", is_flag=True, help="Import ~/cashflow/inbox/ when --files is omitted; email is not supported.")
@click.option("--expense-report", type=click.Path(exists=True), help="Path to expense report .xlsx file or directory.")
@click.pass_context
def ingest(ctx, files, email, auto, expense_report):
    """Ingest transactions from CSV files or email."""
    conn = ctx.obj["conn"]
    if expense_report:
        er_path = Path(expense_report)
        if er_path.is_file():
            xlsx_files = [er_path]
        else:
            xlsx_files = sorted(er_path.glob("*.xlsx"))
        for xlsx in xlsx_files:
            click.echo(f"Matching expense report: {xlsx.name}...")
            rows = parse_expense_report(xlsx)
            matched, already, unmatched = match_expense_report(conn, rows)
            parts = []
            if matched:
                parts.append(f"{matched} matched")
            if already:
                parts.append(f"{already} already reimbursed")
            if unmatched:
                parts.append(f"{unmatched} unmatched")
            if not parts:
                parts.append("no rows")
            click.secho(f"  {', '.join(parts)}", fg="green" if unmatched == 0 else "yellow")
            if unmatched > 0:
                from datetime import timedelta
                for row in rows:
                    start = (row.date - timedelta(days=7)).isoformat()
                    end = (row.date + timedelta(days=7)).isoformat()
                    txn = conn.execute(
                        "SELECT id FROM transactions WHERE date BETWEEN ? AND ? AND ABS(amount - ?) < 0.005 AND canonical_id IS NULL",
                        (start, end, row.amount),
                    ).fetchone()
                    if not txn:
                        click.secho(f"    No match: {row.date} ${row.amount:,.2f} {row.vendor}", fg="yellow")
        return
    if email:
        raise click.ClickException("Email ingestion is not implemented. Use --files or --auto for local exports.")
    if auto and not files:
        inbox = Path.home() / "cashflow" / "inbox"
        if not inbox.is_dir():
            raise click.ClickException(f"Inbox directory does not exist: {inbox}")
        files = (str(inbox),)
    if not files and not auto:
        click.echo("No source specified. Use --files PATH or --auto.")
        return
    total = 0
    csv_files = []
    for f in files:
        path = Path(f)
        if path.is_file():
            csv_files.append(path)
        else:
            csv_files += sorted(path.glob("*.csv")) + sorted(path.glob("*.CSV")) + sorted(path.glob("*.txt"))
    for csv_file in csv_files:
        click.echo(f"Parsing {csv_file.name}...")
        source = _detect_source(csv_file)
        if source == "amazon":
            orders = parse_amazon_orders(csv_file)
            items_stored = store_amazon_orders(conn, orders)
            _record_import(conn, csv_file)
            click.echo(f"  {items_stored} new Amazon items from {len(orders)} orders")
            total += items_stored
            continue
        if source == "checking":
            check_expenses, check_income = parse_bofa_checking_csv(csv_file)
            stored = store_transactions(conn, check_expenses)
            inc_stored = store_income(conn, check_income)
            _record_import(conn, csv_file)
            click.echo(f"  {stored} new checking transactions (debits and credits); {inc_stored} new income records")
            total += stored + inc_stored
            continue
        if source == "chase" and "freedom" in csv_file.name.lower():
            txns = parse_chase_csv(csv_file, account_name="Chase Freedom")
        else:
            txns = PARSERS[source](csv_file)
        if source == "capital" and "wendy" in csv_file.name.lower():
            for txn in txns:
                txn.account_name = "Capital One Wendy"
        stored = store_transactions(conn, txns)
        _record_import(conn, csv_file)
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

    # Link PayPal duplicates to card charges
    paypal_linked = link_paypal_to_cards(conn)
    if paypal_linked > 0:
        click.echo(f"  PayPal: {paypal_linked} transactions linked to card charges")

    repayments_linked = link_recorded_reimbursements(conn)
    if repayments_linked > 0:
        click.echo(f"  Credits: {repayments_linked} matched a reimbursement already recorded, not double-counted")

@cli.command("daily-note")
@click.option("--dir", "daily_dir", type=click.Path(file_okay=False, path_type=Path),
              default=Path.home() / "Documents/clearwater/daily", show_default=True,
              help="Folder of YYYY-MM-DD.md daily notes.")
@click.option("--date", "day", help="Note date (YYYY-MM-DD). Defaults to today.")
@click.pass_context
def daily_note(ctx, daily_dir, day):
    """Write spending, free cash, and alarms into the daily note's frontmatter."""
    today = date.fromisoformat(day) if day else date.today()
    note = daily_dir / f"{today.isoformat()}.md"
    if not note.exists():
        # The morning job creates the note from its template; creating it here would skip the template.
        click.echo(f"No daily note at {note} yet, skipping.")
        return
    fields = daily_note_fields(ctx.obj["conn"], today)
    note.write_text(update_frontmatter(note.read_text(), fields))
    click.echo(f"Updated {note}: " + ", ".join(f"{k}={v}" for k, v in fields.items()))

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
@click.argument("query")
@click.option("--year", type=int, default=None, help="Filter by year.")
@click.option("--date-from", default=None, help="Only transactions on/after this date (YYYY-MM-DD).")
@click.option("--date-to", default=None, help="Only transactions on/before this date (YYYY-MM-DD).")
@click.option("--min-amount", type=float, default=None, help="Minimum amount (charges positive, refunds negative).")
@click.option("--max-amount", type=float, default=None, help="Maximum amount.")
@click.option("--who", type=click.Choice(["fred", "wife", "shared"]), default=None, help="Filter by person.")
@click.option("--account", default=None, help="Account name substring; broad substrings match several cards ('capital one' matches all three Cap One buckets).")
@click.option("--limit", type=int, default=20, help="Max results.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (one object per transaction, for scripts).")
@click.pass_context
def find(ctx, query, year, date_from, date_to, min_amount, max_amount, who, account, limit, as_json):
    """Search transactions by merchant or description."""
    conn = ctx.obj["conn"]
    for label, value in (("--date-from", date_from), ("--date-to", date_to)):
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise click.BadParameter("expected YYYY-MM-DD", param_hint=label)
    sql = (
        "SELECT t.id, t.date, t.amount, t.merchant, t.description, "
        "c.name AS category, a.name AS account, t.who "
        "FROM transactions t "
        "LEFT JOIN categories c ON t.category_id = c.id "
        "LEFT JOIN accounts a ON t.account_id = a.id "
        "WHERE t.canonical_id IS NULL AND (LOWER(t.merchant) LIKE ? OR LOWER(t.description) LIKE ?)"
    )
    params = [f"%{query.lower()}%", f"%{query.lower()}%"]
    if year:
        sql += " AND strftime('%Y', t.date) = ?"
        params.append(str(year))
    if date_from:
        sql += " AND t.date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND t.date <= ?"
        params.append(date_to)
    if min_amount is not None:
        sql += " AND t.amount >= ?"
        params.append(min_amount)
    if max_amount is not None:
        sql += " AND t.amount <= ?"
        params.append(max_amount)
    if who:
        sql += " AND t.who = ?"
        params.append(who)
    if account:
        sql += " AND LOWER(a.name) LIKE ?"
        params.append(f"%{account.lower()}%")
    sql += " ORDER BY t.date DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    if as_json:
        click.echo(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        click.secho(f"No transactions matching '{query}'.", fg="yellow")
        return

    click.echo(f"\n{'ID':>6}  {'Date':<12}  {'Amount':>10}  {'Category':<20}  Merchant")
    click.echo("-" * 80)
    for r in rows:
        cat = r["category"] or "?"
        click.echo(f"{r['id']:>6}  {r['date']:<12}  ${r['amount']:>9,.2f}  {cat:<20}  {r['merchant'][:30]}")


@cli.command()
@click.option("--all", "show_all", is_flag=True,
              help="Include same-account pairs (two identical purchases; usually genuine).")
@click.option("--json", "as_json", is_flag=True, help="Output JSON (one object per pair, for scripts).")
@click.pass_context
def dupes(ctx, show_all, as_json):
    """List likely duplicate charges (same amount, fuzzy merchant, within 3 days).

    By default only cross-account pairs are shown — one purchase recorded by
    two cards/pipelines, the double-posting signature. Same-account repeats
    (two genuinely identical purchases) appear with --all. Occurrence-suffix
    siblings (`-occurrence-N`) are never listed; those are intentional
    same-day purchases. Advisory review list, not a deletion list:
    remediate confirmed pairs with `cashflow dedupe-link`.
    """
    conn = ctx.obj["conn"]
    sql = "SELECT * FROM possible_dupes"
    if not show_all:
        sql += " WHERE account_a != account_b"
    sql += " ORDER BY date_a DESC, id_a"
    rows = conn.execute(sql).fetchall()
    if as_json:
        click.echo(json.dumps([dict(r) for r in rows], indent=2))
        return
    if not rows:
        click.secho("No possible duplicate pairs found.", fg="green")
        return

    scope = "cross-account" if not show_all else "all"
    click.echo(f"\n{len(rows)} possible duplicate pairs ({scope}, same amount, fuzzy merchant, <=3 days apart):")
    click.echo(f"\n{'A and B':>13}  {'Dates':<25}  {'Amount':>9}  Merchants")
    click.echo("-" * 110)
    for r in rows:
        ids = f"#{r['id_a']} #{r['id_b']}"
        dates = f"{r['date_a']} -> {r['date_b']}"
        click.echo(
            f"{ids:>13}  {dates:<25}  ${r['amount']:>8,.2f}  "
            f"{r['merchant_a'][:32]} | {r['merchant_b'][:32]}"
        )
        click.echo(
            f"{'':>13}  accounts: {r['account_a']} / {r['account_b']}"
            f"  who: {r['who_a']} / {r['who_b']}"
        )


@cli.command("dedupe-link")
@click.argument("keep_id", type=int, required=False, default=None)
@click.argument("dupe_id", type=int, required=False, default=None)
@click.option("--from-dupes", is_flag=True, help="Bulk mode: link pairs from the possible_dupes view (cross-account by default).")
@click.option("--all", "show_all", is_flag=True, help="Bulk mode: include same-account pairs.")
@click.option("--merchant", default=None, help="Bulk: only pairs where either merchant matches this substring.")
@click.option("--account", default=None, help="Bulk: only pairs where either account name matches this substring.")
@click.option("--date-from", default=None, help="Bulk: only pairs on/after this date (YYYY-MM-DD, by the earlier charge).")
@click.option("--date-to", default=None, help="Bulk: only pairs on/before this date (YYYY-MM-DD, by the earlier charge).")
@click.option("--yes", is_flag=True, help="Bulk: skip the confirmation prompt.")
@click.pass_context
def dedupe_link(ctx, keep_id, dupe_id, from_dupes, show_all, merchant, account, date_from, date_to, yes):
    """Mark duplicate charges: DUPE becomes a copy of KEEP and stops counting in totals.

    Single pair:  cashflow dedupe-link 2817 3157    (3157 linked to 2817)

    Bulk mode reviews pairs from `cashflow dupes`, keeps the earlier-dated
    charge of each pair (lower id breaks ties), links the later one, and
    asks for confirmation before writing. Filters narrow the set; pairs
    already linked are skipped. Undo with `cashflow dedupe-unlink`.
    """
    conn = ctx.obj["conn"]

    if not from_dupes:
        if keep_id is None or dupe_id is None:
            raise click.ClickException("provide two transaction IDs (KEEP DUPE), or use --from-dupes for bulk mode")
        _link_single(conn, keep_id, dupe_id)
        return

    if keep_id is not None or dupe_id is not None:
        raise click.ClickException("transaction IDs cannot be combined with --from-dupes")
    for label, value in (("--date-from", date_from), ("--date-to", date_to)):
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise click.BadParameter("expected YYYY-MM-DD", param_hint=label)

    sql = "SELECT * FROM possible_dupes WHERE 1=1"
    params = []
    if not show_all:
        sql += " AND account_a != account_b"
    if merchant:
        sql += " AND (LOWER(merchant_a) LIKE ? OR LOWER(merchant_b) LIKE ?)"
        params += [f"%{merchant.lower()}%", f"%{merchant.lower()}%"]
    if account:
        sql += " AND (LOWER(account_a) LIKE ? OR LOWER(account_b) LIKE ?)"
        params += [f"%{account.lower()}%", f"%{account.lower()}%"]
    if date_from:
        sql += " AND date_a >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date_a <= ?"
        params.append(date_to)
    sql += " ORDER BY date_a, id_a"
    pairs = conn.execute(sql, params).fetchall()

    plans, skipped = [], 0
    planned_dupes = set()  # ids already scheduled as dupes earlier in this batch
    for p in pairs:
        if p["id_a"] in planned_dupes or p["id_b"] in planned_dupes:
            skipped += 1
            continue
        a = conn.execute("SELECT id, date, canonical_id FROM transactions WHERE id = ?", (p["id_a"],)).fetchone()
        b = conn.execute("SELECT id, date, canonical_id FROM transactions WHERE id = ?", (p["id_b"],)).fetchone()
        if a["canonical_id"] is not None or b["canonical_id"] is not None:
            skipped += 1
            continue
        keep_side = "a" if p["date_a"] <= p["date_b"] else "b"
        keep_id_, dupe_id_ = (p["id_a"], p["id_b"]) if keep_side == "a" else (p["id_b"], p["id_a"])
        planned_dupes.add(dupe_id_)
        plans.append({
            "keep": keep_id_,
            "dupe": dupe_id_,
            "dupe_date": p["date_b"] if keep_side == "a" else p["date_a"],
            "dupe_merchant": p["merchant_b"] if keep_side == "a" else p["merchant_a"],
            "dupe_account": p["account_b"] if keep_side == "a" else p["account_a"],
            "keep_account": p["account_a"] if keep_side == "a" else p["account_b"],
            "amount": p["amount"],
        })

    if not plans:
        if skipped:
            click.secho(f"No linkable pairs ({skipped} handled earlier in this batch; the view already hides linked pairs).", fg="yellow")
        else:
            click.secho("No matching pairs to link.", fg="yellow")
        return

    scope = "cross-account" if not show_all else "all"
    click.echo(f"\n{len(plans)} pairs to link ({scope}), keeping the earlier-dated charge:")
    for p in plans:
        click.echo(
            f"  link #{p['dupe']} -> keep #{p['keep']}   {p['dupe_date']}   ${p['amount']:>9,.2f}  "
            f"{p['dupe_merchant'][:30]}   ({p['dupe_account']} -> {p['keep_account']})"
        )
    if skipped:
        click.echo(f"  ({skipped} pairs skipped: already linked, or handled earlier in this batch)")
    click.echo(f"\nSpending totals will drop by ${sum(p['amount'] for p in plans):,.2f} once linked.")

    if not yes and not click.confirm(f"Link {len(plans)} pairs?"):
        click.echo("No changes made.")
        return

    for p in plans:
        conn.execute("UPDATE transactions SET canonical_id = ? WHERE id = ?", (p["keep"], p["dupe"]))
    conn.commit()
    click.secho(f"Linked {len(plans)} duplicate charges.", fg="green")
    click.echo("Run `cashflow dupes` to confirm the pairs no longer appear; `cashflow dedupe-unlink` undoes.")


def _link_single(conn, keep_id, dupe_id):
    if keep_id == dupe_id:
        raise click.ClickException("a transaction cannot be linked to itself")
    keep = conn.execute("SELECT * FROM transactions WHERE id = ?", (keep_id,)).fetchone()
    dupe = conn.execute("SELECT * FROM transactions WHERE id = ?", (dupe_id,)).fetchone()
    if not keep:
        raise click.ClickException(f"Transaction {keep_id} not found")
    if not dupe:
        raise click.ClickException(f"Transaction {dupe_id} not found")
    if keep["canonical_id"] is not None:
        raise click.ClickException(
            f"#{keep_id} is itself a linked duplicate of #{keep['canonical_id']}; link to the surviving row"
        )
    relinked = dupe["canonical_id"] is not None
    conn.execute("UPDATE transactions SET canonical_id = ? WHERE id = ?", (keep_id, dupe_id))
    conn.commit()
    was = f" (was linked to #{dupe['canonical_id']})" if relinked else ""
    click.secho(
        f"#{dupe_id} {dupe['merchant']} on {dupe['date']} ${dupe['amount']:,.2f} "
        f"linked to #{keep_id}{was} — excluded from totals now",
        fg="green",
    )


@cli.command("dedupe-unlink")
@click.argument("dupe_ids", type=int, nargs=-1, required=True)
@click.pass_context
def dedupe_unlink(ctx, dupe_ids):
    """Undo dedupe-link: these linked duplicates become normal charges again."""
    conn = ctx.obj["conn"]
    unlinked = 0
    for txn_id in dupe_ids:
        txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
        if not txn:
            raise click.ClickException(f"Transaction {txn_id} not found")
        if txn["canonical_id"] is None:
            click.secho(f"#{txn_id} is not a linked duplicate, skipping.", fg="yellow")
            continue
        conn.execute("UPDATE transactions SET canonical_id = NULL WHERE id = ?", (txn_id,))
        unlinked += 1
        click.secho(f"#{txn_id} unlinked (was a copy of #{txn['canonical_id']}).", fg="green")
    conn.commit()
    if unlinked:
        click.secho(f"{unlinked} transaction(s) count in totals again.", fg="green")


@cli.command()
@click.argument("txn_id", type=int)
@click.argument("category", type=str)
@click.pass_context
def recategorize(ctx, txn_id, category):
    """Change the category of a single transaction."""
    conn = ctx.obj["conn"]

    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        click.secho(f"Transaction {txn_id} not found.", fg="red")
        return

    cat = conn.execute(
        "SELECT id, name FROM categories WHERE LOWER(name) = LOWER(?)", (category,)
    ).fetchone()
    if not cat:
        click.secho(f"Category \"{category}\" not found.", fg="red")
        click.echo("Available categories:")
        for row in conn.execute("SELECT name FROM categories ORDER BY name"):
            click.echo(f"  {row['name']}")
        return

    conn.execute(
        "UPDATE transactions SET category_id = ?, status = 'confirmed' WHERE id = ?",
        (cat["id"], txn_id),
    )
    conn.commit()
    click.secho(
        f"#{txn_id} → {cat['name']} "
        f"(${txn['amount']:,.2f} on {txn['date']})",
        fg="green",
    )


@cli.command()
@click.pass_context
def freshness(ctx):
    """Show how stale each account's data is."""
    conn = ctx.obj["conn"]
    rows = conn.execute(
        "SELECT a.name, MAX(t.date) as last_date, COUNT(t.id) as txn_count "
        "FROM accounts a "
        "LEFT JOIN transactions t ON t.account_id = a.id AND t.canonical_id IS NULL "
        "WHERE a.is_active = 1 "
        "GROUP BY a.id, a.name "
        "ORDER BY last_date"
    ).fetchall()
    if not rows:
        click.echo("No accounts found.")
        return

    click.echo(f"\n{'Account':<35} {'Last Transaction':<18} {'Age':>8} {'Txns':>6}")
    click.echo("-" * 72)
    today = date.today()
    for r in rows:
        last = r["last_date"]
        count = r["txn_count"]
        if not last:
            age_str = "never"
            color = "red"
        else:
            days = (today - date.fromisoformat(last)).days
            if days > 60:
                age_str = f"{days}d"
                color = "red"
            elif days > 30:
                age_str = f"{days}d"
                color = "yellow"
            else:
                age_str = f"{days}d"
                color = "green"
        line = f"{r['name']:<35} {last or '—':<18} {age_str:>8} {count:>6}"
        click.secho(line, fg=color)


@cli.command()
@click.pass_context
def fees(ctx):
    """Show credit card annual fees and projected renewal dates."""
    conn = ctx.obj["conn"]
    rows = conn.execute(
        "SELECT t.merchant, t.amount, t.date, a.name as account "
        "FROM transactions t "
        "JOIN accounts a ON t.account_id = a.id "
        "JOIN categories c ON t.category_id = c.id "
        "WHERE c.name = 'Credit Card Fees' AND t.canonical_id IS NULL AND t.amount > 0 "
        "AND (LOWER(t.merchant || ' ' || t.description) LIKE '%annual%' "
        "OR LOWER(t.merchant || ' ' || t.description) LIKE '%member fee%' "
        "OR LOWER(t.merchant || ' ' || t.description) LIKE '%membership fee%') "
        "ORDER BY t.date DESC"
    ).fetchall()
    if not rows:
        click.secho("No annual fees found. Categorize fee transactions as 'Credit Card Fees' first.", fg="yellow")
        return

    # Show the most recent fee per account and merchant even if its price changed.
    seen = {}
    for r in rows:
        key = (r["account"], r["merchant"])
        if key not in seen:
            seen[key] = r

    click.echo(f"\n{'Card / Fee':<35} {'Account':<22} {'Amount':>10} {'Last Charged':<14} {'Next Expected':<14} {'Days':>5}")
    click.echo("-" * 105)
    today = date.today()
    for (account, merchant), r in sorted(seen.items(), key=lambda x: x[1]["date"]):
        amount = r["amount"]
        last = date.fromisoformat(r["date"])
        next_due = date(last.year + 1, last.month, min(last.day, monthrange(last.year + 1, last.month)[1]))
        days_until = (next_due - today).days
        if days_until < 0:
            days_str = "PAST"
            color = "red"
        elif days_until < 30:
            days_str = str(days_until)
            color = "yellow"
        else:
            days_str = str(days_until)
            color = None
        line = f"{merchant:<35} {account:<22} ${amount:>9,.2f} {r['date']:<14} {next_due.isoformat():<14} {days_str:>5}"
        if color:
            click.secho(line, fg=color)
        else:
            click.echo(line)
    click.echo(f"\nObserved annual fees (renewal estimates): ${sum(r['amount'] for r in seen.values()):,.2f}/year")


@cli.command()
@click.argument("txn_id", type=int)
@click.argument("amount", type=float)
@click.pass_context
def reimburse(ctx, txn_id, amount):
    """Record a partial or full reimbursement on a transaction."""
    conn = ctx.obj["conn"]
    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        click.secho(f"Transaction {txn_id} not found.", fg="red")
        return
    if not math.isfinite(amount):
        raise click.BadParameter("Reimbursement must be finite", param_hint="amount")
    if amount > txn["amount"]:
        click.secho(f"Reimbursement ${amount:,.2f} exceeds transaction amount ${txn['amount']:,.2f}.", fg="red")
        return
    if amount <= 0:
        click.secho("Reimbursement amount must be positive.", fg="red")
        return
    is_full = abs(amount - txn["amount"]) < 0.005
    conn.execute(
        "UPDATE transactions SET reimbursed_amount = ?, is_reimbursed = ? WHERE id = ?",
        (amount, 1 if is_full else 0, txn_id),
    )
    conn.commit()
    net = txn["amount"] - amount
    click.secho(
        f"#{txn_id} {txn['merchant']} on {txn['date']}: "
        f"${txn['amount']:,.2f} - ${amount:,.2f} reimbursed = ${net:,.2f} net",
        fg="green",
    )


@cli.command()
@click.argument("txn_id", type=int)
@click.argument("merchant", type=str)
@click.pass_context
def rename(ctx, txn_id, merchant):
    """Rename the merchant on a transaction."""
    conn = ctx.obj["conn"]
    txn = conn.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    if not txn:
        click.secho(f"Transaction {txn_id} not found.", fg="red")
        return
    conn.execute("UPDATE transactions SET merchant = ? WHERE id = ?", (merchant, txn_id))
    conn.commit()
    click.secho(
        f"#{txn_id} renamed: \"{txn['merchant']}\" → \"{merchant}\"",
        fg="green",
    )


@cli.command()
@click.argument("txn_id", type=int, required=False, default=None)
@click.option("--one-off", type=str, help="Label this transaction as a one-off expense.")
@click.option("--search", type=str, help="Batch tag transactions matching this merchant/description pattern.")
@click.option("--date-from", type=str, help="Filter by start date (YYYY-MM-DD).")
@click.option("--date-to", type=str, help="Filter by end date (YYYY-MM-DD).")
@click.pass_context
def tag(ctx, txn_id, one_off, search, date_from, date_to):
    """Tag a transaction (e.g., as a one-off expense).

    Single: cashflow tag 123 --one-off "japan 2026"
    Batch:  cashflow tag --search "JP" --one-off "japan 2026"
    """
    conn = ctx.obj["conn"]

    if search:
        if not one_off:
            click.secho("--one-off is required for batch tagging.", fg="red")
            return

        sql = (
            "SELECT t.id, t.date, t.amount, t.merchant, t.description, a.name as account "
            "FROM transactions t JOIN accounts a ON t.account_id = a.id "
            "WHERE t.canonical_id IS NULL AND t.is_one_off = 0 "
            "AND (LOWER(t.merchant) LIKE ? OR LOWER(t.description) LIKE ?)"
        )
        params = [f"%{search.lower()}%", f"%{search.lower()}%"]

        if date_from:
            sql += " AND t.date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND t.date <= ?"
            params.append(date_to)

        sql += " ORDER BY t.date"
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            click.secho(f"No untagged transactions matching '{search}'.", fg="yellow")
            return

        click.echo(f"\nFound {len(rows)} transactions to tag as \"{one_off}\":\n")
        total = 0
        for r in rows:
            click.echo(f"  {r['date']}  ${r['amount']:>9,.2f}  {r['account']:<16} {r['merchant'][:40]}")
            total += r["amount"]
        click.echo(f"\n  Total: ${total:,.2f}")

        if not click.confirm(f"\nTag all {len(rows)} as one-off \"{one_off}\"?"):
            return

        ids = [r["id"] for r in rows]
        conn.execute(
            f"UPDATE transactions SET is_one_off = 1, one_off_label = ? "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            [one_off] + ids,
        )
        conn.commit()
        click.secho(f"Tagged {len(ids)} transactions.", fg="green")
        return

    if txn_id is None:
        click.secho("Provide a transaction ID or use --search for batch tagging.", fg="red")
        return

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
    if not pattern.strip():
        raise click.BadParameter("Rule pattern must not be empty", param_hint="pattern")

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
            "UPDATE merchant_rules SET category_id = ?, source = 'manual', confidence = 100 WHERE id = ?",
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
        "WHERE canonical_id IS NULL AND instr(LOWER(merchant), LOWER(?)) > 0",
        (cat["id"], pattern),
    ).rowcount
    conn.commit()

    if updated > 0:
        click.secho(f"  Recategorized {updated} transactions.", fg="green")


@rule.command("delete")
@click.argument("pattern")
@click.pass_context
def rule_delete(ctx, pattern):
    """Delete a merchant rule. Already-categorized transactions keep their category."""
    conn = ctx.obj["conn"]
    deleted = conn.execute("DELETE FROM merchant_rules WHERE pattern = ?", (pattern,)).rowcount
    conn.commit()
    if not deleted:
        raise click.ClickException(f"No rule with pattern '{pattern}'. See `cashflow rule list`.")
    click.secho(f"Deleted rule '{pattern}'", fg="green")


@rule.command("apply")
@click.pass_context
def rule_apply(ctx):
    """Re-run all merchant rules on pending uncategorized transactions."""
    conn = ctx.obj["conn"]
    matched, unmatched = categorize_by_rules(conn)
    click.echo(f"Rules matched: {matched}, unmatched: {unmatched}")


@rule.command("add-category")
@click.argument("name")
@click.argument("type", type=click.Choice(["n", "w", "necessity", "want"]))
@click.pass_context
def rule_add_category(ctx, name, type):
    """Add a new spending category. Type: n=necessity, w=want."""
    full_type = "necessity" if type in ("n", "necessity") else "want"
    conn = ctx.obj["conn"]
    try:
        conn.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, full_type))
        conn.commit()
        click.secho(f"Added category: {name} ({full_type})", fg="green")
    except Exception:
        click.secho(f"Category '{name}' already exists.", fg="yellow")


@cli.command()
@click.option("--year", type=int, default=None, help="Plan year (default: current year).")
@click.option("--balance", type=float, default=None, help="FSA balance to track against.")
@click.option("--claim", is_flag=True, help="Interactively mark transactions as claimed.")
@click.option("--claim-all", is_flag=True, help="Mark all unclaimed candidates as reimbursed.")
@click.pass_context
def fsa(ctx, year, balance, claim, claim_all):
    """Find FSA-reimbursable transactions and track claims."""
    conn = ctx.obj["conn"]
    year = year or date.today().year
    rows = get_fsa_candidates(conn, year)

    if not rows:
        click.secho(f"No FSA-eligible transactions found for {year}.", fg="yellow")
        return

    unclaimed = [r for r in rows if not r["is_reimbursed"]]
    claimed = [r for r in rows if r["is_reimbursed"]]
    unclaimed_total = sum(r["amount"] for r in unclaimed)
    claimed_total = sum(r["reimbursed_amount"] for r in claimed)

    if unclaimed:
        click.echo(f"\n  Unclaimed FSA-eligible transactions ({year}):\n")
        click.echo(f"  {'ID':>6}  {'Date':<12} {'Amount':>10}  {'Category':<12} {'Merchant':<35} {'Account'}")
        click.echo(f"  {'-'*100}")
        for r in unclaimed:
            cat = r["category"] or "?"
            click.echo(
                f"  {r['id']:>6}  {r['date']:<12} ${r['amount']:>9,.2f}  {cat:<12} {r['merchant'][:35]:<35} {r['account']}"
            )
        click.echo(f"  {'-'*100}")
        click.secho(f"  Unclaimed total: ${unclaimed_total:,.2f}  ({len(unclaimed)} transactions)", fg="cyan", bold=True)

    if claimed:
        click.echo(f"\n  Already claimed:")
        for r in claimed:
            click.echo(f"  {r['id']:>6}  {r['date']:<12} ${r['reimbursed_amount']:>9,.2f}  {r['merchant'][:35]}")
        click.secho(f"  Claimed total: ${claimed_total:,.2f}", fg="green")

    if balance is not None:
        remaining = balance - claimed_total
        after_all = remaining - unclaimed_total
        click.echo()
        click.secho(f"  FSA balance:     ${balance:>10,.2f}", bold=True)
        if claimed_total > 0:
            click.secho(f"  Already claimed: ${claimed_total:>10,.2f}")
            click.secho(f"  Remaining:       ${remaining:>10,.2f}")
        click.secho(f"  If all claimed:  ${after_all:>10,.2f} left to spend by Dec 31", fg="yellow" if after_all > 0 else "green")

    click.echo()

    if claim_all and unclaimed:
        if not click.confirm(f"Mark all {len(unclaimed)} unclaimed transactions (${unclaimed_total:,.2f}) as FSA-reimbursed?"):
            return
        ids = [r["id"] for r in unclaimed]
        conn.execute(
            f"UPDATE transactions SET is_reimbursed = 1, reimbursed_amount = amount "
            f"WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        conn.commit()
        click.secho(f"  Marked {len(ids)} transactions as reimbursed.", fg="green")
        return

    if claim and unclaimed:
        marked = 0
        for r in unclaimed:
            click.echo(f"\n  {r['date']}  ${r['amount']:>9,.2f}  {r['merchant']}")
            choice = click.prompt("  [y]es / [n]o / [q]uit", default="y")
            if choice.lower() == "q":
                break
            if choice.lower() == "y":
                conn.execute(
                    "UPDATE transactions SET is_reimbursed = 1, reimbursed_amount = amount WHERE id = ?",
                    (r["id"],),
                )
                marked += 1
        conn.commit()
        if marked:
            click.secho(f"\n  Marked {marked} transactions as FSA-reimbursed.", fg="green")


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


cli.add_command(plan)
cli.add_command(audit)
