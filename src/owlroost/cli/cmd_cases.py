from pathlib import Path
import tomllib

import click
from loguru import logger


# ======================================================================
# Main command
# ======================================================================

@click.command(name="cases")
@click.argument(
    "selector",
    nargs=-1,   # allow multiple selectors
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

    toml_files = sorted(directory.glob("*.toml"))

    if not toml_files:
        click.echo("No .toml case files found.")
        return

    # ------------------------------------------------------------
    # Assign integer IDs
    # ------------------------------------------------------------
    indexed_files = list(enumerate(toml_files, start=1))

    # ------------------------------------------------------------
    # Helper: resolve selector → Path
    # ------------------------------------------------------------
    def resolve_selector(sel: str) -> Path | None:
        # ---- selector is an integer ID ----
        if sel.isdigit():
            idx = int(sel)
            return next(
                (f for i, f in indexed_files if i == idx),
                None,
            )

        # ---- selector is a filename ----
        path = Path(sel)
        if not path.suffix:
            path = path.with_suffix(".toml")

        return next(
            (f for _, f in indexed_files if f.name == path.name),
            None,
        )

    # ------------------------------------------------------------
    # Comparison mode (2+ selectors)
    # ------------------------------------------------------------
    if len(selector) >= 2:
        paths = []
        for sel in selector:
            match = resolve_selector(sel)
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
        sel = selector[0]
        match = resolve_selector(sel)

        if not match:
            click.echo(f"No case matching '{sel}'")
            return

        _display_case(match)
        return

    # ------------------------------------------------------------
    # No selector → list all cases
    # ------------------------------------------------------------
    click.echo(
        f"{'ID':>3} "
        f"{'FILE':<30} "
        f"{'CASE NAME':<20} "
        f"{'HFP FILE':<30} "
        f"{'OPTIMIZATION':<30}"
    )
    click.echo("-" * 125)

    for idx, filename in indexed_files:
        try:
            with filename.open("rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {filename}: {e}")
            continue

        case_name = data.get("Plan Name", "")
        if len(case_name) > 20:
            case_name = case_name[:16] + "..."

        hfp_name = (
            data.get("Household Financial Profile", {})
                .get("HFP file name", "")
        )

        opt_display = _format_optimization(data)

        click.echo(
            f"{idx:>3} "
            f"{filename.stem:<30} "
            f"{case_name:<20} "
            f"{hfp_name:<30} "
            f"{opt_display:<30}"
        )


# ======================================================================
# Helpers
# ======================================================================

def _format_optimization(data: dict) -> str:
    opt_block = data.get("Optimization Parameters", {})
    solver_opts = data.get("Solver Options", {})

    objective = opt_block.get("Objective", "")

    if objective == "maxSpending":
        target = solver_opts.get("bequest")
        return (
            f"maxSpending (bequest={target})"
            if target is not None
            else "maxSpending"
        )

    if objective == "maxBequest":
        target = solver_opts.get("netSpending")
        return (
            f"maxBequest (netSpending={target})"
            if target is not None
            else "maxBequest"
        )

    return objective or ""


# ======================================================================
# Single-case display (UNCHANGED)
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
    click.echo(f"PLAN NAME : {data.get('Plan Name', '')}")
    click.echo("-" * 80)

    desc = data.get("Description")
    if desc:
        click.echo("DESCRIPTION")
        click.echo(desc)
        click.echo()

    basic = data.get("Basic Info", {})
    if basic:
        click.echo("HOUSEHOLD")
        if basic.get("Names"):
            click.echo(f"  Members        : {', '.join(basic['Names'])}")
        if basic.get("Status"):
            click.echo(f"  Status         : {basic['Status']}")
        if basic.get("Date of birth"):
            click.echo(f"  Birth dates    : {', '.join(basic['Date of birth'])}")
        if basic.get("Life expectancy"):
            click.echo(f"  Life expectancy: {', '.join(map(str, basic['Life expectancy']))}")
        if basic.get("Start date"):
            click.echo(f"  Start date     : {basic['Start date']}")
        click.echo()

    assets = data.get("Assets", {})
    if assets:
        click.echo("ASSETS (balances)")
        click.echo(f"  Taxable        : {sum(assets.get('taxable savings balances', []))}")
        click.echo(f"  Tax-deferred   : {sum(assets.get('tax-deferred savings balances', []))}")
        click.echo(f"  Tax-free       : {sum(assets.get('tax-free savings balances', []))}")
        click.echo()

    hfp = data.get("Household Financial Profile", {})
    if hfp.get("HFP file name"):
        click.echo("HOUSEHOLD FINANCIAL PROFILE")
        click.echo(f"  HFP file       : {hfp['HFP file name']}")
        click.echo()

    fixed = data.get("Fixed Income", {})
    if fixed:
        if fixed.get("Pension monthly amounts") or fixed.get("Social security PIA amounts"):
            click.echo("FIXED INCOME")
            if fixed.get("Pension monthly amounts"):
                click.echo(f"  Pensions (monthly): {', '.join(map(str, fixed['Pension monthly amounts']))}")
            if fixed.get("Social security PIA amounts"):
                click.echo(f"  Social Security PIA: {', '.join(map(str, fixed['Social security PIA amounts']))}")
            click.echo()

    rates = data.get("Rates Selection", {})
    if rates.get("Method"):
        click.echo("RATES")
        click.echo(f"  Method         : {rates['Method']}")
        if rates.get("Values"):
            click.echo(f"  Values         : {rates['Values']}")
        click.echo()

    alloc = data.get("Asset Allocation", {})
    if alloc.get("Type") or alloc.get("Interpolation method"):
        click.echo("ASSET ALLOCATION")
        if alloc.get("Type"):
            click.echo(f"  Type           : {alloc['Type']}")
        if alloc.get("Interpolation method"):
            click.echo(f"  Interpolation  : {alloc['Interpolation method']}")
        click.echo()

    opt = data.get("Optimization Parameters", {})
    solver = data.get("Solver Options", {})

    if opt:
        click.echo("OPTIMIZATION")
        if opt.get("Objective"):
            click.echo(f"  Objective      : {opt['Objective']}")
        if opt.get("Spending profile"):
            click.echo(f"  Spending model : {opt['Spending profile']}")
        if opt.get("Surviving spouse spending percent") is not None:
            click.echo(f"  Survivor spend : {opt['Surviving spouse spending percent']}%")

        if opt.get("Objective") == "maxSpending" and solver.get("bequest") is not None:
            click.echo(f"  Target         : bequest = {solver['bequest']}")
        if opt.get("Objective") == "maxBequest" and solver.get("netSpending") is not None:
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
        return str(val)

    col_width = 22
    label_width = 30

    header = f"{'':<{label_width}}"
    for name, _ in cases:
        header += f"{name[:col_width]:<{col_width}}"
    click.echo(header)
    click.echo("-" * (label_width + col_width * len(cases)))

    rows = [
        ("PLAN NAME", lambda d: d.get("Plan Name", ".")),
        ("HFP FILE", lambda d: get(d, "Household Financial Profile", "HFP file name")),
        ("HOUSEHOLD NAMES", lambda d: fmt(get(d, "Basic Info", "Names"))),
        ("START DATE", lambda d: get(d, "Basic Info", "Start date")),
        ("LIFE EXPECTANCY", lambda d: fmt(get(d, "Basic Info", "Life expectancy"))),
        ("TAXABLE ASSETS", lambda d: sum(get(d, "Assets", "taxable savings balances") or [])),
        ("TAX-DEFERRED ASSETS", lambda d: sum(get(d, "Assets", "tax-deferred savings balances") or [])),
        ("TAX-FREE ASSETS", lambda d: sum(get(d, "Assets", "tax-free savings balances") or [])),
        ("OPT OBJECTIVE", lambda d: get(d, "Optimization Parameters", "Objective")),
        ("OPT TARGET", lambda d:
            f"bequest={get(d,'Solver Options','bequest')}"
            if get(d, "Optimization Parameters", "Objective") == "maxSpending"
            else f"netSpending={get(d,'Solver Options','netSpending')}"
            if get(d, "Optimization Parameters", "Objective") == "maxBequest"
            else "."
        ),
        ("ROTH EXCLUDED", lambda d:
            "no one excluded"
            if get(d, "Solver Options", "noRothConversions") == "None"
            else fmt(get(d, "Solver Options", "noRothConversions"))
        ),
        ("ROTH START YEAR", lambda d: get(d, "Solver Options", "startRothConversions")),
        ("MAX ROTH CONV", lambda d: get(d, "Solver Options", "maxRothConversion")),
        ("SOLVER", lambda d: get(d, "Solver Options", "solver")),
    ]

    for label, extractor in rows:
        line = f"{label:<{label_width}}"
        for _, data in cases:
            line += f"{fmt(extractor(data)):<{col_width}}"
        click.echo(line)
