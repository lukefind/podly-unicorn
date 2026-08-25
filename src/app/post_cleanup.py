"""Compatibility and scheduled entry points for episode storage cleanup."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from typing import Optional

from app.extensions import db, scheduler
from app.runtime_config import config as runtime_config
from app.storage_cleanup import run_storage_cleanup
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")
_cleanup_execution_lock = threading.Lock()


def cleanup_processed_posts(retention_days: Optional[int]) -> int:
    """Run storage reconciliation and return the legacy cleaned-episode count."""
    with _cleanup_execution_lock:
        return run_storage_cleanup(
            retention_days,
            trigger="compatibility",
        ).cleaned_count


def _runtime_retention_days() -> Optional[int]:
    return getattr(
        runtime_config,
        "post_cleanup_retention_days",
        DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
    )


def _run_scheduled_scope(
    feed_ids: Optional[Iterable[int]], *, trigger: str
) -> None:
    if scheduler.app is None:
        logger.warning("Cleanup skipped: scheduler has no associated app.")
        return

    try:
        with scheduler.app.app_context(), _cleanup_execution_lock:
            retention = _runtime_retention_days()
            if feed_ids is None:
                run_storage_cleanup(retention, trigger=trigger)
                return
            for feed_id in sorted(set(feed_ids)):
                try:
                    run_storage_cleanup(retention, feed_id=feed_id, trigger=trigger)
                except Exception as exc:  # pylint: disable=broad-except
                    db.session.rollback()
                    logger.error(
                        "Storage cleanup failed for feed %s: %s",
                        feed_id,
                        exc,
                        exc_info=True,
                    )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Storage cleanup failed: %s", exc, exc_info=True)


def scheduled_cleanup_processed_posts() -> None:
    """APScheduler entry point for the storage-cleanup coordinator."""

    _run_scheduled_scope(None, trigger="scheduled")


def immediate_cleanup_processed_posts(
    feed_ids: Optional[set[int]], *, trigger: str = "immediate"
) -> None:
    """Run one coalesced immediate server-wide or feed-scoped maintenance pass."""
    _run_scheduled_scope(feed_ids, trigger=trigger)
