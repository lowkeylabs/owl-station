from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
import yaml

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


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------


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
):
    if diff and diff_project:
        raise click.ClickException("Use only one diff mode")

    value_mode = "nominal" if nominal else "real"

    cases = discover_cases(RESULTS_DIR)
    if not cases:
        click.echo("No cases found.")
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


def render_case_summary(cases: list[Case]):
    click.echo(f"{'ID':<3} {'CASE':<25} {'EXPS':<5} {'RUNS':<5} {'TRIALS':<6}")
    click.echo("-" * 50)

    for i, case in enumerate(cases):
        exp_count = len(case.experiments)
        run_count = sum(len(e.runs) for e in case.experiments)
        trial_count = sum(len(r.trials) for e in case.experiments for r in e.runs)

        click.echo(f"{i:<3} {case.name:<25} {exp_count:<5} {run_count:<5} {trial_count:<6}")


def render_metrics(run_dir: Path):
    data = load_metrics(run_dir)
    if not data:
        click.echo("(no metrics found)")
        return
    click.echo(json.dumps(data, indent=2, sort_keys=False))


def render_case_breakdown(case: Case, diff_mode: str | None, value_mode: str):
    click.echo(f"\nCase: {case.name}\n")

    # Column widths
    w_exp = 3
    w_id = 3
    w_run = 7
    w_trial = 6
    w_net = 9
    w_beq = 9

    # -------------------------
    # Header
    # -------------------------
    header1 = (
        f"{'':>{w_exp}} {'':>{w_id}} "
        f"{'':<{w_run}} {'':<{w_trial}} "
        f"{'NetSpend':>{w_net}} {'Bequest':>{w_beq}}   Overrides"
    )
    header2 = (
        f"{'EXP':>{w_exp}} {'ID':>{w_id}} "
        f"{'Run':<{w_run}} {'Trial':<{w_trial}} "
        f"({value_mode} $K) ({value_mode} $K)"
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

                net = format_k(metrics.get(f"total_net_spending_{value_mode}"))
                beq = format_k(metrics.get(f"total_final_bequest_{value_mode}"))
                overrides = ", ".join(run.overrides) if run.overrides else "—"

                click.echo(
                    f"{exp_id:>{w_exp}} "
                    f"{row_id:>{w_id}} "
                    f"{run.name:<{w_run}} "
                    f"{trial.name:<{w_trial}} "
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
