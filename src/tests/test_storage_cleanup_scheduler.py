"""Contracts for recurring and coalesced storage-maintenance scheduling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app import background, post_cleanup


@pytest.fixture(autouse=True)
def reset_dispatch_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background, "_pending_cleanup_feed_ids", set())
    monkeypatch.setattr(background, "_pending_cleanup_server_wide", False)
    monkeypatch.setattr(background, "_immediate_cleanup_pending", False)


@pytest.mark.parametrize("retention_days", [None, 0, -1])
def test_daily_storage_maintenance_is_scheduled_when_global_age_is_disabled(
    monkeypatch: pytest.MonkeyPatch, retention_days: int | None
) -> None:
    fake_scheduler = MagicMock()
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    background.schedule_cleanup_job(retention_days)

    fake_scheduler.add_job.assert_called_once()
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["id"] == background.DAILY_STORAGE_CLEANUP_JOB_ID
    assert kwargs["trigger"] == "interval"
    assert kwargs["hours"] == 24
    assert kwargs["replace_existing"] is True
    assert kwargs["coalesce"] is True


def test_disabled_scheduler_prevents_recurring_and_immediate_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = MagicMock()
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setenv("PODLY_DISABLE_SCHEDULER", "1")

    background.schedule_cleanup_job(14)
    status = background.request_storage_cleanup(feed_id=7)

    assert status == "scheduler_disabled"
    fake_scheduler.add_job.assert_not_called()


def test_scheduled_entry_reads_runtime_retention_when_it_executes(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_scheduler = MagicMock()
    fake_scheduler.app = app
    cleanup = MagicMock()
    monkeypatch.setattr(post_cleanup, "scheduler", fake_scheduler)
    monkeypatch.setattr(post_cleanup, "run_storage_cleanup", cleanup)
    monkeypatch.setattr(
        post_cleanup.runtime_config, "post_cleanup_retention_days", 31
    )

    post_cleanup.scheduled_cleanup_processed_posts()

    cleanup.assert_called_once_with(31, trigger="scheduled")


def test_feed_requests_coalesce_and_worker_receives_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setattr(background, "immediate_cleanup_processed_posts", dispatch)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    assert background.request_storage_cleanup(feed_id=7) == "queued"
    assert background.request_storage_cleanup(feed_id=9) == "coalesced"
    assert fake_scheduler.add_job.call_count == 1

    background.run_immediate_storage_cleanup()

    dispatch.assert_called_once_with({7, 9})


def test_global_request_escalates_pending_feed_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setattr(background, "immediate_cleanup_processed_posts", dispatch)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    assert background.request_storage_cleanup(feed_id=7) == "queued"
    assert background.request_storage_cleanup() == "coalesced"

    background.run_immediate_storage_cleanup()

    dispatch.assert_called_once_with(None)


def test_feed_request_after_pending_global_scope_stays_server_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = MagicMock()
    dispatch = MagicMock()
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setattr(background, "immediate_cleanup_processed_posts", dispatch)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    assert background.request_storage_cleanup() == "queued"
    assert background.request_storage_cleanup(feed_id=7) == "coalesced"

    background.run_immediate_storage_cleanup()

    dispatch.assert_called_once_with(None)


def test_request_arriving_during_worker_run_is_drained_without_a_second_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = MagicMock()
    scopes: list[set[int] | None] = []

    def dispatch(scope: set[int] | None) -> None:
        scopes.append(scope)
        if scope == {7}:
            assert background.request_storage_cleanup(feed_id=9) == "coalesced"

    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setattr(background, "immediate_cleanup_processed_posts", dispatch)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    assert background.request_storage_cleanup(feed_id=7) == "queued"
    background.run_immediate_storage_cleanup()

    assert scopes == [{7}, {9}]
    assert fake_scheduler.add_job.call_count == 1
    assert background._immediate_cleanup_pending is False


def test_immediate_worker_logs_exception_and_resets_pending_state(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_scheduler = MagicMock()
    dispatch = MagicMock(side_effect=RuntimeError("synthetic cleanup failure"))
    monkeypatch.setattr(background, "scheduler", fake_scheduler)
    monkeypatch.setattr(background, "immediate_cleanup_processed_posts", dispatch)
    monkeypatch.delenv("PODLY_DISABLE_SCHEDULER", raising=False)

    assert background.request_storage_cleanup(feed_id=7) == "queued"
    with caplog.at_level("ERROR", logger="global_logger"):
        background.run_immediate_storage_cleanup()

    assert "Immediate storage cleanup failed" in caplog.text
    assert background._immediate_cleanup_pending is False
