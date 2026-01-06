# src/owlroost/cli/cmd_run.py

import subprocess
import sys
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
helper_groups = ["solver", "optimization", "longevity"]

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


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

    # Pass-through Hydra overrides verbatim
    cmd.extend(overrides)

    return cmd


# ---------------------------------------------------------------------
# CLI help
# ---------------------------------------------------------------------


def build_run_help(cmd) -> str:
    conf_dir = Path(__file__).parents[1] / "conf"

    parts = [
        "Usage: roost run [CASE] [OVERRIDES...]\n",
        "Run OWL via Hydra.\n",
        "Examples:",
        "  roost run",
        "  roost run base.toml solver.netSpending=65.7\n",
        format_override_help(
            conf_dir,
            groups=["solver", "optimization", "longevity"],
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
@click.pass_context
def cmd_run(ctx: click.Context, case: str | None):
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

    # Remaining args → Hydra overrides (verbatim pass-through)
    hydra_overrides = ctx.args
    # hydra_overrides = normalize_hydra_overrides(ctx.args)

    logger.debug("Resolved case file: {}", case_file)
    logger.debug("Hydra overrides: {}", hydra_overrides)

    # Build subprocess command
    cmd = build_hydra_command(case_file, hydra_overrides)

    logger.debug("Executing Hydra:")
    logger.debug("  {}", " ".join(cmd))

    # Execute
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Hydra run failed (exit {e.returncode})") from None


cmd_run.get_help = lambda ctx: build_run_help(cmd_run)
