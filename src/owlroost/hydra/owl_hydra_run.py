# src/owlroost/hydra/owl_hydra_run.py

import time
from multiprocessing import Pool

import hydra
import numpy as np
from hydra.core.hydra_config import HydraConfig
from loguru import logger
from omegaconf import DictConfig
from tqdm import tqdm

from owlroost.cli.utils import normalize_case_file_overrides
from owlroost.core.configure_logging import configure_logging

# Longevity (GM model)
from owlroost.core.override_parser import hydra_overrides_to_dict
from owlroost.hydra.helpers import (
    PROJECT_ROOT,
    bootstrap_logging,
    get_job_id,
    get_run_dir,
    register_resolvers,
    resolve_case_file,
    save_hydra_metadata,
)
from owlroost.hydra.trial_worker import run_trial

# ---------------------------------------------------------------------
# Bootstrap (must run before Hydra initializes)
# ---------------------------------------------------------------------
bootstrap_logging()
register_resolvers()


def fits_uint32(n: int) -> bool:
    return 0 <= n <= 0xFFFFFFFF


def _extract_trial_override(overrides: dict, key: str, default: int | None = None):
    """Extract integer overrides from CLI parsed dict structure."""
    try:
        return int(overrides.get("trial", {}).get(key, default))
    except Exception:
        return default


# ---------------------------------------------------------------------
# MAIN HYDRA ENTRYPOINT
# ---------------------------------------------------------------------
@hydra.main(config_path="conf", config_name="config", version_base=None)
def main(cfg: DictConfig):
    # -----------------------------------------
    # Validate required inputs
    # -----------------------------------------
    if not hasattr(cfg, "case") or not hasattr(cfg.case, "file"):
        raise RuntimeError("Hydra config must define case.file")

    case_file = resolve_case_file(cfg.case.file)

    # Configure logging per Hydra
    configure_logging(cfg)

    # Hydra runtime and overrides
    hc = HydraConfig.get()
    raw_overrides = hc.overrides.task
    job_id = get_job_id(hc)

    overrides = hydra_overrides_to_dict(raw_overrides)
    clean_overrides = normalize_case_file_overrides(raw_overrides)

    logger.debug("{} - overrides: {}", job_id, " ".join(clean_overrides))

    run_dir = get_run_dir()
    logger.debug("{} - Run directory: {}", job_id, run_dir.relative_to(PROJECT_ROOT))

    save_hydra_metadata(
        run_dir=run_dir,
        mode=hc.mode,
        job_id=job_id,
        overrides=raw_overrides,
    )

    # -----------------------------------------
    # Trial configuration
    # -----------------------------------------
    trial_cfg = cfg.trial
    n_jobs = int(trial_cfg.n_jobs)

    trial_id_override = _extract_trial_override(overrides, "id")
    trial_count_override = _extract_trial_override(overrides, "count", default=int(trial_cfg.count))

    use_trial_seeds = trial_id_override is not None or trial_count_override > 1

    # MASTER seed for all trial seeds
    master_seed = 12345
    master_ss = np.random.SeedSequence(master_seed)

    trial_args = []

    # ============================================================
    # CASE 1 — single explicit trial: --trial-id=N
    # ============================================================
    if trial_id_override is not None:
        tid = trial_id_override

        rates_seed = None
        longevity_seed = None

        if use_trial_seeds:
            # Spawn (tid + 1) sequences since we need index tid
            seqs = master_ss.spawn(tid + 1)
            trial_ss = seqs[tid]

            rs, ls = trial_ss.spawn(2)
            rates_seed = int(rs.generate_state(1)[0])
            longevity_seed = int(ls.generate_state(1)[0])

        trial_args.append((job_id, tid, rates_seed, longevity_seed, case_file, overrides, run_dir))
        n_trials = 1

    # ============================================================
    # CASE 2 — single non-seeded run (no trial overrides)
    # ============================================================
    elif trial_count_override == 1:
        trial_args.append((job_id, 0, None, None, case_file, overrides, run_dir))
        n_trials = 1

    # ============================================================
    # CASE 3 — normal multi-trial execution
    # ============================================================
    else:
        n_trials = trial_count_override

        # Spawn all trial seeds at once
        trial_seqs = master_ss.spawn(n_trials)

        for tid in range(n_trials):
            trial_ss = trial_seqs[tid]

            # spawn two independent seeds: rates + longevity
            rs, ls = trial_ss.spawn(2)

            rates_seed = int(rs.generate_state(1)[0])
            longevity_seed = int(ls.generate_state(1)[0])

            logger.debug(f"Trial {tid:04d} seeds: rates={rates_seed}, longevity={longevity_seed}")

            trial_args.append(
                (job_id, tid, rates_seed, longevity_seed, case_file, overrides, run_dir)
            )

    logger.debug("{} - Launching {} trials (n_jobs={})", job_id, n_trials, n_jobs)

    # -------------------------------------------------------------
    # Run trials (parallel if needed)
    # -------------------------------------------------------------

    results = []
    completed = 0

    HEARTBEAT_SEC = 1
    last_update = time.monotonic()

    def _on_trial_done(result):
        results.append(result)

    if n_trials == 1:
        results = [run_trial(*trial_args[0])]
    else:
        with Pool(processes=n_jobs) as pool:
            async_results = [
                pool.apply_async(run_trial, args, callback=_on_trial_done) for args in trial_args
            ]
            async_results = async_results

            with tqdm(
                total=n_trials,
                desc=f"{job_id}",
                unit="trial",
                dynamic_ncols=True,
                bar_format="{desc}: {percentage:.1f}% |{bar}| {postfix}",
                # bar_format="{desc}: {percentage}% |{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] {postfix}",
            ) as pbar:
                while completed < n_trials:
                    newly_completed = len(results) - completed

                    if newly_completed:
                        completed += newly_completed
                        pbar.update(newly_completed)

                    # Heartbeat (continuous s/trial)
                    now = time.monotonic()
                    if now - last_update >= HEARTBEAT_SEC:
                        elapsed = pbar.format_dict["elapsed"] or 0.0
                        spt = elapsed / max(completed, 1)

                        pbar.set_postfix_str(
                            f"elapsed={elapsed:.1f}s, running={completed}/{n_trials}, s_per_trial={spt:.1f}s"
                        )
                        pbar.refresh()
                        last_update = now

                    time.sleep(0.2)

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    solved = [r for r in results if r["status"] == "solved"]
    failed = [r for r in results if r["status"] != "solved"]

    logger.info("{} - Trials complete: {} solved, {} failed", job_id, len(solved), len(failed))

    if failed:
        logger.warning(
            "{} - Failed trial IDs: {}",
            job_id,
            [r["trial_id"] for r in failed],
        )


if __name__ == "__main__":
    main()
