# src/owlroost/hydra/owl_hydra_run.py
from multiprocessing import Pool
from pathlib import Path

import hydra
import numpy as np
from hydra.core.hydra_config import HydraConfig
from loguru import logger
from omegaconf import DictConfig, OmegaConf

from owlroost.cli.utils import normalize_case_file_overrides
from owlroost.core.configure_logging import configure_logging
from owlroost.core.override_parser import hydra_overrides_to_dict
from owlroost.core.owl_runner import run_single_case
from owlroost.hydra.helpers import (
    PROJECT_ROOT,
    bootstrap_logging,
    get_job_id,
    get_run_dir,
    register_resolvers,
    resolve_case_file,
    save_hydra_metadata,
)

# ---------------------------------------------------------------------
# Bootstrap (must run before Hydra)
# ---------------------------------------------------------------------

bootstrap_logging()
register_resolvers()


def fits_uint32(n: int) -> bool:
    return 0 <= n <= 0xFFFFFFFF


def _extract_trial_override(overrides: dict, key: str, default: int | None = None):
    try:
        return int(overrides.get("trial", {}).get(key, default))
    except Exception:
        return default


def _run_trial(
    trial_id: int,
    trial_seed: int | None,
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
    if trial_seed is not None:
        overrides.setdefault("rates", {})["rate_seed"] = trial_seed

    logger.info(
        "Trial {:04d} | seed={} | dir={}",
        trial_id,
        trial_seed if trial_seed is not None else "fromTOML",
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


@hydra.main(
    config_path="conf",
    config_name="config",
    version_base=None,
)
def main(cfg: DictConfig):
    """
    Pure Hydra runner for OWL scenarios.

    - Uses ./conf from the *current working directory*
    - Supports single runs and multiruns (-m)
    - Produces one output workbook per scenario
    - Supports internal trial replication with multiprocessing
    """

    # -------------------------------------------------
    # Validate required inputs
    # -------------------------------------------------
    if not hasattr(cfg, "case") or not hasattr(cfg.case, "file"):
        raise RuntimeError("Hydra config must define case.file")

    case_file = resolve_case_file(cfg.case.file)
    logger.debug(case_file)

    # -------------------------------------------------
    # Configure Loguru from Hydra config
    # -------------------------------------------------
    configure_logging(cfg)

    # -------------------------------------------------
    # Hydra runtime info (SAFE for single + multirun)
    # -------------------------------------------------
    hc = HydraConfig.get()
    raw_overrides = hc.overrides.task
    job_id = get_job_id(hc)

    if 0:
        hc_dict = OmegaConf.to_container(hc, resolve=True)
        logger.trace("HydraConfig dump:\n{}", OmegaConf.to_yaml(hc_dict))

    # -------------------------------------------------
    # Parse semantic overrides
    # -------------------------------------------------
    overrides = hydra_overrides_to_dict(raw_overrides)
    clean_overrides = normalize_case_file_overrides(raw_overrides)

    logger.info(
        "{} - overrides: {}",
        job_id,
        " ".join(clean_overrides),
    )

    # -------------------------------------------------
    # Hydra-managed run directory
    # -------------------------------------------------
    run_dir = get_run_dir()
    logger.info(
        "{} - Run directory: {}",
        job_id,
        run_dir.relative_to(PROJECT_ROOT),
    )

    # -------------------------------------------------
    # Save Hydra metadata
    # -------------------------------------------------
    save_hydra_metadata(
        run_dir=run_dir,
        mode=hc.mode,
        job_id=job_id,
        overrides=raw_overrides,
    )

    # -------------------------------------------------
    # Trial configuration
    # -------------------------------------------------

    trial_cfg = cfg.trial
    n_jobs = int(trial_cfg.n_jobs)

    # Extract semantic trial controls from overrides (NOT cfg)
    trial_id_override = _extract_trial_override(overrides, "id")
    trial_count_override = _extract_trial_override(
        overrides,
        "count",
        default=int(trial_cfg.count),
    )

    use_trial_seeds = trial_id_override is not None or trial_count_override > 1

    master_seed = 12345

    ss = np.random.SeedSequence(master_seed)
    trial_args = []

    # -------------------------------------------------
    # Single explicit trial (--trial-id)
    # -------------------------------------------------
    if trial_id_override is not None:
        trial_id = trial_id_override

        trial_seed = None
        if use_trial_seeds:
            trial_seqs = ss.spawn(trial_id + 1)
            trial_seed = int(trial_seqs[trial_id].generate_state(1)[0])

            logger.warning(f"Seed: {trial_seed}  fits in unit32: {fits_uint32( trial_seed )}")

        trial_args.append(
            (
                trial_id,
                trial_seed,
                case_file,
                overrides,
                run_dir,
            )
        )

        n_trials = 1

    elif trial_count_override == 1:
        trial_args.append(
            (
                0,
                None,  # ← no seed override
                case_file,
                overrides,
                run_dir,
            )
        )
        n_trials = 1

    # -------------------------------------------------
    # Normal multi-trial execution
    # -------------------------------------------------
    else:
        n_trials = trial_count_override
        trial_seqs = ss.spawn(n_trials)

        for i in range(n_trials):
            trial_seed = int(trial_seqs[i].generate_state(1)[0])
            logger.warning(f"Seed: {trial_seed}  fits in unit32: {fits_uint32( trial_seed )}")
            trial_args.append(
                (
                    i,
                    trial_seed,
                    case_file,
                    overrides,
                    run_dir,
                )
            )

    logger.info(
        "{} - Launching {} trials (n_jobs={})",
        job_id,
        n_trials,
        n_jobs,
    )

    # -------------------------------------------------
    # Run trials (parallel)
    # -------------------------------------------------
    if n_trials == 1:
        results = [_run_trial(*trial_args[0])]
    else:
        with Pool(processes=n_jobs) as pool:
            results = pool.starmap(_run_trial, trial_args)

    # -------------------------------------------------
    # Summary
    # -------------------------------------------------
    solved = [r for r in results if r["status"] == "solved"]
    failed = [r for r in results if r["status"] != "solved"]

    logger.info(
        "{} - Trials complete: {} solved, {} failed",
        job_id,
        len(solved),
        len(failed),
    )

    if failed:
        logger.warning(
            "{} - Failed trial IDs: {}",
            job_id,
            [r["trial_id"] for r in failed],
        )


if __name__ == "__main__":
    main()
