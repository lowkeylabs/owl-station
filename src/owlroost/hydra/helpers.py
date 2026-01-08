# src/owlroost/hydra/helpers.py
import os
from pathlib import Path

from hydra.core.hydra_config import HydraConfig
from hydra.utils import to_absolute_path
from loguru import logger
from omegaconf import OmegaConf

from owlroost.core.owl_runner import run_single_case
from owlroost.core.toml_utils import toml_plan_name

# ---------------------------------------------------------------------
# Project root handling
# ---------------------------------------------------------------------

PROJECT_ROOT = Path.cwd().resolve()


# ---------------------------------------------------------------------
# Logging bootstrap (needed before Hydra main)
# ---------------------------------------------------------------------


def bootstrap_logging():
    """
    Configure Loguru before Hydra runs.

    This must happen at import time (outside @hydra.main).
    """
    from owlroost.core.configure_logging import configure_logging

    level = os.getenv("OWLROOST_LOG_LEVEL") or "INFO"
    configure_logging(log_level=level)


# ---------------------------------------------------------------------
# Hydra job helpers
# ---------------------------------------------------------------------


def get_job_id(hc: HydraConfig) -> str:
    """
    Return a stable job id for logging and paths.

    - Multirun: "0", "1", ...
    - Single run: "0"
    """
    try:
        job_id = hc.job.id
        return str(job_id) if job_id is not None else "0"
    except Exception:
        return "0"


def get_run_dir() -> Path:
    """
    Return the Hydra-managed run directory.

    Hydra has already chdir()'d at this point.
    """
    return Path.cwd()


# ---------------------------------------------------------------------
# Case file helpers
# ---------------------------------------------------------------------


def resolve_case_file(case_file: str | Path) -> Path:
    """
    Resolve and validate the case file path.
    """
    if not case_file:
        raise RuntimeError("case.file must be set")

    case_path = Path(to_absolute_path(str(case_file)))

    if not case_path.exists():
        raise FileNotFoundError(f"Case file not found: {case_path}")

    return case_path


# ---------------------------------------------------------------------
# Hydra metadata persistence
# ---------------------------------------------------------------------


def save_hydra_metadata(
    *,
    run_dir: Path,
    mode: str,
    job_id: str,
    overrides: list[str],
):
    """
    Save Hydra metadata needed for reproducibility.
    """
    OmegaConf.save(
        OmegaConf.create(
            {
                "mode": mode,
                "job_id": job_id,
                "overrides": overrides,
            }
        ),
        run_dir / "hydra_meta.yaml",
    )


# ---------------------------------------------------------------------
# OmegaConf resolvers
# ---------------------------------------------------------------------


def register_resolvers():
    """
    Register all OmegaConf resolvers used by OWL-ROOST.
    """
    OmegaConf.register_new_resolver(
        "toml.plan_name",
        toml_plan_name,
        use_cache=True,  # prevents re-reading TOML repeatedly
    )


def run_trial(
    *,
    trial_id: int,
    trial_seed: int,
    case_file: Path,
    base_overrides: dict,
    run_dir: Path,
):
    """
    Execute a single trial in its own directory.
    """
    trial_dir = run_dir / "trials" / f"{trial_id:04d}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    output_file = trial_dir / f"{case_file.stem}.xlsx"

    overrides = dict(base_overrides)
    overrides.setdefault("rates", {})["rate_seed"] = trial_seed

    logger.info(
        "Trial {:04d} | seed={} | dir={}",
        trial_id,
        trial_seed,
        trial_dir.relative_to(run_dir),
    )

    result = run_single_case(
        case_file=str(case_file),
        overrides=overrides,
        output_file=str(output_file),
    )

    return {
        "trial_id": trial_id,
        "seed": trial_seed,
        "status": result.status,
        "output": str(output_file) if result.status == "solved" else None,
    }
