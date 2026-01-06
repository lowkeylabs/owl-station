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
# Data models
# ---------------------------------------------------------------------


@dataclass
class RunResult:
    run_dir: Path
    run_name: str
    run_type: Literal["single", "multi"]
    overrides: list[str]


@dataclass
class Experiment:
    type: Literal["single", "multi"]
    runs: list[RunResult]


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
@click.option("--diff", is_flag=True, help="Diff _original.toml vs _effective.toml.")
@click.option(
    "--diff-project",
    is_flag=True,
    help="Diff project Case_<name>.toml vs _effective.toml.",
)
@click.option("--metrics", is_flag=True, help="Show metrics.json (default for run ID).")
@click.option("--summary", is_flag=True, help="Show summary.json for run ID.")
@click.option("--original", is_flag=True, help="Show _original.toml for run ID.")
@click.option("--effective", is_flag=True, help="Show _effective.toml for run ID.")
@click.option("--nominal", is_flag=True, help="Show nominal dollars (default: real).")
def cmd_results(
    case: str | None,
    run_id: int | None,
    diff: bool,
    diff_project: bool,
    metrics: bool,
    summary: bool,
    original: bool,
    effective: bool,
    nominal: bool,
):
    """
    Display case and run results from the ./results directory.
    """

    if diff and diff_project:
        raise click.ClickException("Use only one of --diff or --diff-project")

    display_flags = [metrics, summary, original, effective]
    if sum(bool(f) for f in display_flags) > 1:
        raise click.ClickException(
            "Use only one of --metrics, --summary, --original, or --effective"
        )

    value_mode = "nominal" if nominal else "real"

    if not RESULTS_DIR.exists():
        click.echo("No results directory found.")
        return

    cases = discover_cases(RESULTS_DIR)
    if not cases:
        click.echo("No cases found in ./results.")
        return

    # --------------------------------------------------
    # No CASE → case summary
    # --------------------------------------------------
    if case is None:
        render_case_summary(cases)
        return

    selected = resolve_case(case, cases)

    # --------------------------------------------------
    # CASE only → full table
    # --------------------------------------------------
    if run_id is None:
        render_case_breakdown(
            selected,
            diff_mode="original" if diff else "project" if diff_project else None,
            value_mode=value_mode,
        )
        return

    # --------------------------------------------------
    # CASE + RUN_ID → per-run inspection
    # --------------------------------------------------
    runs = flatten_runs(selected)

    if run_id < 0 or run_id >= len(runs):
        raise click.ClickException(f"Invalid run ID: {run_id}")

    run = runs[run_id]

    if not any([metrics, summary, original, effective]):
        metrics = True

    if summary:
        render_summary(run.run_dir)
    elif metrics:
        render_metrics(run.run_dir)
    elif original:
        render_original_toml(run.run_dir)
    elif effective:
        render_effective_toml(run.run_dir)
    else:
        render_run_diff(
            run.run_dir,
            diff_mode="original" if diff else "project",
        )


# ---------------------------------------------------------------------
# Discovery logic
# ---------------------------------------------------------------------


def discover_cases(results_dir: Path) -> list[Case]:
    cases: list[Case] = []
    for case_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        cases.append(
            Case(
                name=case_dir.name,
                path=case_dir,
                experiments=discover_experiments(case_dir),
            )
        )
    return cases


def run_index(run_dir: Path) -> int:
    try:
        return int(run_dir.name.split("_", 1)[1])
    except Exception:
        return 10**9


def discover_experiments(case_dir: Path) -> list[Experiment]:
    experiments: list[Experiment] = []

    for date_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        for time_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            runs: list[RunResult] = []
            multirun_file = time_dir / "multirun.yaml"

            if multirun_file.exists():
                for run_dir in sorted(time_dir.glob("run_*"), key=run_index):
                    runs.append(
                        RunResult(
                            run_dir=run_dir,
                            run_name=run_dir.name,
                            run_type="multi",
                            overrides=extract_run_overrides(run_dir / "hydra_meta.yaml"),
                        )
                    )
                if runs:
                    experiments.append(Experiment(type="multi", runs=runs))
            else:
                single_dir = time_dir / "None"
                if single_dir.exists():
                    experiments.append(
                        Experiment(
                            type="single",
                            runs=[
                                RunResult(
                                    run_dir=single_dir,
                                    run_name="None",
                                    run_type="single",
                                    overrides=extract_run_overrides(single_dir / "hydra_meta.yaml"),
                                )
                            ],
                        )
                    )

    return experiments


# ---------------------------------------------------------------------
# Override extraction
# ---------------------------------------------------------------------


def extract_run_overrides(meta_path: Path) -> list[str]:
    if not meta_path.exists():
        return []

    try:
        data = yaml.safe_load(meta_path.read_text()) or {}
    except Exception:
        return []

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


def load_project_toml(run_dir: Path) -> dict | None:
    src = next(run_dir.glob("*_original.toml"), None) or next(
        run_dir.glob("*_effective.toml"), None
    )
    if not src or not src.name.startswith("Case_"):
        return None

    path = Path(f"{src.name.rsplit('_', 1)[0]}.toml")
    return tomllib.load(path.open("rb")) if path.exists() else None


def load_metrics(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_metrics.json"), None)
    return json.load(p.open()) if p else None


# ---------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------


def flatten_runs(case: Case) -> list[RunResult]:
    runs: list[RunResult] = []
    for exp in case.experiments:
        runs.extend(exp.runs)
    return runs


def render_metrics(run_dir: Path):
    data = load_metrics(run_dir)
    if not data:
        click.echo("(no metrics found)")
        return
    click.echo(json.dumps(data, indent=2, sort_keys=False))


def render_summary(run_dir: Path):
    p = next(run_dir.glob("*_summary.json"), None)
    if not p:
        click.echo("(no summary found)")
        return
    click.echo(json.dumps(json.load(p.open()), indent=2, sort_keys=False))


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


def render_run_diff(run_dir: Path, diff_mode: str):
    effective = load_effective_toml(run_dir)
    if not effective:
        click.echo("  (no effective TOML found)")
        return

    if diff_mode == "original":
        base = load_original_toml(run_dir)
        label = "original"
    else:
        base = load_project_toml(run_dir)
        label = "project"

    if not base:
        click.echo(f"  (no {label} TOML found)")
        return

    diffs = diff_toml(base, effective)
    if not any(diffs.values()):
        click.echo("  No changes.")
        return

    click.echo(f"  Diff ({label} → effective):")

    # -------------------------
    # Changed values
    # -------------------------
    for k, (a, b) in diffs["changed"].items():
        click.echo(f"    ~ {k}: {a} → {b}")

    # -------------------------
    # Added values
    # -------------------------
    for k, v in diffs["added"].items():
        click.echo(f"    + {k}: {v}")

    # -------------------------
    # Removed values
    # -------------------------
    for k, v in diffs["removed"].items():
        click.echo(f"    - {k}: {v}")


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------


def render_case_summary(cases: list[Case]):
    click.echo(f"Found {len(cases)} cases in ./results\n")

    header = f"{'ID':<3} {'CASE NAME':<25} {'EXPERIMENTS':<12} {'RUNS':<6}"
    click.echo(header)
    click.echo("-" * len(header))

    for idx, case in enumerate(cases):
        exp_count = len(case.experiments)
        run_count = sum(len(exp.runs) for exp in case.experiments)

        click.echo(f"{idx:<3} {case.name:<25} {exp_count:<12} {run_count:<6}")


def render_case_breakdown(case: Case, diff_mode: str | None, value_mode: str):
    click.echo(f"\nCase: {case.name}\n")

    w_exp = 3
    w_id = 3
    w_run = 6
    w_type = 7
    w_obj = 12
    w_avg = 9
    w_net = 9
    w_beq = 9

    header1 = (
        f"{'':>{w_exp}} {'':>{w_id}} {'':>{w_run}} {'':<{w_type}} {'':<{w_obj}} "
        f"{'$/yr':>{w_avg}} {'NetSpend':>{w_net}} {'Bequest':>{w_beq}}   Overrides"
    )
    header2 = (
        f"{'EXP':>{w_exp}} {'ID':>{w_id}} {'Name':<{w_run}} {'Type':<{w_type}} "
        f"{'Objective':<{w_obj}} "
        f"{'(real $K)':>{w_avg}} ({value_mode} $K)"
        f"{'':>{w_net - len(value_mode) - 3}} "
        f"({value_mode} $K)"
    )

    click.echo(header1)
    click.echo(header2)
    click.echo("-" * max(len(header1), len(header2)))

    row_id = 0

    for exp_id, exp in enumerate(case.experiments):
        for run in exp.runs:
            eff = load_effective_toml(run.run_dir) or {}
            metrics = load_metrics(run.run_dir) or {}

            objective = eff.get("optimization_parameters", {}).get("objective", "—")

            net_key = f"total_net_spending_{value_mode}"
            beq_key = f"total_final_bequest_{value_mode}"

            net = format_k(metrics.get(net_key))
            beq = format_k(metrics.get(beq_key))

            y0_spend = metrics.get("net_spending_for_plan_year_0")
            y0_fmt = f"${y0_spend / 1000:,.1f}K" if y0_spend else "—"

            overrides = ", ".join(run.overrides) if run.overrides else "—"

            click.echo(
                f"{exp_id:>{w_exp}} "
                f"{row_id:>{w_id}} "
                f"{run.run_name:<{w_run}} "
                f"{run.run_type:<{w_type}} "
                f"{objective:<{w_obj}} "
                f"{y0_fmt:>{w_avg}} "
                f"{net:>{w_net}} "
                f"{beq:>{w_beq}}   "
                f"{overrides}"
            )

            if diff_mode:
                render_run_diff(run.run_dir, diff_mode)
                click.echo()

            row_id += 1


# ---------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------


def flatten_dict(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        else:
            out[key] = v
    return out


def diff_toml(original: dict, effective: dict) -> dict:
    o_flat = flatten_dict(original)
    e_flat = flatten_dict(effective)

    changes = {"changed": {}, "added": {}, "removed": {}}
    for key in sorted(set(o_flat) | set(e_flat)):
        if any(key.startswith(p) for p in IGNORE_PREFIXES):
            continue
        if key in o_flat and key in e_flat and o_flat[key] != e_flat[key]:
            changes["changed"][key] = (o_flat[key], e_flat[key])
        elif key in e_flat and key not in o_flat:
            changes["added"][key] = e_flat[key]
        elif key in o_flat and key not in e_flat:
            changes["removed"][key] = o_flat[key]

    return changes


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------


def resolve_case(token: str, cases: list[Case]) -> Case:
    if token.isdigit():
        idx = int(token)
        if idx < 0 or idx >= len(cases):
            raise click.ClickException("Invalid case ID.")
        return cases[idx]

    for case in cases:
        if case.name == token:
            return case

    raise click.ClickException(f"Case not found: {token}")
