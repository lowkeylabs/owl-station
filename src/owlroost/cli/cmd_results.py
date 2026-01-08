from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
import yaml

from owlroost.cli.utils import format_optimization_summary, format_rates_summary

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

RESULTS_DIR = Path("results")
IGNORE_PREFIXES = ("Hydra", "hydra")

# ---------------------------------------------------------------------
# Data models (terminology aligned with Hydra)
# ---------------------------------------------------------------------


@dataclass
class Trial:
    path: Path
    name: str


@dataclass
class Run:
    path: Path
    name: str
    overrides: list[str]
    trials: list[Trial]


@dataclass
class Experiment:
    type: Literal["single", "multi"]
    runs: list[Run]


@dataclass
class Case:
    name: str
    path: Path
    experiments: list[Experiment]


@dataclass(frozen=True)
class FileDescriptor:
    suffix: str
    kind: Literal["INPUT", "OUTPUT"]
    description: str


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------

FILE_DESCRIPTORS = [
    FileDescriptor("_original.toml", "INPUT", "Original input TOML file"),
    FileDescriptor("_effective.toml", "INPUT", "Modified input TOML file, with overrides"),
    FileDescriptor("_rates.xlsx", "INPUT", "Modified rates just prior to solving"),
    FileDescriptor("_original.xlsx", "INPUT", "Original HFP xlsx file"),
    FileDescriptor("_effective.xlsx", "INPUT", "Modified HFP xlsx file, with overrides"),
    FileDescriptor("_metrics.json", "OUTPUT", "OWL top-level metrics as JSON"),
    FileDescriptor("_summary.json", "OUTPUT", "OWL top-level metrics as text"),
    FileDescriptor("_results.xlsx", "OUTPUT", "OWL output workbook with full results"),
]


def describe_file(name: str) -> tuple[str | None, str | None]:
    """
    Return (kind, description) for a filename, or (None, None).
    """
    for d in FILE_DESCRIPTORS:
        if name.endswith(d.suffix):
            return d.kind, d.description
    return None, None


def format_k(value) -> str:
    if value is None:
        return "—"
    try:
        return f"${round(value / 1000):,}K"
    except Exception:
        return "—"


def strip_override_prefix(override: str) -> str:
    if "." in override:
        return override.split(".", 1)[1]
    return override


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


@click.command(name="results")
@click.argument("case", required=False)
@click.argument("run_id", required=False, type=int)
@click.option("--diff", is_flag=True)
@click.option("--diff-project", is_flag=True)
@click.option("--metrics", is_flag=True)
@click.option("--summary", is_flag=True)
@click.option("--original", is_flag=True)
@click.option("--effective", is_flag=True)
@click.option("--nominal", is_flag=True)
@click.option("--files", is_flag=True)
def cmd_results(
    case,
    run_id,
    diff,
    diff_project,
    metrics,
    summary,
    original,
    effective,
    nominal,
    files,
):
    if diff and diff_project:
        raise click.ClickException("Use only one diff mode")

    value_mode = "nominal" if nominal else "real"

    if not RESULTS_DIR.exists():
        click.echo(f"Results directory not found: {RESULTS_DIR}")
        click.echo("Try running a case!")
        return

    cases = discover_cases(RESULTS_DIR)
    if not cases:
        click.echo("No results found.")
        click.echo("Try running a case!")
        return

    if case is None:
        render_case_summary(cases)
        return

    selected = resolve_case(case, cases)

    if run_id is None:
        render_case_breakdown(
            selected,
            diff_mode="original" if diff else "project" if diff_project else None,
            value_mode=value_mode,
        )
        return

    trials = flatten_trials(selected)

    if run_id < 0 or run_id >= len(trials):
        raise click.ClickException("Invalid run ID")

    trial = trials[run_id]

    if summary:
        render_summary(trial.path)
    elif original:
        render_original_toml(trial.path)
    elif effective:
        render_effective_toml(trial.path)
    elif files:
        render_files(trial.path)
    else:
        render_metrics(trial.path)


# ---------------------------------------------------------------------
# Discovery logic
# ---------------------------------------------------------------------


def discover_cases(results_dir: Path) -> list[Case]:
    return [
        Case(
            name=d.name,
            path=d,
            experiments=discover_experiments(d),
        )
        for d in sorted(results_dir.iterdir())
        if d.is_dir()
    ]


def discover_experiments(case_dir: Path) -> list[Experiment]:
    experiments: list[Experiment] = []

    for date_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        for time_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            runs: list[Run] = []

            run_dirs = sorted(
                p for p in time_dir.iterdir() if p.is_dir() and p.name.startswith("run_")
            )

            for run_dir in run_dirs:
                overrides = extract_run_overrides(run_dir / "hydra_meta.yaml")
                trials: list[Trial] = []

                trials_dir = run_dir / "trials"
                if trials_dir.exists():
                    for td in sorted(p for p in trials_dir.iterdir() if p.is_dir()):
                        trials.append(Trial(path=td, name=td.name))
                else:
                    # legacy single-run case
                    trials.append(Trial(path=run_dir, name=run_dir.name))

                runs.append(
                    Run(
                        path=run_dir,
                        name=run_dir.name,
                        overrides=overrides,
                        trials=trials,
                    )
                )

            if runs:
                experiments.append(
                    Experiment(
                        type="multi" if (time_dir / "multirun.yaml").exists() else "single",
                        runs=runs,
                    )
                )

    return experiments


# ---------------------------------------------------------------------
# Override extraction
# ---------------------------------------------------------------------


def extract_run_overrides(meta_path: Path) -> list[str]:
    if not meta_path.exists():
        return []

    data = yaml.safe_load(meta_path.read_text()) or {}
    return [
        strip_override_prefix(o)
        for o in data.get("overrides", [])
        if isinstance(o, str) and not o.startswith("case.file=")
    ]


# ---------------------------------------------------------------------
# TOML / metrics loading
# ---------------------------------------------------------------------


def load_effective_toml(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_effective.toml"), None)
    return tomllib.load(p.open("rb")) if p else None


def load_original_toml(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_original.toml"), None)
    return tomllib.load(p.open("rb")) if p else None


def load_metrics(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_metrics.json"), None)
    return json.load(p.open()) if p else None


# ---------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------


def flatten_trials(case: Case) -> list[Trial]:
    return [trial for exp in case.experiments for run in exp.runs for trial in run.trials]


def load_case_original_toml(case: Case) -> dict | None:
    """
    Load a representative *_original.toml for a case.
    Uses run_0/trials/0000 when available.
    """
    for exp in case.experiments:
        for run in exp.runs:
            for trial in run.trials:
                p = next(trial.path.glob("*_original.toml"), None)
                if p:
                    try:
                        return tomllib.load(p.open("rb"))
                    except Exception:
                        return None
    return None


def render_case_summary(cases: list[Case]):
    # -------------------------
    # Column widths
    # -------------------------
    w_id = 3
    w_case = 20
    w_exp = 5
    w_run = 5
    w_trial = 6
    w_opt = 30
    w_rates = 30

    # -------------------------
    # Header
    # -------------------------
    click.echo(
        f"{'ID':<{w_id}} "
        f"{'CASE':<{w_case}} "
        f"{'EXPS':<{w_exp}} "
        f"{'RUNS':<{w_run}} "
        f"{'TRIALS':<{w_trial}} "
        f"{'OPTIMIZATION':<{w_opt}} "
        f"{'RATES':<{w_rates}}"
    )

    click.echo(
        "-"
        * (
            w_id + w_case + w_exp + w_run + w_trial + w_opt + w_rates + 6  # spaces between columns
        )
    )

    # -------------------------
    # Rows
    # -------------------------
    for i, case in enumerate(cases):
        exp_count = len(case.experiments)
        run_count = sum(len(e.runs) for e in case.experiments)
        trial_count = sum(len(r.trials) for e in case.experiments for r in e.runs)

        original = load_case_original_toml(case) or {}

        opt_display = format_optimization_summary(original)
        rates_display = format_rates_summary(original)

        click.echo(
            f"{i:<{w_id}} "
            f"{case.name:<{w_case}} "
            f"{exp_count:<{w_exp}} "
            f"{run_count:<{w_run}} "
            f"{trial_count:<{w_trial}} "
            f"{opt_display:<{w_opt}} "
            f"{rates_display:<{w_rates}}"
        )


def render_metrics(run_dir: Path):
    data = load_metrics(run_dir)
    if not data:
        click.echo("(no metrics found)")
        return
    click.echo(json.dumps(data, indent=2, sort_keys=False))


def render_case_breakdown(case: Case, diff_mode: str | None, value_mode: str):
    """Render case breakdown"""

    render_case_summary([case])
    click.echo("")

    # Column widths
    w_exp = 3
    w_id = 3
    w_run = 7
    w_trial = 6
    w_yearly = 9
    w_net = 9
    w_beq = 9

    # -------------------------
    # Header
    # -------------------------
    header1 = (
        f"{'':>{w_exp}} {'':>{w_id}} "
        f"{'':<{w_run}} {'':<{w_trial}} "
        f"{'Per Year':>{w_yearly}} {'Total Net':>{w_net}} {'Bequest':>{w_beq}}"
    )
    header2 = (
        f"{'ID':>{w_id}} {'EXP':>{w_exp}} "
        f"{'Run':<{w_run}} {'Trial':<{w_trial}} "
        f"({value_mode} $K) ({value_mode} $K) ({value_mode} $K)  Overrides"
    )

    click.echo(header1)
    click.echo(header2)
    click.echo("-" * max(len(header1), len(header2)))

    # -------------------------
    # Rows
    # -------------------------
    row_id = 0
    for exp_id, exp in enumerate(case.experiments):
        for run in exp.runs:
            for trial in run.trials:
                metrics = load_metrics(trial.path) or {}

                yearly = format_k(metrics.get("net_spending_for_plan_year_0"))
                net = format_k(metrics.get(f"total_net_spending_{value_mode}"))
                beq = format_k(metrics.get(f"total_final_bequest_{value_mode}"))
                overrides = ", ".join(run.overrides) if run.overrides else "—"

                click.echo(
                    f"{row_id:>{w_id}} "
                    f"{exp_id:>{w_exp}} "
                    f"{run.name:<{w_run}} "
                    f"{trial.name:<{w_trial}} "
                    f"{yearly:>{w_yearly}} "
                    f"{net:>{w_net}} "
                    f"{beq:>{w_beq}}   "
                    f"{overrides}"
                )

                row_id += 1


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------


def render_summary(run_dir: Path):
    p = next(run_dir.glob("*_summary.json"), None)
    if not p:
        click.echo("(no summary found)")
        return

    data = json.load(p.open())
    click.echo(json.dumps(data, indent=2, sort_keys=False))


def render_original_toml(run_dir: Path):
    p = next(run_dir.glob("*_original.toml"), None)
    if not p:
        click.echo("(no original TOML found)")
        return

    click.echo(p.read_text(encoding="utf-8"))


def render_effective_toml(run_dir: Path):
    p = next(run_dir.glob("*_effective.toml"), None)
    if not p:
        click.echo("(no effective TOML found)")
        return

    click.echo(p.read_text(encoding="utf-8"))


def resolve_case(token: str, cases: list[Case]) -> Case:
    if token.isdigit():
        return cases[int(token)]
    for c in cases:
        if c.name == token:
            return c
    raise click.ClickException(f"Case not found: {token}")


def render_files(run_dir: Path):
    """
    List files in a trial directory.
    """
    if not run_dir.exists():
        click.echo("(trial directory not found)")
        return

    files = sorted(p for p in run_dir.iterdir() if p.is_file())

    if not files:
        click.echo("(no files found)")
        return

    inputs: list[tuple[str, str]] = []
    outputs: list[tuple[str, str]] = []
    others: list[str] = []

    for p in files:
        kind, desc = describe_file(p.name)

        if kind == "INPUT":
            inputs.append((p.name, desc))
        elif kind == "OUTPUT":
            outputs.append((p.name, desc))
        else:
            others.append(p.name)

    # Sort alphabetically within groups
    inputs.sort()
    outputs.sort()
    others.sort()

    # -------------------------
    # Display
    # -------------------------

    if inputs:
        click.echo("INPUT FILES:")
        for name, desc in inputs:
            click.echo(f"  {name:<35} [{desc}]")

    if outputs:
        click.echo("\nOUTPUT FILES:")
        for name, desc in outputs:
            click.echo(f"  {name:<35} [{desc}]")

    if others:
        click.echo("\nOTHER FILES:")
        for name in others:
            click.echo(f"  {name}")
