import functools
import sqlite3
from datetime import date

import click

from cashflow.plans import (
    KINDS,
    STATUSES,
    PlanLine,
    add_plan,
    defer_plan,
    monthly_free_cash,
    set_status,
    summarize,
    update_plan,
)


def _parse_amount(text: str) -> float:
    cleaned = text.strip().lower().replace("$", "").replace(",", "")
    multiplier = 1000 if cleaned.endswith("k") else 1
    return float(cleaned.rstrip("k")) * multiplier


def _cost_option(ctx, param, value):
    if value is None:
        return None
    parts = value.split("-")
    try:
        if len(parts) > 2:
            raise ValueError
        amounts = [_parse_amount(p) for p in parts]
    except ValueError:
        raise click.BadParameter("expected an amount or range like 5000, 1000-2000, or 10k-15k")
    return amounts[0], amounts[-1]


def _month_or_date(ctx, param, value):
    if value is None:
        return None
    try:
        return date.fromisoformat(value if len(value) > 7 else f"{value}-01")
    except ValueError:
        raise click.BadParameter("expected YYYY-MM or YYYY-MM-DD")


def _clean_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise click.ClickException(str(e))
    return wrapper


def _money(amount: float) -> str:
    sign = "−" if round(amount) < 0 else ""
    return f"{sign}${abs(amount):,.0f}"


def _range(line: PlanLine) -> str:
    if line.pick_one:
        return ""
    if line.cost_low is None or line.cost_high is None:
        return "needs estimate"
    if line.cost_low == line.cost_high:
        return _money(line.cost_low)
    return f"{_money(line.cost_low)}–{line.cost_high:,.0f}"


def _title(line: PlanLine) -> str:
    title = f"  ↳ {line.title}" if line.depth else line.title
    if line.pick_one:
        title += " (pick one)"
    if line.necessity:
        title += " [need]"
    return title


def _status(line: PlanLine) -> str:
    if line.status == "deferred" and line.times_deferred > 1:
        return f"deferred×{line.times_deferred}"
    return line.status


def _optional_money(amount) -> str:
    return _money(amount) if amount is not None else "—"


@click.group(invoke_without_command=True)
@click.pass_context
def plan(ctx):
    """Medium- and long-term plans weighed against free cash flow."""
    if ctx.invoked_subcommand is None:
        _show_plans(ctx.obj["conn"])


def _show_plans(conn: sqlite3.Connection) -> None:
    today = date.today()
    cash = monthly_free_cash(conn, today)
    summary = summarize(conn, today=today, monthly_free=cash.free)
    click.echo(
        f"\nFree cash: {_money(cash.income)} income − {_money(cash.baseline_burn)} baseline burn "
        f"= {_money(cash.free)}/mo"
    )
    click.echo(f"  (average of the last {cash.months} complete months; one-offs excluded, reimbursements netted)\n")
    if not summary.lines:
        click.echo("No plans yet. Add one: cashflow plan add SLUG \"Title\" --kind home --cost 1k-2k --p 0.6")
        return

    header = f"{'Plan':<38} {'Status':<12} {'When':<8} {'Range':<16} {'P':>4} {'Expected':>10} {'Cumul.':>10} {'Gap':>10}"
    click.echo(header)
    click.echo("-" * len(header))
    for line in summary.lines:
        when = line.earliest.strftime("%Y-%m") if line.earliest and not line.depth else ""
        probability = f"{line.probability:.2g}" if line.probability is not None else ""
        row = (
            f"{_title(line)[:38]:<38} {_status(line) if not line.depth else '':<12} {when:<8} "
            f"{_range(line):<16} {probability:>4} {_optional_money(line.expected):>10} "
            f"{_money(line.cumulative_expected) if line.cumulative_expected is not None else '':>10} "
        )
        if line.gap:
            click.echo(row, nl=False)
            click.secho(f"{_money(line.gap):>10}", fg="red")
        else:
            click.echo(row)

    click.echo()
    click.secho(
        f"Expected total: {_money(summary.expected_total)}   Worst case: {_money(summary.worst_total)}",
        bold=True,
    )
    click.echo("  Expected = probability × midpoint of range; pick-one plans sum their alternatives.")
    click.echo("  Gap = cumulative expected cost − (free cash/mo × months until the plan starts).")
    if summary.unpriced:
        names = ", ".join(line.slug for line in summary.unpriced)
        click.secho(f"\nNeeds estimate (not in totals): {names}", fg="yellow")


@plan.command("add")
@click.argument("slug")
@click.argument("title")
@click.option("--kind", type=click.Choice(KINDS), required=True)
@click.option("--cost", callback=_cost_option, help="Amount or range: 5000, 1000-2000, 10k-15k.")
@click.option("--p", "probability", type=float, help="Probability it happens, 0-1.")
@click.option("--from", "earliest", callback=_month_or_date, help="Earliest start (YYYY-MM).")
@click.option("--to", "latest", callback=_month_or_date, help="Latest start (YYYY-MM).")
@click.option("--parent", help="Slug of the pick-one plan this is an alternative for.")
@click.option("--pick-one", is_flag=True, help="Children of this plan are mutually exclusive alternatives.")
@click.option("--necessity", is_flag=True, help="Has to happen (e.g. a leak), not a want.")
@click.pass_context
@_clean_errors
def plan_add(ctx, slug, title, kind, cost, probability, earliest, latest, parent, pick_one, necessity):
    """Add a plan. SLUG should match its Obsidian projects/ folder."""
    cost_low, cost_high = cost or (None, None)
    try:
        add_plan(
            ctx.obj["conn"], slug, title, kind, parent=parent, pick_one=pick_one,
            cost_low=cost_low, cost_high=cost_high, probability=probability,
            earliest=earliest, latest=latest, necessity=necessity,
        )
    except sqlite3.IntegrityError:
        raise click.ClickException(f"Plan '{slug}' already exists")
    click.secho(f"Added {slug}: {title}", fg="green")


@plan.command("set")
@click.argument("slug")
@click.option("--cost", callback=_cost_option, help="Amount or range: 5000, 1000-2000, 10k-15k.")
@click.option("--p", "probability", type=float, help="Probability it happens, 0-1.")
@click.option("--from", "earliest", callback=_month_or_date, help="Earliest start (YYYY-MM).")
@click.option("--to", "latest", callback=_month_or_date, help="Latest start (YYYY-MM).")
@click.pass_context
@_clean_errors
def plan_set(ctx, slug, cost, probability, earliest, latest):
    """Update a plan's estimate or window."""
    if cost is None and probability is None and earliest is None and latest is None:
        raise click.UsageError("Nothing to update; pass --cost, --p, --from, or --to.")
    cost_low, cost_high = cost or (None, None)
    update_plan(ctx.obj["conn"], slug, cost_low=cost_low, cost_high=cost_high,
                probability=probability, earliest=earliest, latest=latest)
    click.secho(f"Updated {slug}", fg="green")


@plan.command("status")
@click.argument("slug")
@click.argument("status", type=click.Choice(STATUSES))
@click.option("--note", help="Why the status changed.")
@click.pass_context
@_clean_errors
def plan_status(ctx, slug, status, note):
    """Change a plan's status (use `defer` to push it out)."""
    set_status(ctx.obj["conn"], slug, status, note=note)
    click.secho(f"{slug} → {status}", fg="green")


@plan.command("defer")
@click.argument("slug")
@click.argument("until", callback=_month_or_date)
@click.option("--note", help="Why it was deferred.")
@click.pass_context
@_clean_errors
def plan_defer(ctx, slug, until, note):
    """Defer a plan to a later start (YYYY-MM)."""
    defer_plan(ctx.obj["conn"], slug, until, note=note)
    click.secho(f"{slug} deferred to {until.isoformat()}", fg="green")
