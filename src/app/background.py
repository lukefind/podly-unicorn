import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import scheduler
from app.post_cleanup import (
    immediate_cleanup_processed_posts,
    scheduled_cleanup_processed_posts,
)

logger = logging.getLogger("global_logger")

DAILY_STORAGE_CLEANUP_JOB_ID = "storage_cleanup_daily"
IMMEDIATE_STORAGE_CLEANUP_JOB_ID = "storage_cleanup_immediate"

_cleanup_scope_lock = threading.Lock()
_pending_cleanup_feed_ids: set[int] = set()
_pending_cleanup_server_wide = False
_immediate_cleanup_pending = False


def add_background_job(minutes: int) -> None:
    """Add the recurring background job for refreshing feeds.

    minutes: interval in minutes; must be a positive integer.
    """
    from app.jobs_manager import (  # pylint: disable=import-outside-toplevel
        scheduled_refresh_all_feeds,
    )

    scheduler.add_job(
        id="refresh_all_feeds",
        func=scheduled_refresh_all_feeds,
        trigger="interval",
        minutes=minutes,
        replace_existing=True,
    )


def schedule_cleanup_job(retention_days: Optional[int]) -> None:
    """Ensure daily storage maintenance exists, independent of age retention.

    ``retention_days`` remains in the signature for callers that update runtime
    configuration.  The scheduled entry point reads the current value when it
    executes; a disabled age policy must not disable count or orphan cleanup.
    """
    del retention_days
    if os.environ.get("PODLY_DISABLE_SCHEDULER") == "1":
        return

    scheduler.add_job(
        id=DAILY_STORAGE_CLEANUP_JOB_ID,
        func=scheduled_cleanup_processed_posts,
        trigger="interval",
        hours=24,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=15),
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )


def request_storage_cleanup(*, feed_id: Optional[int] = None) -> str:
    """Queue or coalesce an immediate cleanup request.

    Feed requests are unioned while a server-wide request supersedes every
    pending feed scope.  The process-local pending flag remains set while the
    date job is executing, so requests arriving during a run are drained by
    that same worker rather than starting an overlapping cleanup.
    """
    global _immediate_cleanup_pending  # pylint: disable=global-statement
    global _pending_cleanup_server_wide  # pylint: disable=global-statement

    if os.environ.get("PODLY_DISABLE_SCHEDULER") == "1":
        return "scheduler_disabled"

    with _cleanup_scope_lock:
        if feed_id is None:
            _pending_cleanup_server_wide = True
            _pending_cleanup_feed_ids.clear()
        elif not _pending_cleanup_server_wide:
            _pending_cleanup_feed_ids.add(feed_id)

        if _immediate_cleanup_pending:
            return "coalesced"

        _immediate_cleanup_pending = True
        try:
            scheduler.add_job(
                id=IMMEDIATE_STORAGE_CLEANUP_JOB_ID,
                func=run_immediate_storage_cleanup,
                trigger="date",
                run_date=datetime.now(timezone.utc) + timedelta(seconds=1),
                replace_existing=False,
                coalesce=True,
                max_instances=1,
            )
        except Exception:
            _immediate_cleanup_pending = False
            _pending_cleanup_server_wide = False
            _pending_cleanup_feed_ids.clear()
            logger.error("Unable to queue immediate storage cleanup", exc_info=True)
            raise
    return "queued"


def run_immediate_storage_cleanup() -> None:
    """Atomically drain every scope coalesced into the immediate date job."""
    global _immediate_cleanup_pending  # pylint: disable=global-statement
    global _pending_cleanup_server_wide  # pylint: disable=global-statement

    while True:
        with _cleanup_scope_lock:
            if _pending_cleanup_server_wide:
                scope: Optional[set[int]] = None
                _pending_cleanup_server_wide = False
                _pending_cleanup_feed_ids.clear()
            elif _pending_cleanup_feed_ids:
                scope = set(_pending_cleanup_feed_ids)
                _pending_cleanup_feed_ids.clear()
            else:
                _immediate_cleanup_pending = False
                return

        try:
            immediate_cleanup_processed_posts(scope)
        except Exception:  # pylint: disable=broad-except
            logger.error("Immediate storage cleanup failed", exc_info=True)
