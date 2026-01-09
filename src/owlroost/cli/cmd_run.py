# src/owlroost/cli/cmd_run.py

import subprocess
import sys
import tomllib
from pathlib import Path

import click
from loguru import logger

from owlroost.cli.utils import (
    find_case_files,
    format_click_options,
    format_override_help,
    index_case_files,
    print_case_list,
    resolve_case_selector,
)

CONF_DIR = Path(__file__).parents[1] / "conf"
helper_groups = [
    "basic_info",
    "savings_assets",
    "fixed_income",
    "rates",
    "asset_allocation",
    "optimization",
    "solver",
]

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def get_rate_selection_method(case_file: Path) -> str | None:
    try:
        with case_file.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise click.ClickException(f"Failed to read case file {case_file}: {e}") from None

    return data.get("rates_selection", {}).get("method")


def validate_rate_method_for_trials(
    *,
    rate_method: str | None,
    trials: int | None,
    trial_id: int | None,
):
    requires_stochastic = (trials is not None and trials > 1) or (
        trial_id is not None and trial_id != 0
    )

    if not requires_stochastic:
        return

    allowed = {"stochastic", "histocastic"}

    if rate_method not in allowed:
        raise click.ClickException(
            "Invalid rate_selection.method for trial execution.\n\n"
            # f"  trials={trials}, trial_id={trial_id}\n"
            f"  Method found in case file: {rate_method!r}\n\n"
            "When running multiple trials or a specific trial-id,\n"
            "rate_selection.method must be one of:\n"
            "  - stochastic\n"
            "  - histocastic\n\n"
        )


def normalize_hydra_overrides(overrides: list[str]) -> list[str]:
    """
    Normalize Hydra overrides:
      - Convert comma-separated values to list syntax
        unless already quoted or bracketed.

    NOTE:
    This helper is intentionally NOT applied by default, preserving
    existing CLI behavior exactly.
    """
    normalized = []

    for o in overrides:
        if "=" not in o:
            normalized.append(o)
            continue

        key, val = o.split("=", 1)

        if (
            "," in val
            and not val.startswith("[")
            and not val.endswith("]")
            and not (val.startswith("'") or val.startswith('"'))
        ):
            val = f"[{val}]"

        normalized.append(f"{key}={val}")

    return normalized


def build_hydra_command(
    case_file: Path | None,
    overrides: list[str],
    *,
    trials: int | None,
    trial_jobs: int | None,
    run_jobs: int | None,
    trial_id: int | None,
) -> list[str]:
    """
    Construct subprocess command invoking owl_hydra_run.py.
    """
    package_root = Path(__file__).parents[1]  # src/owlroost
    script = package_root / "hydra" / "owl_hydra_run.py"
    conf_dir = package_root / "conf"

    if not script.exists():
        raise RuntimeError(f"Hydra runner not found: {script}") from None

    if not conf_dir.exists():
        raise RuntimeError(f"Hydra conf directory not found: {conf_dir}") from None

    cmd = [
        sys.executable,
        str(script),
        "--multirun",
        f"--config-path={conf_dir}",
        "--config-name=config",
    ]

    # Inject selected case file
    if case_file:
        cmd.append(f"case.file={case_file}")

    # Trial controls
    if trials is not None:
        cmd.append(f"trial.count={trials}")

    if trial_jobs is not None:
        cmd.append(f"trial.n_jobs={trial_jobs}")

    if trial_id is not None:
        cmd.append(f"trial.id={trial_id}")

    # Run controls (Hydra launcher parallelism)
    if run_jobs is not None:
        cmd.append(f"launcher.n_jobs={run_jobs}")

    # Pass-through Hydra overrides verbatim
    cmd.extend(overrides)

    return cmd


# ---------------------------------------------------------------------
# CLI help
# ---------------------------------------------------------------------


def build_run_help(cmd) -> str:
    conf_dir = Path(__file__).parents[1] / "conf"

    parts = [
        "Usage: roost run [CASE] [OPTIONS] [OVERRIDES...]\n",
        "Run OWL via Hydra.\n",
        "",
        "Parallelism:",
        "  -t, --trials INTEGER          Number of stochastic trials (trial.count)",
        "      --trial-id INTEGER        Run a specific trial id (trial.id)",
        "      --trial-jobs INTEGER      Max concurrent trials per run (trial.n_jobs)",
        "      --run-jobs INTEGER        Max concurrent Hydra runs (launcher.n_jobs)",
        "",
        "Examples:",
        "  roost run Case.toml",
        "  roost run Case.toml -t 100",
        "  roost run Case.toml --trial-id 7",
        "  roost run Case.toml -t 100 --trial-id 7",
        "  roost run Case.toml -t 100 --trial-jobs 8 --run-jobs 4",
        "",
        format_override_help(
            conf_dir,
            groups=helper_groups,
        ),
        format_click_options(cmd),
    ]

    return "\n".join(parts)


# ---------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------


@click.command(
    name="run",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_extra_args=True,
    ),
)
@click.argument("case", required=False)
@click.option(
    "-t",
    "--trials",
    type=int,
    default=None,
    show_default=False,
    help="Number of stochastic trials (trial.count).",
)
@click.option(
    "--trial-id",
    type=int,
    default=None,
    show_default=False,
    help="Run a specific trial id (trial.id).",
)
@click.option(
    "--trial-jobs",
    type=int,
    default=None,
    show_default=False,
    help="Max concurrent trials per run (trial.n_jobs).",
)
@click.option(
    "--run-jobs",
    type=int,
    default=None,
    show_default=False,
    help="Max concurrent Hydra runs (launcher.n_jobs).",
)
@click.pass_context
def cmd_run(
    ctx: click.Context,
    case: str | None,
    trials: int | None,
    trial_id: int | None,
    trial_jobs: int | None,
    run_jobs: int | None,
):
    """
    Run an OWL case via Hydra.
    """

    cwd = Path.cwd()
    files = find_case_files(cwd)

    # ------------------------------------------------------------
    # No argument → show same case list as `roost cases`
    # ------------------------------------------------------------
    if case is None:
        print_case_list(cwd)
        return

    if not files:
        raise click.BadParameter("No .toml case files found.")

    indexed_files = index_case_files(files)

    case_file = resolve_case_selector(case, indexed_files)
    if not case_file:
        raise click.BadParameter(f"No case matching '{case}'")

    rate_method = get_rate_selection_method(case_file)

    validate_rate_method_for_trials(
        rate_method=rate_method,
        trials=trials,
        trial_id=trial_id,
    )

    # Remaining args → Hydra overrides (verbatim pass-through)
    hydra_overrides = ctx.args
    # hydra_overrides = normalize_hydra_overrides(ctx.args)

    logger.debug("Resolved case file: {}", case_file)
    logger.debug("Hydra overrides: {}", hydra_overrides)
    logger.debug("Trials: {}", trials)
    logger.debug("Trial ID: {}", trial_id)
    logger.debug("Trial jobs: {}", trial_jobs)
    logger.debug("Run jobs: {}", run_jobs)

    # Build subprocess command
    cmd = build_hydra_command(
        case_file,
        hydra_overrides,
        trials=trials,
        trial_jobs=trial_jobs,
        run_jobs=run_jobs,
        trial_id=trial_id,
    )

    logger.debug("Executing Hydra:")
    logger.debug("  {}", " ".join(cmd))

    # Execute
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Hydra run failed (exit {e.returncode})") from None


cmd_run.get_help = lambda ctx: build_run_help(cmd_run)
