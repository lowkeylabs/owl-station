# src/owlroost/core/owl_runner.py
import ast
import json
import shutil
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from pathlib import Path

import numpy as np
import owlplanner as owl
import pandas as pd
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


def coerce_override_value(v):
    if isinstance(v, str):
        try:
            parsed = ast.literal_eval(v)
            return parsed
        except (ValueError, SyntaxError):
            return v
    return v


def apply_generic_overrides(key: str, diconf: dict, value: dict):
    group = diconf.setdefault(key, {})

    for k, v in value.items():
        v = coerce_override_value(v)
        logger.debug("Overrides: {}: {}={}", key, k, v)
        group[k] = v


def apply_basic_info_overrides(diconf: dict, value: dict):
    apply_generic_overrides("basic_info", diconf, value)


def apply_savings_assets_overrides(diconf: dict, value: dict):
    apply_generic_overrides("savings_assets", diconf, value)


def apply_fixed_income_overrides(diconf: dict, value: dict):
    apply_generic_overrides("fixed_income", diconf, value)


def apply_rates_overrides(diconf: dict, value: dict):
    apply_generic_overrides("rates_selection", diconf, value)


def apply_asset_allocation_overrides(diconf: dict, value: dict):
    apply_generic_overrides("asset_allocation", diconf, value)


def apply_optimization_overrides(diconf: dict, value: dict):
    apply_generic_overrides("optimization_parameters", diconf, value)


def apply_solver_overrides(diconf: dict, value: dict):
    apply_generic_overrides("solver_options", diconf, value)


OVERRIDE_HANDLERS = {
    "basic_info": apply_basic_info_overrides,
    "savings_assets": apply_savings_assets_overrides,
    "fixed_income": apply_fixed_income_overrides,
    "rates": apply_rates_overrides,
    "asset_allocation": apply_asset_allocation_overrides,
    "optimization": apply_optimization_overrides,
    "solver": apply_solver_overrides,
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

    return diconf


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

    output_path = Path(output_file)

    # Save these files before call.  ORIGINAL TOML
    original_toml_path = output_path.with_suffix("").with_name(output_path.stem + "_original.toml")
    with open(original_toml_path, "w", encoding="utf-8") as f:
        f.write(original_toml)

    # Safe before solve. EFFECTIVE TOML
    effective_toml_path = output_path.with_suffix("").with_name(
        output_path.stem + "_effective.toml"
    )
    with open(effective_toml_path, "w", encoding="utf-8") as f:
        f.write(effective_toml)

    # save rates
    rates_dict = {
        "Year": plan.year_n.tolist(),
        "S&P 500": plan.tau_kn[0].tolist(),
        "Corporate Baa": plan.tau_kn[1].tolist(),
        "T Bonds": plan.tau_kn[2].tolist(),
        "inflation": plan.tau_kn[3].tolist(),
    }
    rates_path = output_path.with_suffix("").with_name(output_path.stem + "_rates.xlsx")

    df = pd.DataFrame(rates_dict)
    df.to_excel(
        rates_path,
        index=False,  # no extra index column
        sheet_name="Rates",  # optional but nice
    )

    # solve
    plan.solve(plan.objective, plan.solverOptions)

    if plan.caseStatus != "solved":
        return

    # Save these files if solve was OK.

    p = Path(output_file)
    results_file = p.with_name(f"{p.stem}_results{p.suffix}")

    plan.saveWorkbook(basename=results_file, overwrite=True)

    # METRICS
    metrics_path = output_path.with_suffix("").with_name(output_path.stem + "_metrics.json")
    write_metrics_json(plan, metrics_path)

    # SUMMARY
    summary_path = output_path.with_suffix("").with_name(output_path.stem + "_summary.json")
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
    logger.debug(overrides)

    # -------------------------------------------------
    # Load original TOML
    # -------------------------------------------------
    original_toml = load_original_toml(case_file)

    SEMANTIC_OVERRIDE_KEYS = set(OVERRIDE_HANDLERS)

    semantic_overrides = (
        {k: v for k, v in overrides.items() if k in SEMANTIC_OVERRIDE_KEYS} if overrides else None
    )

    toml_dict = load_and_override_toml(case_file, semantic_overrides)

    hfp_section = toml_dict.get("household_financial_profile", {})
    hfp_file = hfp_section.get("HFP_file_name")

    trial_path = Path(output_file).parent

    if hfp_file:
        hfp_path = Path(case_file).parent / hfp_file

        hfp_original = trial_path / f"{hfp_path.stem}_original{hfp_path.suffix}"
        shutil.copy2(hfp_path, hfp_original)

        hfp_modified = trial_path / f"{hfp_path.stem}_effective{hfp_path.suffix}"
        shutil.copy2(hfp_original, hfp_modified)
        hfp_section["HFP_file_name"] = hfp_modified.name

        # Add code to modify hfp_modified as necessary

    modified_toml = toml.dumps(toml_dict)
    toml_buf = StringIO(modified_toml)
    toml_buf.seek(0)

    plan = owl.readConfig(
        toml_buf,
        logstreams="loguru",
        readContributions=False,
    )
    if hfp_file:
        plan.readContributions(str(hfp_modified))

    solve_and_save(plan, output_file, modified_toml, original_toml)

    if plan.caseStatus != "solved":
        return PlanRunResult(status=plan.caseStatus)

    return PlanRunResult(
        status="solved",
        output_file=output_file,
        summary=plan.summaryDic,
        adjusted_toml=modified_toml,
    )
