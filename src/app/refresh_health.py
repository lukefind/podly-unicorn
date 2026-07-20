from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional


class RefreshHealth:
    """Thread-safe liveness state and overlap guard for refresh-all cycles."""

    def __init__(self, stale_after_seconds: int = 900) -> None:
        self.stale_after_seconds = stale_after_seconds
        self._state_lock = Lock()
        self._cycle_lock = Lock()
        self._refresh_running = False
        self._refresh_started_at: Optional[datetime] = None
        self._current_feed_id: Optional[int] = None
        self._last_completed_at: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._stale_logged = False

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _as_utc_naive(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _serialize(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return f"{value.isoformat()}Z"

    def try_start(self, now: Optional[datetime] = None) -> bool:
        if not self._cycle_lock.acquire(blocking=False):
            return False
        started_at = self._as_utc_naive(now or self._now())
        with self._state_lock:
            self._refresh_running = True
            self._refresh_started_at = started_at
            self._current_feed_id = None
            self._last_error = None
            self._stale_logged = False
        return True

    def set_current_feed(self, feed_id: Optional[int]) -> None:
        with self._state_lock:
            self._current_feed_id = feed_id

    def record_feed_error(self, feed_id: Optional[int], error: Exception) -> None:
        with self._state_lock:
            self._last_error = f"feed_{feed_id}:{type(error).__name__}"

    def finish(self, completed: bool, now: Optional[datetime] = None) -> None:
        finished_at = self._as_utc_naive(now or self._now())
        with self._state_lock:
            if completed:
                self._last_completed_at = finished_at
            self._refresh_running = False
            self._current_feed_id = None
        self._cycle_lock.release()

    def _is_stale_locked(self, now: datetime) -> bool:
        return bool(
            self._refresh_running
            and self._refresh_started_at is not None
            and (now - self._refresh_started_at).total_seconds()
            > self.stale_after_seconds
        )

    def mark_stale_logged(self, now: Optional[datetime] = None) -> bool:
        checked_at = self._as_utc_naive(now or self._now())
        with self._state_lock:
            if not self._is_stale_locked(checked_at) or self._stale_logged:
                return False
            self._stale_logged = True
            return True

    def snapshot(self, now: Optional[datetime] = None) -> dict[str, Any]:
        checked_at = self._as_utc_naive(now or self._now())
        with self._state_lock:
            stale = self._is_stale_locked(checked_at)
            return {
                "status": "stale" if stale else "ok",
                "refresh_running": self._refresh_running,
                "refresh_started_at": self._serialize(self._refresh_started_at),
                "current_feed_id": self._current_feed_id,
                "last_completed_at": self._serialize(self._last_completed_at),
                "last_error": self._last_error,
                "stale_after_seconds": self.stale_after_seconds,
            }


refresh_health = RefreshHealth()
