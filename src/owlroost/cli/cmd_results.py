"""
roost results command

Summarize and inspect OWL results produced via Hydra.

Supports:
  - case summary
  - per-case experiment breakdown
  - Hydra overrides (excluding case.file)
  - semantic diff between TOML files:
      --diff          : _original.toml → _effective.toml
      --diff-project  : project Case_<name>.toml → _effective.toml
  - metrics display (net spending, bequest)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal

import click
import yaml
import tomllib
import json

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

RESULTS_DIR = Path("results")

IGNORE_PREFIXES = ("Hydra", "hydra")

# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass
class Experiment:
    type: Literal["single", "multi"]
    run_count: int
    overrides: List[str]
    sample_run: Path   # representative run dir (None/ or run_0)


@dataclass
class Case:
    name: str
    path: Path
    experiments: List[Experiment]


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------


def format_k(value) -> str:
    """Format dollar value as rounded $K."""
    if value is None:
        return "—"
    try:
        return f"${round(value / 1000):,}K"
    except Exception:
        return "—"


def strip_override_prefix(override: str) -> str:
    """Remove top-level Hydra key (optimization., solver., etc.)."""
    if "." in override:
        return override.split(".", 1)[1]
    return override


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


@click.command(name="results")
@click.argument("case", required=False)
@click.option("--diff", is_flag=True, help="Diff _original.toml vs _effective.toml.")
@click.option(
    "--diff-project",
    is_flag=True,
    help="Diff project Case_<name>.toml vs _effective.toml.",
)
@click.option("--nominal", is_flag=True, help="Show nominal dollars (default: real).")
def cmd_results(case: str | None, diff: bool, diff_project: bool, nominal: bool):
    """
    Inspect results produced by OWL runs.
    """
    if diff and diff_project:
        raise click.ClickException("Use only one of --diff or --diff-project")

    value_mode = "nominal" if nominal else "real"

    if not RESULTS_DIR.exists():
        click.echo("No results directory found.")
        return

    cases = discover_cases(RESULTS_DIR)

    if not cases:
        click.echo("No cases found in ./results.")
        return

    if (diff or diff_project) and case is None:
        raise click.ClickException("--diff options require a CASE")

    if case is None:
        render_case_summary(cases)
    else:
        selected = resolve_case(case, cases)
        render_case_breakdown(
            selected,
            diff_mode="original" if diff else "project" if diff_project else None,
            value_mode=value_mode,
        )


# ---------------------------------------------------------------------
# Discovery logic
# ---------------------------------------------------------------------


def discover_cases(results_dir: Path) -> List[Case]:
    cases: List[Case] = []
    for case_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        cases.append(
            Case(
                name=case_dir.name,
                path=case_dir,
                experiments=discover_experiments(case_dir),
            )
        )
    return cases


def discover_experiments(case_dir: Path) -> List[Experiment]:
    experiments: List[Experiment] = []

    for date_dir in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        for time_dir in sorted(p for p in date_dir.iterdir() if p.is_dir()):
            multirun_file = time_dir / "multirun.yaml"

            if multirun_file.exists():
                runs = sorted(time_dir.glob("run_*"))
                if not runs:
                    continue
                experiments.append(
                    Experiment(
                        type="multi",
                        run_count=len(runs),
                        overrides=extract_multirun_overrides(time_dir),
                        sample_run=runs[0],
                    )
                )
            else:
                single = time_dir / "None"
                if not single.exists():
                    continue
                experiments.append(
                    Experiment(
                        type="single",
                        run_count=0,
                        overrides=extract_single_overrides(time_dir),
                        sample_run=single,
                    )
                )

    return experiments


# ---------------------------------------------------------------------
# Override extraction
# ---------------------------------------------------------------------


def extract_multirun_overrides(time_dir: Path) -> List[str]:
    path = time_dir / "multirun.yaml"
    if not path.exists():
        return []

    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return []

    overrides = (
        data.get("hydra", {})
        .get("overrides", {})
        .get("task", [])
    )

    return [
        strip_override_prefix(o)
        for o in overrides
        if isinstance(o, str) and not o.startswith("case.file=")
    ]


def extract_single_overrides(time_dir: Path) -> List[str]:
    meta = time_dir / "None" / "hydra_meta.yaml"
    if not meta.exists():
        return []

    try:
        data = yaml.safe_load(meta.read_text()) or {}
    except Exception:
        return []

    overrides = data.get("overrides", [])

    return [
        strip_override_prefix(o)
        for o in overrides
        if isinstance(o, str) and not o.startswith("case.file=")
    ]


# ---------------------------------------------------------------------
# TOML / metrics loading
# ---------------------------------------------------------------------


def load_effective_toml(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_effective.toml"), None)
    if not p:
        return None
    return tomllib.load(p.open("rb"))


def load_original_toml(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_original.toml"), None)
    if not p:
        return None
    return tomllib.load(p.open("rb"))


def load_project_toml(run_dir: Path) -> dict | None:
    src = (
        next(run_dir.glob("*_original.toml"), None)
        or next(run_dir.glob("*_effective.toml"), None)
    )
    if not src or not src.name.startswith("Case_"):
        return None

    base = src.name.rsplit("_", 1)[0]
    path = Path(f"{base}.toml")
    if not path.exists():
        return None

    return tomllib.load(path.open("rb"))


def load_metrics(run_dir: Path) -> dict | None:
    p = next(run_dir.glob("*_metrics.json"), None)
    if not p:
        return None
    return json.load(p.open())


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------


def render_case_summary(cases: List[Case]):
    click.echo(f"Found {len(cases)} cases in ./results\n")
    header = f"{'ID':<3} {'CASE NAME':<25} {'EXPERIMENTS':<12}"
    click.echo(header)
    click.echo("-" * len(header))

    for idx, case in enumerate(cases):
        click.echo(f"{idx:<3} {case.name:<25} {len(case.experiments):<12}")


def render_case_breakdown(case: Case, diff_mode: str | None, value_mode: str):
    click.echo(f"\nCase: {case.name}\n")

    # -------------------------
    # Column widths (tuned)
    # -------------------------
    w_id = 3
    w_run = 5
    w_type = 7
    w_obj = 12
    w_avg = 9     # NEW: $/yr column
    w_net = 9
    w_beq = 9

    # -------------------------
    # Two-line header
    # -------------------------
    header1 = (
        f"{'':<{w_id}} "
        f"{'':<{w_run}} "
        f"{'':<{w_type}} "
        f"{'':<{w_obj}} "
        f"{'$/yr':>{w_avg}} "
        f"{'NetSpend':>{w_net}} "
        f"{'Bequest':>{w_beq}}   "
        f"{'Overrides'}"
    )

    header2 = (
        f"{'ID':<{w_id}} "
        f"{'Name':<{w_run}} "
        f"{'Type':<{w_type}} "
        f"{'Objective':<{w_obj}} "
        f"{'(real $K)':>{w_avg}} "
        f"{f'({value_mode} $K)':>{w_net}} "
        f"{f'({value_mode} $K)':>{w_beq}}"
    )

    click.echo(header1)
    click.echo(header2)
    click.echo("-" * max(len(header1), len(header2)))

    # -------------------------
    # Rows
    # -------------------------
    for idx, exp in enumerate(case.experiments):
        run_name = exp.sample_run.name
        eff = load_effective_toml(exp.sample_run) or {}
        metrics = load_metrics(exp.sample_run) or {}

        objective = eff.get("Optimization Parameters", {}).get("Objective", "—")

        # --- Net / Bequest totals ---
        net_key = f"total_net_spending_{value_mode}"
        beq_key = f"total_final_bequest_{value_mode}"

        net = format_k(metrics.get(net_key))
        beq = format_k(metrics.get(beq_key))

        # --- NEW: average real $ / year ---
        try:
            total_real = metrics.get("total_net_spending_real")
            y0 = metrics.get("year_start")
            y1 = metrics.get("year_final_bequest")

            if total_real is not None and y0 is not None and y1 is not None:
                years = (y1 - y0 + 1)
                avg_real = (total_real / years) / 1000.0
                avg_fmt = f"${avg_real:,.1f}K"
            else:
                avg_fmt = "—"
        except Exception:
            avg_fmt = "—"

        overrides = ", ".join(exp.overrides) if exp.overrides else "—"

        click.echo(
            f"{idx:<{w_id}} "
            f"{run_name:<{w_run}} "
            f"{exp.type:<{w_type}} "
            f"{objective:<{w_obj}} "
            f"{avg_fmt:>{w_avg}} "
            f"{net:>{w_net}} "
            f"{beq:>{w_beq}}   "
            f"{overrides}"
        )

        if diff_mode:
            render_experiment_diff(exp, diff_mode)
            click.echo()


def render_experiment_diff(exp: Experiment, diff_mode: str):
    effective = load_effective_toml(exp.sample_run)
    if not effective:
        click.echo("  (no effective TOML found)")
        return

    if diff_mode == "original":
        base = load_original_toml(exp.sample_run)
        label = "original"
    else:
        base = load_project_toml(exp.sample_run)
        label = "project"

    if not base:
        click.echo(f"  (no {label} TOML found)")
        return

    diffs = diff_toml(base, effective)
    if not any(diffs.values()):
        click.echo("  No changes.")
        return

    click.echo(f"  Diff ({label} → effective):")
    for k, (a, b) in diffs["changed"].items():
        click.echo(f"    {k}: {a} → {b}")


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


def resolve_case(token: str, cases: List[Case]) -> Case:
    if token.isdigit():
        idx = int(token)
        if idx < 0 or idx >= len(cases):
            raise click.ClickException("Invalid case ID.")
        return cases[idx]

    for case in cases:
        if case.name == token:
            return case

    raise click.ClickException(f"Case not found: {token}")
