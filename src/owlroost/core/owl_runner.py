# src/owlroost/core/owl_runner.py

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import numpy as np
import owlplanner as owl
import toml
from loguru import logger

from owlroost.core.metrics_from_plan import write_metrics_json

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


def apply_longevity_override(diconf: dict, cfg_longevity: dict):
    """
    Apply longevity overrides from merged Hydra config.

    cfg_longevity example:
        {"values": [99, None]}
    """
    expectancy = diconf["Basic Info"]["Life expectancy"]

    values = cfg_longevity.get("values", [])

    if not isinstance(values, (list | tuple)):
        raise TypeError("longevity.values must be a list")

    if len(values) > len(expectancy):
        raise ValueError(
            f"Longevity override has {len(values)} values, "
            f"but dataset only has {len(expectancy)} people"
        )

    for i, le in enumerate(values):
        if le is not None:
            expectancy[i] = int(le)


def apply_optimization_override(diconf: dict, value: dict):
    """
    Apply optimization strategy overrides and enforce invariants.

    value example:
        {"Objective": "maxBequest"}
    """

    opt = diconf.setdefault("Optimization Parameters", {})
    # Apply overrides
    for k, v in value.items():
        opt[k] = v


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


OVERRIDE_HANDLERS = {
    "longevity": apply_longevity_override,
    "optimization": apply_optimization_override,
    "solver": apply_solver_override,
}


def load_original_toml(case_file: str) -> str:
    """
    Load and normalize the original TOML with no overrides applied.
    Returns normalized TOML text.
    """
    with open(case_file, encoding="utf-8") as f:
        diconf = toml.load(f)

    # Normalize via round-trip serialization
    return toml.dumps(diconf)


def load_and_override_toml(case_file: str, overrides: dict) -> tuple[StringIO, str]:
    with open(case_file, encoding="utf-8") as f:
        diconf = toml.load(f)

    diconf = deepcopy(diconf)

    logger.debug(overrides)
    # -------------------------------------------------
    # Apply semantic overrides via handlers
    # -------------------------------------------------
    if overrides:
        for key, value in overrides.items():
            # 🚫 Skip index-based overrides entirely
            if "." in key:
                logger.debug("Skipping index override: {}", key)
                continue

            try:
                handler = OVERRIDE_HANDLERS[key]
            except KeyError as e:
                raise RuntimeError(
                    f"Unknown override '{key}'. " f"Supported overrides: {list(OVERRIDE_HANDLERS)}"
                ) from e
            if handler is None:
                logger.debug("Ignoring non-semantic override: {}", key)
            handler(diconf, value)

    # -------------------------------------------------
    # Serialize adjusted TOML
    # -------------------------------------------------
    toml_text = toml.dumps(diconf)
    buf = StringIO(toml_text)
    buf.seek(0)

    return buf, toml_text, diconf


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


def solve_and_save(plan, output_file: str, effective_toml: str, original_toml: str) -> None:
    """
    Solve the plan and write output.
    """

    normalize_optimization(plan)

    plan.solve(plan.objective, plan.solverOptions)

    if plan.caseStatus != "solved":
        return

    plan.saveWorkbook(basename=output_file, overwrite=True)

    output_path = Path(output_file)

    # Write METRICS JSON
    metrics_path = output_path.with_suffix("").with_name(  # strip .xlsx
        output_path.stem + "_metrics.json"
    )
    write_metrics_json(plan, metrics_path)

    # Write SUMMARY JSON
    summary_path = output_path.with_suffix("").with_name(  # strip .xlsx
        output_path.stem + "_summary.json"
    )
    with open(summary_path, "w") as f:
        json.dump(plan.summaryDic(), f, indent=2, sort_keys=False, default=json_safe)

    # Write ORIGINAL TOML
    original_toml_path = output_path.with_suffix("").with_name(output_path.stem + "_original.toml")
    with open(original_toml_path, "w", encoding="utf-8") as f:
        f.write(original_toml)

    # Write EFFECTIVE TOML
    toml_path = output_path.with_suffix("").with_name(output_path.stem + "_effective.toml")
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(effective_toml)


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

    logger.debug(overrides)

    # -------------------------------------------------
    # Load and normalize ORIGINAL TOML (no overrides)
    # -------------------------------------------------
    original_toml = load_original_toml(case_file)

    SEMANTIC_OVERRIDE_KEYS = set(OVERRIDE_HANDLERS)
    if overrides:
        semantic_overrides = {k: v for k, v in overrides.items() if k in SEMANTIC_OVERRIDE_KEYS}
    else:
        semantic_overrides = None
    toml_buf, toml_text, toml_dict = load_and_override_toml(case_file, semantic_overrides)

    plan = owl.readConfig(
        toml_buf,
        logstreams="loguru",
        readContributions=False,
    )

    # Add code to find and read from contributions file

    hfp_section = toml_dict.get("Household Financial Profile", {})
    timeListsFileName = hfp_section.get("HFP file name", None)
    timeListsFileName = str(Path(case_file).parent / timeListsFileName)
    logger.debug(f"HFP file: {timeListsFileName}")
    plan.readContributions(timeListsFileName)

    logger.debug(f"{plan.tau_kn}")
    # self.tau_kn = dr.genSeries(self.N_n).transpose()
    # self.mylog.vprint(f"Generating rate series of {len(self.tau_kn[0])} years using {method} method.")

    # Once rates are selected, (re)build cumulative inflation multipliers.
    # self.gamma_n = _genGamma_n(self.tau_kn)

    solve_and_save(plan, output_file, toml_text, original_toml)

    if plan.caseStatus != "solved":
        return PlanRunResult(status=plan.caseStatus)

    return PlanRunResult(
        status="solved",
        output_file=output_file,
        summary=plan.summaryDic,
        adjusted_toml=toml_text,
    )
