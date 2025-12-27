# src/owlstation/core/owl_runner.py

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import numpy as np
import owlplanner as owl
import toml

from owlstation.core.metrics_from_plan import write_metrics_json

# ---------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------


@dataclass
class PlanRunResult:
    status: str
    output_file: str | None = None
    summary: dict | None = None
    adjusted_toml: str | None = None


# ---------------------------------------------------------------------
# TOML override helpers
# ---------------------------------------------------------------------


def apply_longevity_override(diconf: dict, value: dict):
    """
    Apply longevity overrides.

    value example:
        {"Jack": 85, "Jill": 90}
    """
    names = diconf["Basic Info"]["Names"]
    expectancy = diconf["Basic Info"]["Life expectancy"]

    for name, le in value.items():
        try:
            idx = names.index(name)
        except ValueError as e:
            raise RuntimeError(f"Person '{name}' not found in Basic Info.Names={names}") from e

        expectancy[idx] = int(le)


def apply_optimization_override(diconf: dict, value: dict):
    """
    Apply optimization strategy overrides and enforce invariants.

    value example:
        {"Objective": "maxBequest"}
    """

    opt = diconf.setdefault("Optimization Parameters", {})
    solver = diconf.setdefault("Solver Options", {})

    # Apply overrides
    for k, v in value.items():
        opt[k] = v

    objective = opt.get("Objective")

    if objective == "maxBequest":
        if "netSpending" not in solver:
            raise RuntimeError("Objective=maxBequest requires 'netSpending' in [Solver Options]")

        # Remove incompatible constraint
        solver.pop("bequest", None)

    elif objective == "maxSpending":
        if "bequest" not in solver:
            raise RuntimeError("Objective=maxSpending requires 'bequest' in [Solver Options]")

        # Remove incompatible constraint
        solver.pop("netSpending", None)

    else:
        raise RuntimeError(f"Unknown optimization Objective: {objective}")


def apply_solver_override(diconf: dict, value: dict):
    """
    Apply solver option overrides.

    value example:
        {
            "netSpending": 90,
            "bequest": 500,
            "noRothConversions": "Jill",
            "maxRothConversion": 100
        }
    """

    solver = diconf.setdefault("Solver Options", {})

    # -------------------------------------------------
    # Apply overrides verbatim
    # -------------------------------------------------
    for k, v in value.items():
        solver[k] = v

    # -------------------------------------------------
    # Normalize mutually exclusive solver flags
    # -------------------------------------------------

    # If noRothConversions is set, maxRothConversion is irrelevant
    if solver.get("noRothConversions"):
        solver.pop("maxRothConversion", None)

    # spendingSlack must be non-negative
    if "spendingSlack" in solver:
        slack = solver["spendingSlack"]
        if slack < 0:
            raise RuntimeError("solver.spendingSlack must be >= 0")

    # xorConstraints should be boolean
    if "xorConstraints" in solver:
        solver["xorConstraints"] = bool(solver["xorConstraints"])

    # withSCLoop should be boolean
    if "withSCLoop" in solver:
        solver["withSCLoop"] = bool(solver["withSCLoop"])

    # solver backend sanity check
    if "solver" in solver:
        if solver["solver"] not in {"HiGHS"}:
            raise RuntimeError(f"Unsupported solver backend: {solver['solver']}")


OVERRIDE_HANDLERS = {
    "longevity": apply_longevity_override,
    "optimization": apply_optimization_override,
    "solver": apply_solver_override,
}


def load_and_override_toml(case_file: str, overrides: dict) -> tuple[StringIO, str]:
    with open(case_file, encoding="utf-8") as f:
        diconf = toml.load(f)

    diconf = deepcopy(diconf)

    # -------------------------------------------------
    # Apply semantic overrides via handlers
    # -------------------------------------------------
    for key, value in overrides.items():
        try:
            handler = OVERRIDE_HANDLERS[key]
        except KeyError as e:
            raise RuntimeError(
                f"Unknown override '{key}'. " f"Supported overrides: {list(OVERRIDE_HANDLERS)}"
            ) from e

        handler(diconf, value)

    # -------------------------------------------------
    # Serialize adjusted TOML
    # -------------------------------------------------
    toml_text = toml.dumps(diconf)
    buf = StringIO(toml_text)
    buf.seek(0)

    return buf, toml_text


def normalize_optimization(plan):
    """
    Bridge Hydra intent → OWL solver semantics.
    Enforces valid optimization modes.
    """
    objective = plan.objective
    solver_opts = plan.solverOptions

    if objective == "maxBequest":
        if "netSpending" not in solver_opts:
            raise RuntimeError("Objective=maxBequest requires solver option 'netSpending'")
        solver_opts.pop("bequest", None)

    elif objective == "maxSpending":
        if "bequest" not in solver_opts:
            raise RuntimeError("Objective=maxSpending requires solver option 'bequest'")
        solver_opts.pop("netSpending", None)

    else:
        raise RuntimeError(f"Unknown optimization Objective: {objective}")


# ---------------------------------------------------------------------
# Core solver helper
# ---------------------------------------------------------------------


def json_safe(obj):
    """Convert common non-JSON types to JSON-safe values."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (datetime | date)):
        return obj.isoformat()
    if isinstance(obj, np.generic):
        return obj.item()
    if hasattr(obj, "__dict__"):
        # last-resort: stringify custom objects
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def solve_and_save(plan, output_file: str) -> None:
    """
    Solve the plan and write output.
    """

    normalize_optimization(plan)

    plan.solve(plan.objective, plan.solverOptions)

    if plan.caseStatus != "solved":
        return

    plan.saveWorkbook(basename=output_file, overwrite=True)

    output_path = Path(output_file)

    metrics_path = output_path.with_suffix("").with_name(  # strip .xlsx
        output_path.stem + "_metrics.json"
    )
    write_metrics_json(plan, metrics_path)

    summary_path = output_path.with_suffix("").with_name(  # strip .xlsx
        output_path.stem + "_summary.json"
    )

    with open(summary_path, "w") as f:
        json.dump(plan.summaryDic(), f, indent=2, sort_keys=False, default=json_safe)


# ---------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------


def run_single_case(
    *,
    case_file: str,
    overrides: dict,
    output_file: str,
) -> PlanRunResult:
    """
    Run a single OWL case with semantic overrides.

    Overrides are applied to TOML BEFORE readConfig,
    ensuring all derived horizons and constraints
    are built correctly by OWL.
    """
    toml_buf, toml_text = load_and_override_toml(case_file, overrides)

    plan = owl.readConfig(
        toml_buf,
        logstreams="loguru",
        readContributions=False,
    )

    solve_and_save(plan, output_file)

    if plan.caseStatus != "solved":
        return PlanRunResult(status=plan.caseStatus)

    return PlanRunResult(
        status="solved",
        output_file=output_file,
        summary=plan.summaryDic,
        adjusted_toml=toml_text,
    )
