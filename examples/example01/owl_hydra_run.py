# src/owlroost/hydra/owl_hydra_run.py
import os
from pathlib import Path

import hydra
from hydra.core.hydra_config import HydraConfig
from hydra.utils import to_absolute_path
from loguru import logger
from omegaconf import DictConfig, OmegaConf

from owlroost.core.configure_logging import configure_logging
from owlroost.core.override_parser import hydra_overrides_to_dict
from owlroost.core.owl_runner import run_single_case
from owlroost.core.toml_utils import toml_plan_name

# Loguru needs to initially be set OUTSIDE of main
level = os.getenv("OWLROOST_LOG_LEVEL")
if not level:
    level = "INFO"  # <- this level MUST match conf/logging/default.yaml default setting!
configure_logging(log_level=level)

# Store project root - hydra changes directories a lot!
PROJECT_ROOT = Path.cwd().resolve()


# Helper to guard against Hydra job.id not being set (single- vs multi-runs)
def get_job_id(hc) -> str:
    """
    Return a stable job id for logging and paths.

    - Multirun: "0", "1", ...
    - Single run: "0"
    """
    try:
        job_id = hc.job.id
        if job_id is None:
            return "0"
        return str(job_id)
    except Exception:
        return "0"


OmegaConf.register_new_resolver(
    "toml.plan_name",
    toml_plan_name,
    use_cache=True,  # important: prevents re-reading file repeatedly
)


@hydra.main(
    config_path="conf",  # resolved relative to CWD
    config_name="config",
    version_base=None,
)
def main(cfg: DictConfig):
    """
    Pure Hydra runner for OWL scenarios.

    - Uses ./conf from the *current working directory*
    - Supports single runs and multiruns (-m)
    - Produces one output workbook per scenario
    """
    # -------------------------------------------------
    # Validate case.file
    # -------------------------------------------------
    if not cfg.case.file:
        raise RuntimeError("case.file must be set")

    case_file = Path(to_absolute_path(cfg.case.file))
    logger.debug(case_file)

    if not case_file.exists():
        raise FileNotFoundError(f"Case file not found: {case_file}")

    # -------------------------------------------------
    # Configure Loguru from Hydra config
    # -------------------------------------------------

    configure_logging(cfg)

    # -------------------------------------------------
    # Validate required inputs
    # -------------------------------------------------
    if not hasattr(cfg, "case") or not hasattr(cfg.case, "file"):
        raise RuntimeError("Hydra config must define case.file (path to TOML case file).")

    # -------------------------------------------------
    # Hydra runtime info (SAFE for single + multirun)
    # -------------------------------------------------
    hc = HydraConfig.get()
    raw_overrides = hc.overrides.task
    job_id = get_job_id(hc)

    if 0:
        hc_dict = OmegaConf.to_container(
            hc,
            resolve=True,
        )
        logger.trace("HydraConfig dump:\n{}", OmegaConf.to_yaml(hc_dict))

    # -------------------------------------------------
    # Parse semantic overrides (shared with cmd_run)
    # -------------------------------------------------
    overrides = hydra_overrides_to_dict(raw_overrides)

    logger.info(
        "{} - overrides: {}",
        job_id,
        " ".join(raw_overrides),
    )

    # -------------------------------------------------
    # Hydra-managed run directory
    # -------------------------------------------------
    # Hydra has already chdir()'d into the job directory
    run_dir = Path.cwd()
    # run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("{} - Run directory: {}", job_id, run_dir.relative_to(PROJECT_ROOT))

    # -------------------------------------------------
    # Output filename (no redundancy needed)
    # -------------------------------------------------
    output_file = run_dir / f"{case_file.stem}.xlsx"

    # -------------------------------------------------
    # Save Hydra meta info for reproducibility
    # -------------------------------------------------
    OmegaConf.save(
        OmegaConf.create(
            {
                "mode": hc.mode,
                "job_id": job_id,
                "overrides": raw_overrides,
            }
        ),
        run_dir / "hydra_meta.yaml",
    )

    # -------------------------------------------------
    # Run OWL via shared runner
    # -------------------------------------------------
    result = run_single_case(
        case_file=str(case_file),
        overrides=overrides,
        output_file=str(output_file),
    )

    logger.info("{} - Case status: {}", job_id, result.status)

    if result.status != "solved":
        logger.warning("Case did not solve; no output written.")
        return

    logger.info(
        "{} - Results saved to: {}",
        job_id,
        output_file.relative_to(Path.cwd()),
    )


if __name__ == "__main__":
    main()
