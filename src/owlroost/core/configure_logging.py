# src/owlroost/core/configure_logging.py

import sys
from typing import Union

from loguru import logger

try:
    from omegaconf import DictConfig
except ImportError:  # pragma: no cover
    DictConfig = None

CURRENT_LOG_LEVEL: str | None = None  # noqa: F841

LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def configure_logging(
    log_level: Union[str, "DictConfig"] | None = "INFO",
):
    """
    Configure Loguru logging.

    Behavior:
      - If configured level >= INFO:
          * INFO / SUCCESS → short format
          * WARNING+ → full format
      - If configured level < INFO (DEBUG / TRACE):
          * All messages → full format
    """

    # ------------------------------------------------------------
    # Extract level from Hydra config if provided
    # ------------------------------------------------------------
    if DictConfig and isinstance(log_level, DictConfig):
        log_level = log_level.get("logging", {}).get("level", "INFO")

    if not log_level:
        return

    log_level = str(log_level).upper()

    if log_level not in LOG_LEVELS:
        raise ValueError(f"Invalid log level: {log_level}")

    # ------------------------------------------------------------
    # Reset Loguru handlers
    # ------------------------------------------------------------
    logger.remove()

    # ------------------------------------------------------------
    # Format function
    # ------------------------------------------------------------
    def dynamic_format(record):
        record_level = record["level"].name

        short = "<level>{level:8}</level> | <level>{message}</level>\n"
        full = (
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level:8}</level> | "
            "<cyan>{name}</cyan>:"
            "<cyan>{function}</cyan>:"
            "<cyan>{line}</cyan> - "
            "<level>{message}</level>\n"
        )

        # DEBUG / TRACE mode → always full
        if log_level in {"DEBUG", "TRACE"}:
            return full

        # INFO or higher → short for INFO/SUCCESS, full otherwise
        if record_level in {"INFO", "SUCCESS"}:
            return short

        return full

    # ------------------------------------------------------------
    # Add stderr handler
    # ------------------------------------------------------------

    CURRENT_LOG_LEVEL = log_level  # noqa: F841

    logger.add(
        sys.stderr,
        level=log_level,
        format=dynamic_format,
        backtrace=(log_level == "TRACE"),
        diagnose=(log_level == "TRACE"),
        enqueue=False,  # IMPORTANT for Hydra multiruns / multiprocessing
    )

    logger.debug("Loguru configured (level={})", log_level)
