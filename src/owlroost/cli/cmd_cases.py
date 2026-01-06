import tomllib
from pathlib import Path

import click
from loguru import logger

from owlroost.cli.utils import (
    find_case_files,
    index_case_files,
    print_case_list,
    resolve_case_selector,
)

# ======================================================================
# Main command
# ======================================================================


@click.command(name="cases")
@click.argument(
    "selector",
    nargs=-1,  # allow multiple selectors
)
def cmd_cases(selector):
    """
    List ROOST case files, display a single case, or compare cases.

    SELECTOR may be:
      - omitted (list all cases)
      - one case ID or filename (display)
      - two or more IDs / filenames (compare)
    """

    directory = Path(".")
    logger.debug(f"Scanning directory: {directory}")

    files = find_case_files(directory)

    if not files:
        click.echo("No .toml case files found.")
        return

    indexed_files = index_case_files(files)

    # ------------------------------------------------------------
    # Comparison mode (2+ selectors)
    # ------------------------------------------------------------
    if len(selector) >= 2:
        paths: list[Path] = []

        for sel in selector:
            match = resolve_case_selector(sel, indexed_files)
            if not match:
                click.echo(f"No case matching '{sel}'")
                return
            paths.append(match)

        _display_case_compare(paths)
        return

    # ------------------------------------------------------------
    # Single selector → display case
    # ------------------------------------------------------------
    if len(selector) == 1:
        match = resolve_case_selector(selector[0], indexed_files)
        if not match:
            click.echo(f"No case matching '{selector[0]}'")
            return

        _display_case(match)
        return

    # ------------------------------------------------------------
    # No selector → list all cases
    # ------------------------------------------------------------
    print_case_list(directory)


# ======================================================================
# Single-case display
# ======================================================================


def _display_case(path: Path):
    """
    Display a concise, human-readable summary of a ROOST case file.
    """
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        click.echo(f"Failed to load {path}: {e}")
        return

    click.echo(f"CASE FILE : {path.name}")
    click.echo(f"CASE NAME : {data.get('case_name', '')}")
    click.echo("-" * 80)

    # ------------------------------------------------------------
    # Description
    # ------------------------------------------------------------
    desc = data.get("description")
    if desc:
        click.echo("DESCRIPTION")
        click.echo(desc)
        click.echo()

    # ------------------------------------------------------------
    # Basic household info
    # ------------------------------------------------------------
    basic = data.get("basic_info", {})
    if basic:
        click.echo("HOUSEHOLD")
        if basic.get("names"):
            click.echo(f"  Members        : {', '.join(basic['names'])}")
        if basic.get("status"):
            click.echo(f"  Status         : {basic['status']}")
        if basic.get("date_of_birth"):
            click.echo(f"  Birth dates    : {', '.join(basic['date_of_birth'])}")
        if basic.get("life_expectancy"):
            click.echo(f"  Life expectancy: {', '.join(map(str, basic['life_expectancy']))}")
        if basic.get("start_date"):
            click.echo(f"  Start date     : {basic['start_date']}")
        click.echo()

    # ------------------------------------------------------------
    # Savings assets
    # ------------------------------------------------------------
    assets = data.get("savings_assets", {})
    if assets:
        click.echo("ASSETS (balances)")
        click.echo(f"  Taxable        : {sum(assets.get('taxable_savings_balances', []))}")
        click.echo(f"  Tax-deferred   : {sum(assets.get('tax_deferred_savings_balances', []))}")
        click.echo(f"  Tax-free       : {sum(assets.get('tax_free_savings_balances', []))}")
        click.echo()

    # ------------------------------------------------------------
    # Household financial profile
    # ------------------------------------------------------------
    hfp = data.get("household_financial_profile", {})
    if hfp.get("HFP_file_name"):
        click.echo("HOUSEHOLD FINANCIAL PROFILE")
        click.echo(f"  HFP file       : {hfp['HFP_file_name']}")
        click.echo()

    # ------------------------------------------------------------
    # Fixed income
    # ------------------------------------------------------------
    fixed = data.get("fixed_income", {})
    if fixed:
        if fixed.get("pension_monthly_amounts") or fixed.get("social_security_pia_amounts"):
            click.echo("FIXED INCOME")
            if fixed.get("pension_monthly_amounts"):
                click.echo(
                    f"  Pensions (monthly): "
                    f"{', '.join(map(str, fixed['pension_monthly_amounts']))}"
                )
            if fixed.get("social_security_pia_amounts"):
                click.echo(
                    f"  Social Security PIA: "
                    f"{', '.join(map(str, fixed['social_security_pia_amounts']))}"
                )
            click.echo()

    # ------------------------------------------------------------
    # Rates
    # ------------------------------------------------------------
    rates = data.get("rates_selection", {})
    if rates.get("method"):
        click.echo("RATES")
        click.echo(f"  Method         : {rates['method']}")
        if rates.get("from") is not None and rates.get("to") is not None:
            click.echo(f"  Window         : {rates['from']}–{rates['to']}")
        click.echo()

    # ------------------------------------------------------------
    # Asset allocation
    # ------------------------------------------------------------
    alloc = data.get("asset_allocation", {})
    if alloc.get("type") or alloc.get("interpolation_method"):
        click.echo("ASSET ALLOCATION")
        if alloc.get("type"):
            click.echo(f"  Type           : {alloc['type']}")
        if alloc.get("interpolation_method"):
            click.echo(f"  Interpolation  : {alloc['interpolation_method']}")
        click.echo()

    # ------------------------------------------------------------
    # Optimization & solver
    # ------------------------------------------------------------
    opt = data.get("optimization_parameters", {})
    solver = data.get("solver_options", {})

    if opt:
        click.echo("OPTIMIZATION")
        if opt.get("objective"):
            click.echo(f"  Objective      : {opt['objective']}")
        if opt.get("spending_profile"):
            click.echo(f"  Spending model : {opt['spending_profile']}")
        if opt.get("surviving_spouse_spending_percent") is not None:
            click.echo(f"  Survivor spend : " f"{opt['surviving_spouse_spending_percent']}%")

        if opt.get("objective") == "maxSpending" and solver.get("bequest") is not None:
            click.echo(f"  Target         : bequest = {solver['bequest']}")
        if opt.get("objective") == "maxBequest" and solver.get("netSpending") is not None:
            click.echo(f"  Target         : netSpending = {solver['netSpending']}")

        click.echo()

    if solver:
        click.echo("SOLVER / ROTH POLICY")
        if solver.get("solver"):
            click.echo(f"  Engine              : {solver['solver']}")

        no_roth = solver.get("noRothConversions")
        if no_roth == "None":
            click.echo("  Roth excluded       : no one excluded")
        elif isinstance(no_roth, list) and no_roth:
            click.echo(f"  Roth excluded       : {', '.join(map(str, no_roth))}")
        else:
            click.echo("  Roth excluded       : (not specified)")

        if solver.get("startRothConversions") is not None:
            click.echo(f"  Roth start year     : {solver['startRothConversions']}")
        if solver.get("maxRothConversion") is not None:
            click.echo(f"  Max Roth conversion : {solver['maxRothConversion']}")
        if solver.get("spendingSlack"):
            click.echo(f"  Spending slack      : {solver['spendingSlack']}")
        if solver.get("withMedicare"):
            click.echo(f"  Medicare modeling   : {solver['withMedicare']}")

        click.echo()


# ======================================================================
# Comparison display
# ======================================================================


def _display_case_compare(paths: list[Path]):
    """
    Display a side-by-side comparison of multiple ROOST case files.
    """
    cases = []

    for path in paths:
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
            cases.append((path.name, data))
        except Exception as e:
            click.echo(f"Failed to load {path}: {e}")
            return

    def get(d, *keys):
        for k in keys:
            if d is None:
                return "."
            d = d.get(k)
        return "." if d is None else d

    def fmt(val):
        if isinstance(val, list):
            return ", ".join(map(str, val)) or "."
        return "." if val is None else str(val)

    col_width = 22
    label_width = 30

    header = f"{'':<{label_width}}"
    for name, _ in cases:
        header += f"{name[:col_width]:<{col_width}}"
    click.echo(header)
    click.echo("-" * (label_width + col_width * len(cases)))

    rows = [
        ("CASE NAME", lambda d: d.get("case_name", ".")),
        ("HFP FILE", lambda d: get(d, "household_financial_profile", "HFP_file_name")),
        ("HOUSEHOLD NAMES", lambda d: fmt(get(d, "basic_info", "names"))),
        ("START DATE", lambda d: get(d, "basic_info", "start_date")),
        ("LIFE EXPECTANCY", lambda d: fmt(get(d, "basic_info", "life_expectancy"))),
        (
            "TAXABLE ASSETS",
            lambda d: sum(get(d, "savings_assets", "taxable_savings_balances") or []),
        ),
        (
            "TAX-DEFERRED ASSETS",
            lambda d: sum(get(d, "savings_assets", "tax_deferred_savings_balances") or []),
        ),
        (
            "TAX-FREE ASSETS",
            lambda d: sum(get(d, "savings_assets", "tax_free_savings_balances") or []),
        ),
        ("OPT OBJECTIVE", lambda d: get(d, "optimization_parameters", "objective")),
        (
            "OPT TARGET",
            lambda d: f"bequest={get(d,'solver_options','bequest')}"
            if get(d, "optimization_parameters", "objective") == "maxSpending"
            else f"netSpending={get(d,'solver_options','netSpending')}"
            if get(d, "optimization_parameters", "objective") == "maxBequest"
            else ".",
        ),
        (
            "ROTH EXCLUDED",
            lambda d: "no one excluded"
            if get(d, "solver_options", "noRothConversions") == "None"
            else fmt(get(d, "solver_options", "noRothConversions")),
        ),
        ("ROTH START YEAR", lambda d: get(d, "solver_options", "startRothConversions")),
        ("MAX ROTH CONV", lambda d: get(d, "solver_options", "maxRothConversion")),
        ("SOLVER", lambda d: get(d, "solver_options", "solver")),
    ]

    for label, extractor in rows:
        line = f"{label:<{label_width}}"
        for _, data in cases:
            line += f"{fmt(extractor(data)):<{col_width}}"
        click.echo(line)
