# src/owlroost/hydra/trial_worker.py

import tomllib
from pathlib import Path

import numpy as np
from loguru import logger

from owlroost.core.configure_logging import CURRENT_LOG_LEVEL
from owlroost.core.longevity import sample_individual_lifetime
from owlroost.core.owl_runner import run_single_case


def run_trial_star(args):
    from owlroost.hydra.trial_worker import run_trial

    return run_trial(*args)


def run_trial(
    job_id: int,
    trial_id: int,
    rates_seed: int | None,
    longevity_seed: int | None,
    case_file: Path,
    base_overrides: dict,
    run_dir: Path,
):
    trial_dir = run_dir / "trials" / f"{trial_id:04d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    output_file = trial_dir / f"{case_file.stem}.xlsx"
    overrides = dict(base_overrides)

    # ---------------- rates seed ----------------
    if rates_seed is not None:
        overrides.setdefault("rates", {})["rate_seed"] = rates_seed

    # ---------------- longevity ----------------
    if longevity_seed is not None:
        case_data = tomllib.loads(case_file.read_text())

        ages = case_data["basic_info"]["life_expectancy"]
        health = case_data["basic_info"].get("health", ["average"] * len(ages))
        sex = case_data["basic_info"].get("sex", ["female"] * len(ages))
        smoker = case_data["basic_info"].get("smoker", [False] * len(ages))
        married = case_data["basic_info"].get("married", True)

        rng = np.random.default_rng(longevity_seed)
        life_exp = [
            int(
                sample_individual_lifetime(
                    rng,
                    current_age=ages[i],
                    health=health[i],
                    sex=sex[i],
                    smoker=smoker[i],
                    married=married,
                )
            )
            for i in range(len(ages))
        ]

        overrides.setdefault("basic_info", {})["life_expectancy"] = life_exp
        overrides["basic_info"]["longevity_seed"] = longevity_seed

    logger.debug(
        "Job: {:5} | Trial {:04d} | life_expectancy={} | rates_seed={} | longevity_seed={} | dir={}",
        job_id,
        trial_id,
        overrides,
        rates_seed if rates_seed is not None else "TOML",
        longevity_seed if longevity_seed is not None else "TOML",
        trial_dir.relative_to(run_dir),
    )

    if CURRENT_LOG_LEVEL not in {"TRACE", "DEBUG"}:
        logger.info(
            "Job: {:5} | Trial {:04d}",
            job_id,
            trial_id,
        )
        result = run_single_case(
            case_file=str(case_file),
            overrides=overrides,
            output_file=str(output_file),
        )

    return {
        "trial_id": trial_id,
        "rates_seed": rates_seed,
        "longevity_seed": longevity_seed,
        "status": result.status,
        "output": str(output_file) if result.status == "solved" else None,
    }
