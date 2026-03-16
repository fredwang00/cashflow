import click
from pathlib import Path
from cashflow.db import get_connection, store_transactions
from cashflow.seed import seed_all
from cashflow.parsers.chase import parse_chase_csv

@click.group()
def cli():
    """Household financial dashboard."""
    pass

@cli.command()
@click.option("--files", type=click.Path(exists=True), help="Path to CSV inbox directory or file.")
@click.option("--email", is_flag=True, help="Poll Gmail for new emails. (Not yet implemented.)")
@click.option("--auto", is_flag=True, help="Run both email and file ingestion.")
def ingest(files, email, auto):
    """Ingest transactions from CSV files or email."""
    conn = get_connection()
    seed_all(conn)
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
    conn.close()
