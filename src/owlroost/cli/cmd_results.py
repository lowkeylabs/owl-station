from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
import yaml
from loguru import logger

from owlroost.cli.utils import format_optimization_summary, format_rates_summary

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

RESULTS_DIR = Path("results")
IGNORE_PREFIXES = ("Hydra", "hydra")

# ---------------------------------------------------------------------
# Data models
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
    return override.split(".", 1)[1] if "." in override else override


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


@click.command(name="results")
@click.argument("case", required=False)
@click.argument("run_id", required=False, type=int)
@click.argument("trial_id", required=False, type=int)
@click.option("--diff", is_flag=True)
@click.option("--diff-project", is_flag=True)
@click.option("--metrics", is_flag=True)
@click.option("--summary", is_flag=True)
@click.option("--original", is_flag=True)
@click.option("--effective", is_flag=True)
@click.option("--nominal", is_flag=True)
@click.option("--files", is_flag=True)
@click.option("--delete", help="Comma-separated list of IDs to delete")
def cmd_results(
    case,
    run_id,
    trial_id,
    diff,
    diff_project,
    metrics,
    summary,
    original,
    effective,
    nominal,
    files,
    delete,
):
    if diff and diff_project:
        raise click.ClickException("Use only one diff mode")

    value_mode = "nominal" if nominal else "real"

    if not RESULTS_DIR.exists():
        click.echo(f"Results directory not found: {RESULTS_DIR}")
        return

    cases = discover_cases(RESULTS_DIR)
    if not cases:
        click.echo("No results found.")
        return

    # -------------------------------------------------
    # CASE SUMMARY (no case selected)
    # -------------------------------------------------
    if case is None:
        if delete:
            delete_ids = parse_id_list(delete)
            bad = [i for i in delete_ids if i < 0 or i >= len(cases)]
            if bad:
                raise click.ClickException(f"Invalid case IDs: {bad}")

            click.echo("Deleting cases:")
            for i in delete_ids:
                click.echo(f"  [{i}] {cases[i].path}")
                import shutil

                shutil.rmtree(cases[i].path, ignore_errors=True)
            return

        render_case_summary(cases)
        return

    selected = resolve_case(case, cases)
    runs = flatten_runs(selected)

    # -------------------------------------------------
    # RUN SUMMARY (case selected, no run_id)
    # -------------------------------------------------
    if run_id is None:
        if delete:
            delete_ids = parse_id_list(delete)
            bad = [i for i in delete_ids if i < 0 or i >= len(runs)]
            if bad:
                raise click.ClickException(f"Invalid run IDs: {bad}")

            click.echo("Deleting runs:")
            for i in delete_ids:
                click.echo(f"  [{i}] {runs[i].path}")
                import shutil

                shutil.rmtree(runs[i].path, ignore_errors=True)
            return

        render_case_summary([selected])
        render_run_summary(selected, value_mode)
        return

    # -------------------------------------------------
    # RUN DETAIL (case + run_id)
    # -------------------------------------------------
    if delete:
        raise click.ClickException("--delete not valid when viewing trials (delete the run)")

    if run_id < 0 or run_id >= len(runs):
        raise click.ClickException("Invalid run ID")

    run = runs[run_id]
    trials = run.trials

    # -------------------------------------------------
    # TRIAL TABLE (case + run_id, no trial_id)
    # -------------------------------------------------
    if trial_id is None and len(trials) > 1:
        exp_id = next(i for i, e in enumerate(selected.experiments) if run in e.runs)
        render_case_summary([selected])
        render_run_summary(selected, value_mode, selected_run=run)
        render_run_trials(selected, run, exp_id, value_mode)
        return
    else:
        trial_id = 0

    # -------------------------------------------------
    # SINGLE TRIAL DETAIL (case + run_id + trial_id)
    # -------------------------------------------------
    if trial_id < 0 or trial_id >= len(trials):
        raise click.ClickException("Invalid trial ID")

    trial = trials[trial_id]

    # Context headers (lightweight, consistent)

    exp_id = next(i for i, e in enumerate(selected.experiments) if run in e.runs)
    trial_id = run.trials.index(trial)

    render_case_summary([selected])

    render_run_summary(selected, value_mode, selected_run=run)

    if len(trials) > 1:
        render_run_trials(selected, run, exp_id, value_mode, selected_trial=trial)

    # render_single_trial_summary(selected,run,trial,exp_id,trial_id,value_mode )

    # Leaf default behavior
    if summary:
        render_summary(trial.path)
    if original:
        render_original_toml(trial.path)
    if effective:
        render_effective_toml(trial.path)
    if files:
        render_files(trial.path)
    if metrics:
        render_metrics(trial.path)


# ---------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------


def discover_cases(results_dir: Path) -> list[Case]:
    return [
        Case(d.name, d, discover_experiments(d))
        for d in sorted(results_dir.iterdir())
        if d.is_dir()
    ]


def discover_experiments(case_dir: Path) -> list[Experiment]:
    experiments: list[Experiment] = []

    for date_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        for time_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            runs: list[Run] = []

            for run_dir in sorted(
                p for p in time_dir.iterdir() if p.is_dir() and p.name.startswith("run_")
            ):
                overrides = extract_run_overrides(run_dir / "hydra_meta.yaml")
                trials_dir = run_dir / "trials"
                trials = (
                    [Trial(p, p.name) for p in sorted(trials_dir.iterdir())]
                    if trials_dir.exists()
                    else [Trial(run_dir, run_dir.name)]
                )
                runs.append(Run(run_dir, run_dir.name, overrides, trials))

            if runs:
                experiments.append(
                    Experiment(
                        "multi" if (time_dir / "multirun.yaml").exists() else "single",
                        runs,
                    )
                )

    return experiments


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------


def parse_id_list(s: str) -> list[int]:
    ids: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = map(int, part.split("-", 1))
            ids.update(range(a, b + 1))
        else:
            ids.add(int(part))
    return sorted(ids)


def extract_run_overrides(meta_path: Path) -> list[str]:
    if not meta_path.exists():
        return []
    data = yaml.safe_load(meta_path.read_text()) or {}
    return [
        strip_override_prefix(o)
        for o in data.get("overrides", [])
        if isinstance(o, str) and not o.startswith("case.file=")
    ]


def flatten_runs(case: Case) -> list[Run]:
    return [run for exp in case.experiments for run in exp.runs]


def flatten_trials_for_run(run: Run) -> list[Trial]:
    return run.trials


def load_metrics(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_metrics.json"), None)
    return json.load(p.open()) if p else None


def load_case_original_toml(case: Case) -> dict | None:
    for exp in case.experiments:
        for run in exp.runs:
            for t in run.trials:
                p = next(t.path.glob("*_original.toml"), None)
                if p:
                    return tomllib.load(p.open("rb"))
    return None


def normalize_overrides_for_display(overrides) -> str:
    if not overrides:
        return "—"

    cleaned = []
    for o in overrides:
        if not isinstance(o, str):
            continue

        # Remove Hydra escaping for spaces
        o = o.replace("\\ ", " ")

        # Drop overrides with key == "count"
        key = o.split("=", 1)[0]
        if key == "count":
            continue

        cleaned.append(o)

    return ", ".join(cleaned) if cleaned else "—"


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------


def render_divider():
    click.echo("-" * 100)


def render_case_summary(cases: list[Case]):
    w_id, w_exp, w_run, w_trial, w_case, w_opt, w_rates = 3, 4, 5, 6, 20, 30, 30

    click.echo("CASE SUMMARY")
    render_divider()
    click.echo(
        f"{'ID':>{w_id}} {'Exps':>{w_exp}} "
        f"{'Runs':<{w_run}} {'Trials':>{w_trial}}  "
        f"{'Case Name':<{w_case}} "
        f"{'Optimization':<{w_opt}} {'Rates':<{w_rates}}"
    )
    render_divider()

    for i, case in enumerate(cases):
        orig = load_case_original_toml(case) or {}
        click.echo(
            f"{i:>{w_id}} "
            f"{len(case.experiments):>{w_exp}} "
            f"{sum(len(e.runs) for e in case.experiments):<{w_run}} "
            f"{sum(len(r.trials) for e in case.experiments for r in e.runs):>{w_trial}}  "
            f"{case.name:<{w_case}} "
            f"{format_optimization_summary(orig):<{w_opt}} "
            f"{format_rates_summary(orig):<{w_rates}}"
        )


def render_run_summary(
    case: Case,
    value_mode: str,
    selected_run: Run | None = None,
):
    """
    Render a summary of runs for a selected case.
    If selected_run is provided, show only that run.
    Averages numeric metrics across all trials in each run.
    """

    # -------------------------
    # Column widths
    # -------------------------
    w_id = 3
    w_exp = 4
    w_run = 5
    w_trial = 6
    w_y = 9
    w_n = 9
    w_b = 9

    # -------------------------
    # Header
    # -------------------------
    click.echo("")
    click.echo("RUN SUMMARY")
    render_divider()
    click.echo(
        f"{'':>{w_id}} "
        f"{'':>{w_exp}} "
        f"{'':<{w_run}} "
        f"{'':>{w_trial}} "
        f"{'Net/Yr':>{w_y}} "
        f"{'Total Net':>{w_n}} "
        f"{'Bequest':>{w_b}} "
        f""
    )
    value_display = f"({value_mode} $K)"
    click.echo(
        f"{'ID':>{w_id}} {'Exp':>{w_exp}} {'Run':<{w_run}} {'Trials':>{w_trial}} "
        f"{value_display:>{w_y}} {value_display:>{w_n}} {value_display:>{w_b}}   Overrides"
    )
    render_divider()

    # -------------------------
    # Rows
    # -------------------------
    run_id = 0
    for exp_id, exp in enumerate(case.experiments):
        for run in exp.runs:
            if selected_run is not None and run is not selected_run:
                run_id += 1
                continue

            # -------------------------
            # Aggregate metrics
            # -------------------------
            yearly_vals = []
            net_vals = []
            beq_vals = []

            for t in run.trials:
                m = load_metrics(t.path) or {}

                if (v := m.get("net_spending_for_plan_year_0")) is not None:
                    yearly_vals.append(v)

                if (v := m.get(f"total_net_spending_{value_mode}")) is not None:
                    net_vals.append(v)

                if (v := m.get(f"total_final_bequest_{value_mode}")) is not None:
                    beq_vals.append(v)

            def avg(vals):
                return sum(vals) / len(vals) if vals else None

            yearly = format_k(avg(yearly_vals))
            net = format_k(avg(net_vals))
            beq = format_k(avg(beq_vals))

            overrides = normalize_overrides_for_display(run.overrides)

            click.echo(
                f"{run_id:>{w_id}} "
                f"{exp_id:>{w_exp}} "
                f"{run.name:<{w_run}} "
                f"{len(run.trials):>{w_trial}} "
                f"{yearly:>{w_y}} "
                f"{net:>{w_n}} "
                f"{beq:>{w_b}}   "
                f"{overrides}"
            )

            run_id += 1


def render_run_trials(
    case: Case,
    run: Run,
    exp_id: int,
    value_mode: str,
    selected_trial: Trial | None = None,
):
    click.echo("")
    click.echo("TRIAL SUMMARY")

    w_id, w_exp, w_run, w_trial, w_y, w_n, w_b = 3, 4, 5, 6, 9, 9, 9

    render_divider()
    click.echo(
        f"{'':>{w_id}} "
        f"{'':>{w_exp}} "
        f"{'':<{w_run}} "
        f"{'':>{w_trial}} "
        f"{'Net/Yr':>{w_y}} "
        f"{'Total Net':>{w_n}} "
        f"{'Bequest':>{w_b}} "
        f""
    )
    value_display = f"({value_mode} $K)"
    click.echo(
        f"{'ID':>{w_id}} {'Exp':>{w_exp}} {'Run':<{w_run}} {'Trials':>{w_trial}} "
        f"{value_display:>{w_y}} {value_display:>{w_n}} {value_display:>{w_b}}   Overrides"
    )
    render_divider()

    for i, t in enumerate(run.trials):
        # 🔹 Filter if a specific trial is selected
        if selected_trial is not None and t is not selected_trial:
            continue

        m = load_metrics(t.path) or {}

        click.echo(
            f"{i:>{w_id}} {exp_id:>{w_exp}} {run.name:<{w_run}} {t.name:>{w_trial}} "
            f"{format_k(m.get('net_spending_for_plan_year_0')):>{w_y}} "
            f"{format_k(m.get(f'total_net_spending_{value_mode}')):>{w_n}} "
            f"{format_k(m.get(f'total_final_bequest_{value_mode}')):>{w_b}}   "
            f"{normalize_overrides_for_display(run.overrides)}"
        )


def render_metrics(run_dir: Path):
    data = load_metrics(run_dir)
    click.echo(json.dumps(data, indent=2) if data else "(no metrics found)")


def render_summary(run_dir: Path):
    p = next(run_dir.glob("*_summary.json"), None)
    click.echo(p.read_text() if p else "(no summary found)")


def render_original_toml(run_dir: Path):
    p = next(run_dir.glob("*_original.toml"), None)
    click.echo(p.read_text() if p else "(no original TOML found)")


def render_effective_toml(run_dir: Path):
    p = next(run_dir.glob("*_effective.toml"), None)
    click.echo(p.read_text() if p else "(no effective TOML found)")


def resolve_case(token: str, cases: list[Case]) -> Case:
    if token.isdigit():
        return cases[int(token)]
    for c in cases:
        if c.name == token:
            return c
    raise click.ClickException(f"Case not found: {token}")


def render_files(run_dir: Path):
    """List files in a trial directory."""
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

    click.echo("")
    click.echo("FILES")
    render_divider()
    click.echo(f"Path: {run_dir}")
    render_divider()
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


def render_single_trial_summary(
    case: Case,
    run: Run,
    trial: Trial,
    exp_id: int,
    trial_id: int,
    value_mode: str,
):
    """
    Render a single trial summary and default to metrics output.
    """

    # -------------------------
    # Context header
    # -------------------------
    if 0:
        click.echo("RUN")
        render_divider()
        click.echo(f"EXP {exp_id} | {run.name} | {len(run.trials)} trials")

        overrides = normalize_overrides_for_display(run.overrides)
        click.echo(f"Overrides: {overrides}")
        click.echo("")

    logger.debug(f"{case} {run} {trial} {exp_id} {trial_id} {value_mode}")

    # -------------------------
    # Trial summary
    # -------------------------
    click.echo("")
    click.echo("METRICS")
    render_divider()

    render_metrics(trial.path)
