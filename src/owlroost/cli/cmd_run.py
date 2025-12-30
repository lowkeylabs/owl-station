# src/owlroost/cli/cmd_run.py

import subprocess
import sys
from pathlib import Path

import click
from loguru import logger

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def find_case_files(directory: Path) -> list[Path]:
    """Return sorted list of .toml case files."""
    return sorted(directory.glob("*.toml"))


def resolve_case_arg(arg: str | None, cases: list[Path]) -> Path | None:
    """
    Resolve a case argument which may be:
      - None          → no case specified
      - filename      → exact match
      - integer index → positional case selection
    """
    if arg is None:
        return None

    # Numeric ID
    if arg.isdigit():
        idx = int(arg)
        try:
            return cases[idx]
        except IndexError:
            raise click.BadParameter(f"No case with id {idx}") from None

    # Filename
    path = Path(arg)
    if path.suffix == "":
        path = path.with_suffix(".toml")

    if not path.exists():
        raise click.BadParameter(f"Case file '{path}' does not exist") from None

    return path.resolve()


def list_cases(cases: list[Path]) -> None:
    """Print indexed case list."""
    if not cases:
        click.echo("No .toml case files found.")
        return

    click.echo("Available cases:")
    for i, case in enumerate(cases):
        click.echo(f"  [{i}] {case.name}")


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
        f"--config-path={conf_dir}",
        "--config-name=config",
    ]

    if case_file:
        cmd.append(f"case.file={case_file}")

    cmd.extend(overrides)

    return cmd


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
    Run OWL via Hydra.

    Usage:
      roost run              → list available cases
      roost run <case.toml>  → run a specific case
      roost run <id>         → run case by index

    Any additional arguments are forwarded directly to Hydra.
    """

    cwd = Path.cwd()
    cases = find_case_files(cwd)

    # No argument → list cases
    if case is None:
        list_cases(cases)
        return

    # Resolve case argument
    case_file = resolve_case_arg(case, cases)

    # Remaining args → Hydra overrides
    hydra_overrides = ctx.args

    logger.debug("Resolved case: {}", case_file)
    logger.debug("Hydra overrides: {}", hydra_overrides)

    # Build subprocess command
    cmd = build_hydra_command(case_file, hydra_overrides)

    logger.info("Executing Hydra:")
    logger.info("  {}", " ".join(cmd))

    # Execute
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise click.ClickException(f"Hydra run failed (exit {e.returncode})") from None
