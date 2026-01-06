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

    Supported forms:
      {"values": [80, None]}
      {"values": {0: 80}}
      {"values": 80}   # single-person case
    """
    expectancy = diconf["basic_info"]["life_expectancy"]
    values = cfg_longevity.get("values")

    # -------------------------------
    # Scalar → person 0
    # -------------------------------
    if isinstance(values, (int | float)):
        expectancy[0] = int(values)
        return

    # -------------------------------
    # Dict index overrides (Hydra)
    # -------------------------------
    if isinstance(values, dict):
        for i, le in values.items():
            if le is not None:
                expectancy[int(i)] = int(le)
        return

    # -------------------------------
    # List overrides (TOML-style)
    # -------------------------------
    if isinstance(values, (list | tuple)):
        if len(values) > len(expectancy):
            raise ValueError(
                f"Longevity override has {len(values)} values, "
                f"but dataset only has {len(expectancy)} people"
            )
        for i, le in enumerate(values):
            if le is not None:
                expectancy[i] = int(le)
        return

    raise TypeError(f"Unsupported longevity.values type: {type(values)}")


def apply_optimization_override(diconf: dict, value: dict):
    """
    Apply optimization strategy overrides.

    Example:
        {"objective": "maxBequest"}
    """
    opt = diconf.setdefault("optimization_parameters", {})
    for k, v in value.items():
        opt[k] = v


def apply_solver_override(diconf: dict, value: dict):
    """
    Apply solver option overrides.

    Example:
        {
            "netSpending": 90,
            "bequest": 500,
            "noRothConversions": "Jill",
            "maxRothConversion": 100
        }
    """
    solver = diconf.setdefault("solver_options", {})

    for k, v in value.items():
        solver[k] = v
        logger.debug("Applied solver override: {}={}", k, v)


OVERRIDE_HANDLERS = {
    "longevity": apply_longevity_override,
    "optimization": apply_optimization_override,
    "solver": apply_solver_override,
}


# ---------------------------------------------------------------------
# TOML load / override helpers
# ---------------------------------------------------------------------


def load_original_toml(case_file: str) -> str:
    """
    Load and normalize the original TOML with no overrides applied.
    Returns normalized TOML text.
    """
    with open(case_file, encoding="utf-8") as f:
        diconf = toml.load(f)

    return toml.dumps(diconf)


def load_and_override_toml(case_file: str, overrides: dict) -> tuple[StringIO, str, dict]:
    with open(case_file, encoding="utf-8") as f:
        diconf = toml.load(f)

    diconf = deepcopy(diconf)

    logger.debug(overrides)

    # -------------------------------------------------
    # Apply semantic overrides via handlers
    # -------------------------------------------------
    if overrides:
        for key, value in overrides.items():
            # Skip index-based overrides entirely
            if "." in key:
                logger.debug("Skipping index override: {}", key)
                continue

            try:
                handler = OVERRIDE_HANDLERS[key]
            except KeyError as e:
                raise RuntimeError(
                    f"Unknown override '{key}'. " f"Supported overrides: {list(OVERRIDE_HANDLERS)}"
                ) from e

            handler(diconf, value)

    toml_text = toml.dumps(diconf)
    buf = StringIO(toml_text)
    buf.seek(0)

    return buf, toml_text, diconf


# ---------------------------------------------------------------------
# Optimization normalization
# ---------------------------------------------------------------------


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
        raise RuntimeError(f"Unknown optimization objective: {objective}")


# ---------------------------------------------------------------------
# Core solver helpers
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

    # METRICS
    metrics_path = output_path.with_suffix("").with_name(output_path.stem + "_metrics.json")
    write_metrics_json(plan, metrics_path)

    # SUMMARY
    summary_path = output_path.with_suffix("").with_name(output_path.stem + "_summary.json")
    with open(summary_path, "w") as f:
        json.dump(plan.summaryDic(), f, indent=2, sort_keys=False, default=json_safe)

    # ORIGINAL TOML
    original_toml_path = output_path.with_suffix("").with_name(output_path.stem + "_original.toml")
    with open(original_toml_path, "w", encoding="utf-8") as f:
        f.write(original_toml)

    # EFFECTIVE TOML
    effective_toml_path = output_path.with_suffix("").with_name(
        output_path.stem + "_effective.toml"
    )
    with open(effective_toml_path, "w", encoding="utf-8") as f:
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
    # Load original TOML
    # -------------------------------------------------
    original_toml = load_original_toml(case_file)

    SEMANTIC_OVERRIDE_KEYS = set(OVERRIDE_HANDLERS)

    semantic_overrides = (
        {k: v for k, v in overrides.items() if k in SEMANTIC_OVERRIDE_KEYS} if overrides else None
    )

    toml_buf, toml_text, toml_dict = load_and_override_toml(case_file, semantic_overrides)

    plan = owl.readConfig(
        toml_buf,
        logstreams="loguru",
        readContributions=False,
    )

    # -------------------------------------------------
    # Read contributions / HFP file
    # -------------------------------------------------
    hfp_section = toml_dict.get("household_financial_profile", {})
    hfp_file = hfp_section.get("HFP_file_name")

    if hfp_file:
        hfp_path = Path(case_file).parent / hfp_file
        logger.debug("HFP file: {}", hfp_path)
        plan.readContributions(str(hfp_path))

    solve_and_save(plan, output_file, toml_text, original_toml)

    if plan.caseStatus != "solved":
        return PlanRunResult(status=plan.caseStatus)

    return PlanRunResult(
        status="solved",
        output_file=output_file,
        summary=plan.summaryDic,
        adjusted_toml=toml_text,
    )
