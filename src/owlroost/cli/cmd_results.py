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

W_ID = 3
W_EXP = 4
W_RUN = 7
W_TRIAL = 6
W_CASE = 20
W_OPT = 30
W_RATES = 30
W_YEAR = 9
W_NET = 9
W_BEQ = 9

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
    click.echo("CASE SUMMARY")
    render_divider()
    click.echo(
        f"{'ID':>{W_ID}} {'Exps':>{W_EXP}} "
        f"{'Runs':<{W_RUN}} {'Trials':>{W_TRIAL}}  "
        f"{'Case Name':<{W_CASE}} "
        f"{'Optimization':<{W_OPT}} {'Rates':<{W_RATES}}"
    )
    render_divider()

    for i, case in enumerate(cases):
        orig = load_case_original_toml(case) or {}
        click.echo(
            f"{i:>{W_ID}} "
            f"{len(case.experiments):>{W_EXP}} "
            f"{sum(len(e.runs) for e in case.experiments):<{W_RUN}} "
            f"{sum(len(r.trials) for e in case.experiments for r in e.runs):>{W_TRIAL}}  "
            f"{case.name:<{W_CASE}} "
            f"{format_optimization_summary(orig):<{W_OPT}} "
            f"{format_rates_summary(orig):<{W_RATES}}"
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

    Sorting rules:
      1. Determine an effective objective per run:
         - If overrides contain maxBequest or maxSpending → use that
         - Otherwise use case.optimization.objective
      2. Group rows by effective objective:
         - maxBequest first, sorted by bequest DESC
         - maxSpending next, sorted by net spending DESC
         - everything else last, stable order
    """

    # -------------------------
    # Header
    # -------------------------
    click.echo("")
    click.echo("RUN SUMMARY")
    render_divider()
    click.echo(
        f"{'':>{W_ID}} "
        f"{'':>{W_EXP}} "
        f"{'':<{W_RUN}} "
        f"{'':>{W_TRIAL}} "
        f"{'Net/Yr':>{W_YEAR}} "
        f"{'Total Net':>{W_NET}} "
        f"{'Bequest':>{W_BEQ}} "
        f""
    )
    value_display = f"({value_mode} $K)"
    click.echo(
        f"{'ID':>{W_ID}} {'Exp':>{W_EXP}} {'Run':<{W_RUN}} {'Trials':>{W_TRIAL}} "
        f"{value_display:>{W_YEAR}} {value_display:>{W_NET}} {value_display:>{W_BEQ}}   Overrides"
    )
    render_divider()

    # -------------------------
    # Collect rows (no output)
    # -------------------------
    rows = []
    run_id = 0
    case_toml = load_case_original_toml(case)
    case_objective = case_toml.get("optimization_parameters", {}).get("objective", "maxBequest")

    for exp_id, exp in enumerate(case.experiments):
        for run in exp.runs:
            if selected_run is not None and run is not selected_run:
                run_id += 1
                continue

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

            yearly_avg = avg(yearly_vals)
            net_avg = avg(net_vals)
            beq_avg = avg(beq_vals)

            overrides = run.overrides or []

            if any("maxBequest" in o for o in overrides):
                effective_objective = "maxBequest"
            elif any("maxSpending" in o for o in overrides):
                effective_objective = "maxSpending"
            else:
                effective_objective = case_objective

            rows.append(
                {
                    "run_id": run_id,
                    "exp_id": exp_id,
                    "run": run,
                    "trials": len(run.trials),
                    "yearly": yearly_avg,
                    "net": net_avg,
                    "beq": beq_avg,
                    "objective": effective_objective,
                    "overrides": normalize_overrides_for_display(run.overrides),
                }
            )

            run_id += 1

    # -------------------------
    # Sorting
    # -------------------------
    def sort_key(row):
        obj = row["objective"]

        if obj == "maxBequest":
            return (0, -(row["beq"] or float("-inf")))
        if obj == "maxSpending":
            return (1, -(row["net"] or float("-inf")))

        return (2, row["run_id"])  # stable fallback

    rows.sort(key=sort_key)

    # -------------------------
    # Render rows
    # -------------------------
    for row in rows:
        click.echo(
            f"{row['run_id']:>{W_ID}} "
            f"{row['exp_id']:>{W_EXP}} "
            f"{row['run'].name:<{W_RUN}} "
            f"{row['trials']:>{W_TRIAL}} "
            f"{format_k(row['yearly']):>{W_YEAR}} "
            f"{format_k(row['net']):>{W_NET}} "
            f"{format_k(row['beq']):>{W_BEQ}}   "
            f"{row['overrides']}"
        )


def render_run_trials(
    case: Case,
    run: Run,
    exp_id: int,
    value_mode: str,
    selected_trial: Trial | None = None,
):
    click.echo("")
    click.echo("TRIAL SUMMARY")

    render_divider()
    click.echo(
        f"{'':>{W_ID}} "
        f"{'':>{W_EXP}} "
        f"{'':<{W_RUN}} "
        f"{'':>{W_TRIAL}} "
        f"{'Net/Yr':>{W_YEAR}} "
        f"{'Total Net':>{W_NET}} "
        f"{'Bequest':>{W_BEQ}} "
        f""
    )
    value_display = f"({value_mode} $K)"
    click.echo(
        f"{'ID':>{W_ID}} {'Exp':>{W_EXP}} {'Run':<{W_RUN}} {'Trials':>{W_TRIAL}} "
        f"{value_display:>{W_YEAR}} {value_display:>{W_NET}} {value_display:>{W_BEQ}}   Overrides"
    )
    render_divider()

    for i, t in enumerate(run.trials):
        # 🔹 Filter if a specific trial is selected
        if selected_trial is not None and t is not selected_trial:
            continue

        m = load_metrics(t.path) or {}

        click.echo(
            f"{i:>{W_ID}} {exp_id:>{W_EXP}} {run.name:<{W_RUN}} {t.name:>{W_TRIAL}} "
            f"{format_k(m.get('net_spending_for_plan_year_0')):>{W_YEAR}} "
            f"{format_k(m.get(f'total_net_spending_{value_mode}')):>{W_NET}} "
            f"{format_k(m.get(f'total_final_bequest_{value_mode}')):>{W_BEQ}}   "
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
