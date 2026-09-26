from datetime import date, timedelta

import click

from cashflow.audit import Recurring, category_spikes, find_recurring, record_decision

_RECENTLY_STOPPED_DAYS = 180


def _money(amount: float) -> str:
    return f"${amount:,.2f}"


def _row(item: Recurring) -> str:
    category = item.category or "?"
    return (
        f"  {_money(item.monthly_cost):>10}/mo {_money(item.annual_cost):>11}/yr  {item.cadence:<8} "
        f"{item.last_seen.isoformat():<11} {category[:18]:<18} {item.key}"
    )


def _alarms(items: list[Recurring]) -> list[tuple[str, str]]:
    alarms = []
    for item in items:
        if item.charged_after_cancel:
            alarms.append((
                f"{item.key}: charged {_money(item.latest_amount)} on {item.charged_after_cancel} "
                f"after you cancelled it on {item.decided_on}", "red"))
        if item.active and item.price_increase and not item.is_new and item.decision != "cancel":
            alarms.append((
                f"{item.key}: price up {_money(item.price_increase)} to {_money(item.latest_amount)}", "yellow"))
        if item.is_new and item.decision is None:
            alarms.append((
                f"{item.key}: new recurring charge, {_money(item.monthly_cost)}/mo since {item.first_seen}", "yellow"))
    return alarms


@click.group(invoke_without_command=True)
@click.option("--all", "show_all", is_flag=True, help="List kept charges individually.")
@click.pass_context
def audit(ctx, show_all):
    """Find recurring charges and spending spikes worth a second look."""
    if ctx.invoked_subcommand is None:
        _show_audit(ctx.obj["conn"], date.today(), show_all)


def _show_audit(conn, today: date, show_all: bool) -> None:
    items = find_recurring(conn, today)
    active = [i for i in items if i.active]

    alarms = _alarms(items)
    if alarms:
        click.secho("\nAlarms", bold=True)
        for message, color in alarms:
            click.secho(f"  ! {message}", fg=color)

    to_review = [i for i in active if i.decision is None]
    if to_review:
        monthly = sum(i.monthly_cost for i in to_review)
        click.secho(
            f"\nTo review ({len(to_review)} charges, {_money(monthly)}/mo, {_money(monthly * 12)}/yr)", bold=True)
        for item in to_review:
            click.echo(_row(item))

    kept = [i for i in active if i.decision == "keep"]
    if kept:
        monthly = sum(i.monthly_cost for i in kept)
        click.echo(f"\nKept: {len(kept)} charges, {_money(monthly)}/mo" + ("" if show_all else "  (--all to list)"))
        if show_all:
            for item in kept:
                click.echo(_row(item))

    watching = [i for i in items if i.decision == "cancel" and not i.charged_after_cancel]
    if watching:
        click.echo(f"\nCancelled, watching for new charges: {', '.join(i.key for i in watching)}")

    cutoff = today - timedelta(days=_RECENTLY_STOPPED_DAYS)
    stopped = [i for i in items if not i.active and i.last_seen >= cutoff and i.decision != "cancel"]
    if stopped:
        click.secho("\nRecently stopped", bold=True)
        for item in stopped:
            click.echo(f"  {item.key}: last {_money(item.latest_amount)} on {item.last_seen}")

    spikes = category_spikes(conn, today)
    if spikes:
        click.secho(f"\nSpending spikes in {spikes[0].month:%B %Y} (vs 6-month median, one-offs excluded)", bold=True)
        for spike in spikes:
            click.echo(
                f"  {spike.category}: {_money(spike.month_total)} vs {_money(spike.median)} "
                f"(+{_money(spike.delta)})")

    if not (alarms or to_review or kept or watching or stopped or spikes):
        click.secho("Nothing to flag.", fg="green")
    elif to_review:
        click.echo('\nDecide with: cashflow audit keep|cancel|ignore "<part of the name>"')


def _resolve(conn, text: str) -> Recurring:
    items = find_recurring(conn, date.today(), include_ignored=True)
    needle = text.lower().strip()
    exact = [i for i in items if i.key == needle]
    if exact:
        return exact[0]
    matches = [i for i in items if needle in i.key or needle in i.label.lower()]
    if not matches:
        raise click.ClickException(f"No recurring charge matches '{text}'. Run `cashflow audit` to see names.")
    if len(matches) > 1:
        names = "\n".join(f"  {i.key}" for i in matches)
        raise click.ClickException(f"'{text}' matches more than one charge; be more specific:\n{names}")
    return matches[0]


def _decide(decision: str, past_tense: str):
    @click.argument("name")
    @click.option("--note", help="Why, for future you.")
    @click.pass_context
    def command(ctx, name, note):
        conn = ctx.obj["conn"]
        item = _resolve(conn, name)
        record_decision(conn, item.key, decision, today=date.today(), note=note)
        click.secho(f"{past_tense} {item.key} ({_money(item.monthly_cost)}/mo)", fg="green")
    return command


audit.command("keep", help="Mark a recurring charge as wanted.")(_decide("keep", "Keeping"))
audit.command("cancel", help="Mark a charge as cancelled; alarms if it charges again.")(_decide("cancel", "Watching"))
audit.command("ignore", help="Hide a false positive.")(_decide("ignore", "Ignoring"))
