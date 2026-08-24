"""Compatibility and scheduled entry points for episode storage cleanup."""

from __future__ import annotations

import logging
from typing import Optional

from app.extensions import scheduler
from app.runtime_config import config as runtime_config
from app.storage_cleanup import run_storage_cleanup
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")


def cleanup_processed_posts(retention_days: Optional[int]) -> int:
    """Run storage reconciliation and return the legacy cleaned-episode count."""
    return run_storage_cleanup(
        retention_days,
        trigger="compatibility",
    ).cleaned_count


def scheduled_cleanup_processed_posts() -> None:
    """APScheduler entry point for the storage-cleanup coordinator."""
    retention = getattr(
        runtime_config,
        "post_cleanup_retention_days",
        DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
    )
    if scheduler.app is None:
        logger.warning("Cleanup skipped: scheduler has no associated app.")
        return

    try:
        with scheduler.app.app_context():
            run_storage_cleanup(retention, trigger="scheduled")
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Scheduled cleanup failed: %s", exc, exc_info=True)
