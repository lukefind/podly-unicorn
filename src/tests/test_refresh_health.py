from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest import mock

import pytest
import requests
from flask import Flask


def test_refresh_health_tracks_sanitized_stale_cycle() -> None:
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth(stale_after_seconds=900)
    started_at = datetime(2026, 7, 20, 9, 0)

    assert tracker.try_start(started_at) is True
    tracker.set_current_feed(13)
    tracker.record_feed_error(
        13, requests.ReadTimeout("secret https://host.example/?token=x")
    )

    snapshot = tracker.snapshot(started_at + timedelta(minutes=16))

    assert snapshot["status"] == "stale"
    assert snapshot["last_error"] == "feed_13:ReadTimeout"
    assert "https://" not in json.dumps(snapshot)


def test_overlapping_start_does_not_modify_active_cycle() -> None:
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth()
    started_at = datetime(2026, 7, 20, 9, 0)
    assert tracker.try_start(started_at) is True
    tracker.set_current_feed(13)

    assert tracker.try_start(started_at + timedelta(minutes=1)) is False
    snapshot = tracker.snapshot(started_at + timedelta(minutes=1))
    assert snapshot["refresh_started_at"] == "2026-07-20T09:00:00Z"
    assert snapshot["current_feed_id"] == 13


def test_finish_records_only_completed_cycles() -> None:
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth()
    started_at = datetime(2026, 7, 20, 9, 0)
    completed_at = started_at + timedelta(minutes=2)
    assert tracker.try_start(started_at) is True
    tracker.finish(completed=False, now=completed_at)
    assert tracker.snapshot(completed_at)["last_completed_at"] is None

    assert tracker.try_start(completed_at) is True
    tracker.finish(completed=True, now=completed_at + timedelta(minutes=1))
    assert (
        tracker.snapshot(completed_at + timedelta(minutes=1))["last_completed_at"]
        == "2026-07-20T09:03:00Z"
    )


def test_health_route_returns_exact_fields_and_logs_stale_once() -> None:
    from app.refresh_health import RefreshHealth
    from app.routes import health_routes

    app = Flask(__name__)
    tracker = RefreshHealth(stale_after_seconds=0)
    health_routes.refresh_health = tracker
    app.register_blueprint(health_routes.health_bp)

    with mock.patch.object(health_routes.logger, "error") as log_error:
        with app.test_client() as client:
            idle = client.get("/health")
            assert idle.status_code == 200

            assert tracker.try_start(datetime.utcnow() - timedelta(seconds=1)) is True
            first = client.get("/health")
            second = client.get("/health")

    expected_fields = {
        "status",
        "refresh_running",
        "refresh_started_at",
        "current_feed_id",
        "last_completed_at",
        "last_error",
        "stale_after_seconds",
    }
    assert set(idle.get_json()) == expected_fields
    assert first.status_code == 503
    assert second.status_code == 503
    log_error.assert_called_once()


def _bare_manager():
    from app.jobs_manager import JobsManager

    manager = JobsManager.__new__(JobsManager)
    manager._cleanup_inconsistent_posts = mock.Mock()
    manager.enqueue_pending_jobs = mock.Mock(return_value={"status": "ok"})
    manager.start_post_processing = mock.Mock()
    return manager


def test_refresh_manager_rejects_overlap_without_querying_feeds(app) -> None:
    from app import jobs_manager
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth()
    assert tracker.try_start(datetime.utcnow()) is True
    manager = _bare_manager()

    with mock.patch.object(jobs_manager, "refresh_health", tracker), mock.patch.object(
        jobs_manager.scheduler, "app", app
    ), mock.patch.object(jobs_manager.Feed, "query") as feed_query:
        result = manager.start_refresh_all_feeds()

    assert result["status"] == "already_running"
    feed_query.all.assert_not_called()
    tracker.finish(completed=False)


def test_refresh_manager_records_successful_completion(app) -> None:
    from app import jobs_manager
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth()
    manager = _bare_manager()

    with mock.patch.object(jobs_manager, "refresh_health", tracker), mock.patch.object(
        jobs_manager.scheduler, "app", app
    ), mock.patch.object(jobs_manager.Feed, "query") as feed_query:
        feed_query.all.return_value = []
        result = manager.start_refresh_all_feeds()

    assert result == {"status": "ok"}
    assert tracker.snapshot()["last_completed_at"] is not None
    assert tracker.snapshot()["refresh_running"] is False


def test_refresh_manager_releases_cycle_after_cycle_level_error(app) -> None:
    from app import jobs_manager
    from app.refresh_health import RefreshHealth

    tracker = RefreshHealth()
    manager = _bare_manager()

    with mock.patch.object(jobs_manager, "refresh_health", tracker), mock.patch.object(
        jobs_manager.scheduler, "app", app
    ), mock.patch.object(jobs_manager.Feed, "query") as feed_query:
        feed_query.all.side_effect = RuntimeError("database unavailable")
        with pytest.raises(RuntimeError, match="database unavailable"):
            manager.start_refresh_all_feeds()

    snapshot = tracker.snapshot()
    assert snapshot["last_completed_at"] is None
    assert snapshot["refresh_running"] is False
    assert tracker.try_start() is True
    tracker.finish(completed=False)
