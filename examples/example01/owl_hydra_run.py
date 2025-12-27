# src/owlstation/hydra/owl_hydra_run.py
import os
from pathlib import Path

import hydra
from hydra.core.hydra_config import HydraConfig
from loguru import logger
from omegaconf import DictConfig, OmegaConf

from owlstation.core.configure_logging import configure_logging
from owlstation.core.override_parser import hydra_overrides_to_dict
from owlstation.core.owl_runner import run_single_case

# Loguru needs to initially be set OUTSIDE of main
level = os.getenv("OWLSTATION_LOG_LEVEL")
if not level:
    level = "INFO"  # <- this level MUST match conf/logging/default.yaml default setting!
configure_logging(log_level=level)


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
    # Configure Loguru from Hydra config
    # -------------------------------------------------

    configure_logging(cfg)

    # -------------------------------------------------
    # Validate required inputs
    # -------------------------------------------------
    if not hasattr(cfg, "case") or not hasattr(cfg.case, "file"):
        raise RuntimeError("Hydra config must define case.file (path to TOML case file).")

    case_file = Path(cfg.case.file)

    if not case_file.exists():
        raise FileNotFoundError(f"Case file not found: {case_file}")

    # -------------------------------------------------
    # Hydra runtime info (SAFE for single + multirun)
    # -------------------------------------------------
    hc = HydraConfig.get()
    raw_overrides = hc.overrides.task

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
        "Job {} - overrides: {}",
        hc.job.num,
        " ".join(raw_overrides),
    )

    # -------------------------------------------------
    # Hydra-managed run directory
    # -------------------------------------------------
    # Hydra has already chdir()'d into the job directory
    run_dir = Path(hc.runtime.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------
    # Output filename (no redundancy needed)
    # -------------------------------------------------
    output_file = run_dir / f"{case_file.stem}.xlsx"

    # -------------------------------------------------
    # Run OWL via shared runner
    # -------------------------------------------------
    result = run_single_case(
        case_file=str(case_file),
        overrides=overrides,
        output_file=str(output_file),
    )

    logger.info("Job {} - Case status: {}", hc.job.num, result.status)

    if result.status != "solved":
        logger.warning("Case did not solve; no output written.")
        return

    logger.info(
        "Job {} - Results saved to: {}",
        hc.job.num,
        output_file.relative_to(Path.cwd()),
    )


if __name__ == "__main__":
    main()
