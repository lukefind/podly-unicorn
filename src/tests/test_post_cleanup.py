from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import app.storage_cleanup as storage_cleanup_module
from app.extensions import db, scheduler
from app.jobs_manager_run_service import SINGLETON_RUN_ID
from app.models import (
    Feed,
    Identification,
    JobsManagerRun,
    ModelCall,
    Post,
    ProcessingJob,
    ProcessingStatistics,
    PromptPreset,
    TranscriptSegment,
    User,
    UserFeedSubscription,
)
from app.post_cleanup import cleanup_processed_posts, scheduled_cleanup_processed_posts
from app.storage_cleanup import is_valid_retention_count, run_storage_cleanup


@pytest.fixture
def data_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    in_root = data_root / "in"
    srv_root = data_root / "srv"
    in_root.mkdir(parents=True)
    srv_root.mkdir(parents=True)
    monkeypatch.setenv("PODLY_PODCAST_DATA_DIR", str(data_root))
    return in_root, srv_root


def _create_feed(suffix: str = "main", retention_count: object = None) -> Feed:
    feed = Feed(
        title=f"Test Feed {suffix}",
        rss_url=f"https://example.com/{suffix}.xml",
        processed_episode_retention_count=retention_count,
    )
    db.session.add(feed)
    db.session.flush()
    return feed


def _create_post(
    feed: Feed,
    guid: str,
    *,
    release_date: datetime | None,
    processed_path: Path | None = None,
    input_path: Path | None = None,
) -> Post:
    post = Post(
        feed_id=feed.id,
        guid=guid,
        download_url=f"https://example.com/{guid}.mp3",
        title=f"Episode {guid}",
        description="test",
        release_date=release_date,
        whitelisted=True,
        processed_audio_path=str(processed_path) if processed_path else None,
        unprocessed_audio_path=str(input_path) if input_path else None,
    )
    db.session.add(post)
    db.session.flush()
    return post


def _audio(path: Path, payload: bytes = b"audio") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _stale_attempt(
    in_root: Path,
    guid: str,
    job_id: str,
    *,
    payload: bytes = b"attempt-audio",
) -> tuple[Path, Path]:
    attempt = in_root / "jobs" / guid / job_id
    audio = _audio(attempt / "episode.mp3", payload)
    old = datetime.utcnow() - timedelta(hours=25)
    os.utime(audio, (old.timestamp(), old.timestamp()))
    os.utime(attempt, (old.timestamp(), old.timestamp()))
    os.utime(attempt.parent, (old.timestamp(), old.timestamp()))
    return attempt, audio


def _completed_job(
    post: Post, completed_at: datetime, *, feed_id: int | None = None
) -> ProcessingJob:
    job = ProcessingJob(
        id=f"job-{post.feed_id}-{post.guid}-{completed_at.timestamp()}",
        post_guid=post.guid,
        feed_id=post.feed_id if feed_id is None else feed_id,
        status="completed",
        current_step=4,
        total_steps=4,
        progress_percentage=100.0,
        created_at=completed_at,
        started_at=completed_at,
        completed_at=completed_at,
    )
    db.session.add(job)
    return job


def test_count_policy_keeps_newest_valid_outputs_after_reconciliation(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed(retention_count=2)
        now = datetime.utcnow()
        newest_missing = _create_post(
            feed,
            "newest-missing",
            release_date=now,
            processed_path=srv_root / "missing.mp3",
        )
        newest_valid = _create_post(
            feed,
            "newest-valid",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "newest-valid.mp3"),
        )
        promoted_valid = _create_post(
            feed,
            "promoted-valid",
            release_date=now - timedelta(days=2),
            processed_path=_audio(srv_root / "promoted-valid.mp3"),
        )
        old_valid = _create_post(
            feed,
            "old-valid",
            release_date=now - timedelta(days=3),
            processed_path=_audio(srv_root / "old-valid.mp3"),
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.expire_all()
        assert result.cleaned_count == 1
        assert newest_missing.processed_audio_path is None
        assert newest_valid.processed_audio_path is not None
        assert promoted_valid.processed_audio_path is not None
        assert old_valid.processed_audio_path is None
        assert not (srv_root / "old-valid.mp3").exists()


def test_orphan_sweep_only_removes_stale_exact_attempt_layout_when_age_disabled(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    attempt, _ = _stale_attempt(in_root, "orphan-guid", "missing-job")
    outside_layout = _audio(in_root / "legacy" / "old.mp3")
    jobs_root_file = _audio(in_root / "jobs" / "unknown.bin")
    guid_root_file = _audio(in_root / "jobs" / "malformed-guid" / "unknown.bin")

    with app.app_context():
        result = run_storage_cleanup(None, trigger="orphan-layout")

    assert not attempt.exists()
    assert not attempt.parent.exists()
    assert outside_layout.exists()
    assert jobs_root_file.exists()
    assert guid_root_file.exists()
    assert result.attempt_delete_attempts == 1
    assert result.attempts_removed == 1
    assert result.reclaimed_bytes == len(b"attempt-audio")
    assert result.unsafe_skips == 2


@pytest.mark.parametrize("status", ["pending", "running"])
def test_orphan_sweep_preserves_empty_guid_parent_with_active_job(
    app,
    data_roots: tuple[Path, Path],
    status: str,
) -> None:
    in_root, _ = data_roots
    guid = f"empty-active-{status}-guid"
    guid_parent = in_root / "jobs" / guid
    guid_parent.mkdir(parents=True)

    with app.app_context():
        db.session.add(
            ProcessingJob(
                id=f"empty-active-{status}-job",
                post_guid=guid,
                feed_id=None,
                status=status,
                created_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        run_storage_cleanup(None, trigger=f"empty-active-{status}")

    assert guid_parent.exists()


def test_feed_scoped_orphan_sweep_removes_only_allowed_empty_guid_parent(
    app,
    data_roots: tuple[Path, Path],
) -> None:
    in_root, _ = data_roots
    jobs_root = in_root / "jobs"
    allowed_parent = jobs_root / "empty-allowed-guid"
    out_of_scope_parent = jobs_root / "empty-out-of-scope-guid"
    ambiguous_parent = jobs_root / "empty-ambiguous-guid"
    for parent in (allowed_parent, out_of_scope_parent, ambiguous_parent):
        parent.mkdir(parents=True)

    with app.app_context():
        target_feed = _create_feed("empty-scope-target")
        other_feed = _create_feed("empty-scope-other")
        _create_post(
            target_feed, "empty-allowed-guid", release_date=datetime.utcnow()
        )
        _create_post(
            other_feed, "empty-out-of-scope-guid", release_date=datetime.utcnow()
        )
        _create_post(
            target_feed, "empty-ambiguous-guid", release_date=datetime.utcnow()
        )
        _create_post(
            other_feed, "empty-ambiguous-guid", release_date=datetime.utcnow()
        )
        db.session.commit()

        result = run_storage_cleanup(
            None, feed_id=target_feed.id, trigger="empty-feed-scope"
        )

    assert not allowed_parent.exists()
    assert out_of_scope_parent.exists()
    assert ambiguous_parent.exists()
    assert any("empty-ambiguous-guid" in warning for warning in result.warnings)


def test_orphan_sweep_preserves_all_attempts_for_active_same_guid_job(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    active_attempt, _ = _stale_attempt(in_root, "active-guid", "active-job")
    retry_attempt, _ = _stale_attempt(in_root, "active-guid", "old-retry")

    with app.app_context():
        db.session.add(
            ProcessingJob(
                id="active-job",
                post_guid="active-guid",
                feed_id=None,
                status="running",
                created_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-active")

    assert active_attempt.exists()
    assert retry_attempt.exists()
    assert result.active_skips == 2
    assert result.attempt_delete_attempts == 0


def test_orphan_sweep_removes_only_old_failed_or_cancelled_job_attempts(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    statuses = ("failed", "cancelled", "completed", "skipped", "mystery")
    attempts = {
        status: _stale_attempt(in_root, f"{status}-guid", f"{status}-job")[0]
        for status in statuses
    }

    with app.app_context():
        old = datetime.utcnow() - timedelta(days=2)
        db.session.add_all(
            [
                ProcessingJob(
                    id=f"{status}-job",
                    post_guid=f"{status}-guid",
                    feed_id=None,
                    status=status,
                    created_at=old,
                    completed_at=old,
                )
                for status in statuses
            ]
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-terminal")

    assert not attempts["failed"].exists()
    assert not attempts["cancelled"].exists()
    assert attempts["completed"].exists()
    assert attempts["skipped"].exists()
    assert attempts["mystery"].exists()
    assert result.attempts_removed == 2


def test_orphan_sweep_preserves_recent_filesystem_and_recent_terminal_job(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    recent_filesystem = in_root / "jobs" / "recent-fs-guid" / "missing-job"
    _audio(recent_filesystem / "episode.mp3")
    recent_job_attempt, _ = _stale_attempt(
        in_root, "recent-job-guid", "recent-failed-job"
    )

    with app.app_context():
        db.session.add(
            ProcessingJob(
                id="recent-failed-job",
                post_guid="recent-job-guid",
                feed_id=None,
                status="failed",
                created_at=datetime.utcnow() - timedelta(hours=1),
                completed_at=datetime.utcnow() - timedelta(hours=1),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-grace")

    assert recent_filesystem.exists()
    assert recent_job_attempt.exists()
    assert result.grace_skips == 2
    assert result.attempt_delete_attempts == 0


def test_orphan_sweep_preserves_referenced_input_for_valid_processed_output(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "retained-output-guid", "failed-final"
    )

    with app.app_context():
        feed = _create_feed("orphan-retained-output")
        post = _create_post(
            feed,
            "retained-output-guid",
            release_date=datetime.utcnow(),
            processed_path=_audio(srv_root / "retained-output.mp3"),
            input_path=input_path,
        )
        db.session.add(
            ProcessingJob(
                id="failed-final",
                post_guid=post.guid,
                feed_id=feed.id,
                status="failed",
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-retained-output")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(input_path)
        assert post.processed_audio_path is not None

    assert attempt.exists()
    assert input_path.exists()
    assert result.attempts_removed == 0


def test_orphan_sweep_removes_stale_failed_referenced_input_and_clears_pointer(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "failed-reference-guid", "failed-reference-job"
    )

    with app.app_context():
        feed = _create_feed("orphan-failed-reference")
        post = _create_post(
            feed,
            "failed-reference-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        db.session.add(
            ProcessingJob(
                id="failed-reference-job",
                post_guid=post.guid,
                feed_id=feed.id,
                status="failed",
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-failed-reference")

        db.session.refresh(post)
        assert post.unprocessed_audio_path is None

    assert not attempt.exists()
    assert result.attempts_removed == 1


def test_orphan_sweep_preserves_shared_guid_mapping_as_ambiguous(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "shared-orphan-guid", "shared-failed-job"
    )

    with app.app_context():
        target_feed = _create_feed("orphan-shared-target")
        other_feed = _create_feed("orphan-shared-other")
        target = _create_post(
            target_feed,
            "shared-orphan-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        _create_post(
            other_feed,
            "shared-orphan-guid",
            release_date=datetime.utcnow(),
        )
        db.session.add(
            ProcessingJob(
                id="shared-failed-job",
                post_guid=target.guid,
                feed_id=target_feed.id,
                status="failed",
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-shared-guid")

        db.session.refresh(target)
        assert target.unprocessed_audio_path == str(input_path)

    assert attempt.exists()
    assert result.ambiguous_skips == 1
    assert any("ambiguous" in warning for warning in result.warnings)


def test_orphan_sweep_preserves_mismatched_path_reference_as_ambiguous(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "filesystem-guid", "mismatched-reference-job"
    )

    with app.app_context():
        feed = _create_feed("orphan-mismatched-reference")
        post = _create_post(
            feed,
            "different-post-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        db.session.add(
            ProcessingJob(
                id="mismatched-reference-job",
                post_guid="filesystem-guid",
                feed_id=feed.id,
                status="failed",
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-mismatched-reference")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(input_path)

    assert attempt.exists()
    assert result.ambiguous_skips == 1
    assert any("ambiguous" in warning for warning in result.warnings)


def test_orphan_sweep_rejects_guid_parent_swap_before_attempt_deletion(
    app,
    data_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, _ = data_roots
    guid = "swapped-orphan-guid"
    job_id = "swapped-orphan-job"
    attempt, input_path = _stale_attempt(in_root, guid, job_id, payload=b"inside")
    guid_parent = attempt.parent
    parked_parent = in_root / "jobs" / f"{guid}-parked"
    outside_parent = tmp_path / "outside-orphan-guid"
    outside_file = _audio(outside_parent / job_id / "episode.mp3", b"outside")
    original_stat = os.stat
    guid_stats = 0

    def swap_on_guid_revalidation(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal guid_stats
        if path == guid and kwargs.get("dir_fd") is not None:
            guid_stats += 1
            if guid_stats == 2:
                guid_parent.rename(parked_parent)
                guid_parent.symlink_to(outside_parent, target_is_directory=True)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", swap_on_guid_revalidation)

    with app.app_context():
        result = run_storage_cleanup(None, trigger="orphan-parent-swap")

    assert guid_stats >= 2
    assert (parked_parent / job_id / input_path.name).read_bytes() == b"inside"
    assert outside_file.read_bytes() == b"outside"
    assert result.attempts_removed == 0
    assert result.unsafe_skips == 1


def test_orphan_sweep_preserves_file_changed_in_place_before_unlink(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "changed-orphan-guid", "changed-orphan-job", payload=b"original"
    )
    original_stat = os.stat
    file_stats = 0

    def change_file_on_revalidation(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal file_stats
        if path == input_path.name and kwargs.get("dir_fd") is not None:
            file_stats += 1
            if file_stats == 2:
                input_path.write_bytes(b"replacement-content")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", change_file_on_revalidation)

    with app.app_context():
        result = run_storage_cleanup(None, trigger="orphan-file-change")

    assert file_stats >= 2
    assert attempt.exists()
    assert input_path.read_bytes() == b"replacement-content"
    assert result.attempts_removed == 0
    assert result.failed_count == 1
    assert result.unsafe_skips == 1
    assert result.skipped_count == 1


def test_orphan_sweep_retries_pointer_clear_after_database_commit_failure(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "orphan-db-retry-guid", "orphan-db-retry-job"
    )

    with app.app_context():
        feed = _create_feed("orphan-db-retry")
        post = _create_post(
            feed,
            "orphan-db-retry-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        db.session.add(
            ProcessingJob(
                id="orphan-db-retry-job",
                post_guid=post.guid,
                feed_id=feed.id,
                status="failed",
                created_at=datetime.utcnow() - timedelta(days=2),
                completed_at=datetime.utcnow() - timedelta(days=2),
            )
        )
        db.session.commit()
        session = db.session()
        original_commit = session.commit

        def fail_commit() -> None:
            raise RuntimeError("synthetic orphan commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        first = run_storage_cleanup(None, trigger="orphan-db-failure")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(input_path)
        assert not attempt.exists()
        assert first.attempts_removed == 1
        assert first.failed_count == 1
        assert any("retry" in error for error in first.errors)

        monkeypatch.setattr(session, "commit", original_commit)
        second = run_storage_cleanup(None, trigger="orphan-db-retry")

        db.session.refresh(post)
        assert post.unprocessed_audio_path is None
        assert second.failed_count == 0


def test_orphan_sweep_retries_jobless_pointer_clear_after_database_commit_failure(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "jobless-db-retry-guid", "jobless-db-retry-attempt"
    )

    with app.app_context():
        feed = _create_feed("jobless-db-retry")
        post = _create_post(
            feed,
            "jobless-db-retry-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        db.session.commit()
        session = db.session()
        original_commit = session.commit

        def fail_commit() -> None:
            raise RuntimeError("synthetic jobless pointer commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        first = run_storage_cleanup(None, trigger="jobless-db-failure")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(input_path)
        assert not attempt.exists()
        assert first.attempts_removed == 1
        assert first.failed_count == 1

        monkeypatch.setattr(session, "commit", original_commit)
        second = run_storage_cleanup(None, trigger="jobless-db-retry")

        db.session.refresh(post)
        assert post.unprocessed_audio_path is None
        assert second.attempts_removed == 0
        assert second.failed_count == 0


def test_orphan_sweep_feed_scope_removes_only_safely_attributable_attempts(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, _ = data_roots
    target_attempt, _ = _stale_attempt(in_root, "target-scope-guid", "target-scope-job")
    other_attempt, _ = _stale_attempt(in_root, "other-scope-guid", "other-scope-job")
    unknown_attempt, _ = _stale_attempt(
        in_root, "unknown-scope-guid", "unknown-scope-job"
    )

    with app.app_context():
        target_feed = _create_feed("orphan-scope-target")
        other_feed = _create_feed("orphan-scope-other")
        target_post = _create_post(
            target_feed, "target-scope-guid", release_date=datetime.utcnow()
        )
        other_post = _create_post(
            other_feed, "other-scope-guid", release_date=datetime.utcnow()
        )
        old = datetime.utcnow() - timedelta(days=2)
        db.session.add_all(
            [
                ProcessingJob(
                    id="target-scope-job",
                    post_guid=target_post.guid,
                    feed_id=target_feed.id,
                    status="failed",
                    created_at=old,
                    completed_at=old,
                ),
                ProcessingJob(
                    id="other-scope-job",
                    post_guid=other_post.guid,
                    feed_id=other_feed.id,
                    status="cancelled",
                    created_at=old,
                    completed_at=old,
                ),
            ]
        )
        db.session.commit()

        result = run_storage_cleanup(
            None, feed_id=target_feed.id, trigger="orphan-feed-scope"
        )

    assert not target_attempt.exists()
    assert other_attempt.exists()
    assert unknown_attempt.exists()
    assert result.attempts_removed == 1
    assert result.ambiguous_skips == 1
    assert any("ambiguous" in warning for warning in result.warnings)


def test_orphan_sweep_preserves_symlink_attempts_and_symlink_contents(
    app, data_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    in_root, _ = data_roots
    jobs_root = in_root / "jobs"
    outside_attempt = tmp_path / "outside-attempt"
    outside_file = _audio(outside_attempt / "outside.mp3", b"outside")
    linked_attempt = jobs_root / "linked-guid" / "linked-job"
    linked_attempt.parent.mkdir(parents=True)
    linked_attempt.symlink_to(outside_attempt, target_is_directory=True)

    nested_attempt, _ = _stale_attempt(in_root, "nested-link-guid", "nested-link-job")
    nested_link = nested_attempt / "escape.mp3"
    nested_link.symlink_to(outside_file)

    with app.app_context():
        result = run_storage_cleanup(None, trigger="orphan-symlinks")

    assert linked_attempt.is_symlink()
    assert nested_link.is_symlink()
    assert outside_file.read_bytes() == b"outside"
    assert result.attempts_removed == 0
    assert result.unsafe_skips == 2


def test_orphan_sweep_unlink_failure_preserves_retryable_post_pointer(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, _ = data_roots
    attempt, input_path = _stale_attempt(
        in_root, "orphan-unlink-guid", "orphan-unlink-job"
    )

    with app.app_context():
        feed = _create_feed("orphan-unlink")
        post = _create_post(
            feed,
            "orphan-unlink-guid",
            release_date=datetime.utcnow(),
            input_path=input_path,
        )
        old = datetime.utcnow() - timedelta(days=2)
        db.session.add(
            ProcessingJob(
                id="orphan-unlink-job",
                post_guid=post.guid,
                feed_id=feed.id,
                status="cancelled",
                created_at=old,
                completed_at=old,
            )
        )
        db.session.commit()
        original_unlink = os.unlink

        def fail_attempt_unlink(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *args: object,
            **kwargs: object,
        ) -> None:
            if path == input_path.name and kwargs.get("dir_fd") is not None:
                raise OSError("synthetic orphan unlink failure")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", fail_attempt_unlink)
        result = run_storage_cleanup(None, trigger="orphan-unlink-failure")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(input_path)

    assert attempt.exists()
    assert input_path.exists()
    assert result.attempt_delete_attempts == 1
    assert result.attempts_removed == 0
    assert result.failed_count == 1
    assert result.reclaimed_bytes == 0


def test_orphan_sweep_merges_one_summary_when_global_age_is_disabled(
    app,
    data_roots: tuple[Path, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, _ = data_roots
    _stale_attempt(in_root, "summary-stale-guid", "summary-stale-job", payload=b"1234")
    recent_attempt = in_root / "jobs" / "summary-recent-guid" / "recent-job"
    _audio(recent_attempt / "episode.mp3")
    _audio(in_root / "jobs" / "summary-unknown.bin")

    with app.app_context(), caplog.at_level(logging.INFO, logger="global_logger"):
        result = run_storage_cleanup(None, trigger="orphan-summary")

    summaries = [
        json.loads(record.getMessage().removeprefix("storage_cleanup_summary "))
        for record in caplog.records
        if record.getMessage().startswith("storage_cleanup_summary ")
    ]
    assert len(summaries) == 1
    payload = summaries[0]
    assert payload["attempt_delete_attempts"] == 1
    assert payload["attempts_removed"] == 1
    assert payload["reclaimed_bytes"] == 4
    assert payload["grace_skips"] == 1
    assert payload["unsafe_skips"] == 1
    assert result.to_dict() == payload


def test_orphan_summary_counts_each_preserved_attempt_as_one_generic_skip(
    app,
    data_roots: tuple[Path, Path],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, _ = data_roots
    active_attempt, _ = _stale_attempt(
        in_root, "summary-active-guid", "summary-active-job"
    )
    recent_attempt = in_root / "jobs" / "summary-grace-guid" / "summary-grace-job"
    _audio(recent_attempt / "episode.mp3")
    ambiguous_attempt, _ = _stale_attempt(
        in_root, "summary-ambiguous-guid", "summary-ambiguous-job"
    )
    unsafe_attempt, _ = _stale_attempt(
        in_root, "summary-unsafe-guid", "summary-unsafe-job"
    )
    outside = _audio(tmp_path / "outside-summary.mp3")
    (unsafe_attempt / "escape.mp3").symlink_to(outside)

    with app.app_context(), caplog.at_level(logging.INFO, logger="global_logger"):
        first_feed = _create_feed("summary-ambiguous-first")
        second_feed = _create_feed("summary-ambiguous-second")
        _create_post(
            first_feed,
            "summary-ambiguous-guid",
            release_date=datetime.utcnow(),
        )
        _create_post(
            second_feed,
            "summary-ambiguous-guid",
            release_date=datetime.utcnow(),
        )
        old = datetime.utcnow() - timedelta(days=2)
        db.session.add_all(
            [
                ProcessingJob(
                    id="summary-active-job",
                    post_guid="summary-active-guid",
                    feed_id=None,
                    status="running",
                    created_at=old,
                ),
                ProcessingJob(
                    id="summary-ambiguous-job",
                    post_guid="summary-ambiguous-guid",
                    feed_id=first_feed.id,
                    status="failed",
                    created_at=old,
                    completed_at=old,
                ),
            ]
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="orphan-skip-summary")

    assert active_attempt.exists()
    assert recent_attempt.exists()
    assert ambiguous_attempt.exists()
    assert unsafe_attempt.exists()
    assert result.active_skips == 1
    assert result.grace_skips == 1
    assert result.ambiguous_skips == 1
    assert result.unsafe_skips == 1
    assert result.skipped_count == 4
    summaries = [
        json.loads(record.getMessage().removeprefix("storage_cleanup_summary "))
        for record in caplog.records
        if record.getMessage().startswith("storage_cleanup_summary ")
    ]
    assert len(summaries) == 1
    assert summaries[0]["skipped_count"] == 4


def test_global_age_uses_newer_of_successful_job_and_processed_file_mtime(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed()
        now = datetime.utcnow()
        recreated_path = _audio(srv_root / "recreated.mp3")
        old_path = _audio(srv_root / "old.mp3")
        old_timestamp = now - timedelta(days=10)
        recent_timestamp = now - timedelta(days=1)
        recreated_path.touch()
        old_epoch = old_timestamp.timestamp()
        os.utime(
            recreated_path, (recent_timestamp.timestamp(), recent_timestamp.timestamp())
        )
        os.utime(old_path, (old_epoch, old_epoch))
        recreated = _create_post(
            feed,
            "recreated",
            release_date=old_timestamp,
            processed_path=recreated_path,
        )
        expired = _create_post(
            feed,
            "expired",
            release_date=old_timestamp,
            processed_path=old_path,
        )
        _completed_job(recreated, old_timestamp)
        _completed_job(expired, old_timestamp)
        db.session.commit()

        result = run_storage_cleanup(5, trigger="test")

        db.session.expire_all()
        assert result.cleaned_count == 1
        assert recreated.processed_audio_path is not None
        assert expired.processed_audio_path is None


@pytest.mark.parametrize(
    "value",
    [None, True, False, 0, -1, 1.5, "2", 2_147_483_648],
)
def test_invalid_values_are_not_count_policies(value: object) -> None:
    assert not is_valid_retention_count(value)


def test_eligible_cleanup_preserves_episode_metadata_and_removes_derived_artifacts(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed(retention_count=1)
        user = User(username="listener", password_hash="hash", role="user")
        db.session.add(user)
        db.session.flush()
        subscription = UserFeedSubscription(user_id=user.id, feed_id=feed.id)
        db.session.add(subscription)
        preset = PromptPreset(
            name="cleanup-test",
            system_prompt="system",
            user_prompt_template="user",
        )
        db.session.add(preset)
        db.session.flush()
        now = datetime.utcnow()
        _create_post(
            feed,
            "retained",
            release_date=now,
            processed_path=_audio(srv_root / "retained.mp3"),
        )
        old_input = _audio(in_root / "old-input.mp3", b"input")
        old_output = _audio(srv_root / "old-output.mp3", b"processed")
        old = _create_post(
            feed,
            "eligible",
            release_date=now - timedelta(days=1),
            processed_path=old_output,
            input_path=old_input,
        )
        old.processed_with_preset_id = preset.id
        old.refined_ad_boundaries = {"start": 1.5}
        old.refined_ad_boundaries_updated_at = now
        model_call = ModelCall(
            post_id=old.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            response="response",
            status="completed",
        )
        segment = TranscriptSegment(
            post_id=old.id,
            sequence_num=0,
            start_time=0.0,
            end_time=1.0,
            text="ad",
        )
        db.session.add_all([model_call, segment])
        db.session.flush()
        db.session.add_all(
            [
                Identification(
                    transcript_segment_id=segment.id,
                    model_call_id=model_call.id,
                    confidence=0.9,
                    label="ad",
                ),
                ProcessingStatistics(
                    post_id=old.id,
                    total_ad_segments_removed=1,
                    total_duration_removed_seconds=1.0,
                    original_duration_seconds=2.0,
                    processed_duration_seconds=1.0,
                    percentage_removed=50.0,
                ),
            ]
        )
        _completed_job(old, now - timedelta(days=1))
        preserved = {
            "feed_id": old.feed_id,
            "guid": old.guid,
            "download_url": old.download_url,
            "title": old.title,
            "description": old.description,
            "release_date": old.release_date,
            "whitelisted": old.whitelisted,
        }
        post_id = old.id
        subscription_id = subscription.id
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.expire_all()
        cleaned_post = db.session.get(Post, post_id)
        assert cleaned_post is not None
        assert {key: getattr(cleaned_post, key) for key in preserved} == preserved
        assert db.session.get(Feed, feed.id) is not None
        assert db.session.get(UserFeedSubscription, subscription_id) is not None
        assert cleaned_post.processed_audio_path is None
        assert cleaned_post.unprocessed_audio_path is None
        assert cleaned_post.processed_with_preset_id is None
        assert cleaned_post.refined_ad_boundaries is None
        assert cleaned_post.refined_ad_boundaries_updated_at is None
        assert TranscriptSegment.query.filter_by(post_id=post_id).count() == 0
        assert ModelCall.query.filter_by(post_id=post_id).count() == 0
        assert Identification.query.count() == 0
        assert ProcessingStatistics.query.filter_by(post_id=post_id).count() == 0
        assert ProcessingJob.query.filter_by(post_guid="eligible").count() == 0
        assert not old_input.exists()
        assert not old_output.exists()
        assert result.cleaned_count == 1


def test_active_job_sharing_guid_blocks_cleanup_across_feeds(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        target_feed = _create_feed("target", retention_count=1)
        other_feed = _create_feed("other")
        now = datetime.utcnow()
        _create_post(
            target_feed,
            "retained",
            release_date=now,
            processed_path=_audio(srv_root / "retained-active-test.mp3"),
        )
        target = _create_post(
            target_feed,
            "shared-guid",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "blocked.mp3"),
        )
        _create_post(other_feed, "shared-guid", release_date=now)
        db.session.add(
            ProcessingJob(
                id="other-feed-active",
                post_guid="shared-guid",
                feed_id=other_feed.id,
                status="running",
                current_step=2,
                total_steps=4,
                progress_percentage=50.0,
                created_at=now,
                started_at=now,
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(target)
        assert target.processed_audio_path is not None
        assert (srv_root / "blocked.mp3").exists()
        assert (
            ProcessingJob.query.filter_by(id="other-feed-active").one().status
            == "running"
        )
        assert result.cleaned_count == 0
        assert result.active_skips == 1


def test_terminal_jobs_are_feed_scoped_and_ambiguous_legacy_rows_are_preserved(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        target_feed = _create_feed("target-terminal", retention_count=1)
        other_feed = _create_feed("other-terminal")
        now = datetime.utcnow()
        _create_post(
            target_feed,
            "new-terminal",
            release_date=now,
            processed_path=_audio(srv_root / "new-terminal.mp3"),
        )
        target = _create_post(
            target_feed,
            "shared-terminal",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "old-terminal.mp3"),
        )
        _create_post(other_feed, "shared-terminal", release_date=now)
        completed_at = now - timedelta(days=2)
        db.session.add_all(
            [
                ProcessingJob(
                    id="target-terminal-job",
                    post_guid=target.guid,
                    feed_id=target_feed.id,
                    status="completed",
                    completed_at=completed_at,
                ),
                ProcessingJob(
                    id="other-terminal-job",
                    post_guid=target.guid,
                    feed_id=other_feed.id,
                    status="failed",
                    completed_at=completed_at,
                ),
                ProcessingJob(
                    id="ambiguous-legacy-job",
                    post_guid=target.guid,
                    feed_id=None,
                    status="completed",
                    completed_at=completed_at,
                ),
            ]
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        assert db.session.get(ProcessingJob, "target-terminal-job") is None
        assert db.session.get(ProcessingJob, "other-terminal-job") is not None
        assert db.session.get(ProcessingJob, "ambiguous-legacy-job") is not None
        assert result.ambiguous_skips == 1
        assert any("ambiguous" in warning for warning in result.warnings)


def test_missing_input_with_valid_retained_output_clears_only_input_pointer(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("missing-input", retention_count=1)
        post = _create_post(
            feed,
            "missing-input-guid",
            release_date=datetime.utcnow(),
            processed_path=_audio(srv_root / "valid-output.mp3"),
            input_path=in_root / "missing-input.mp3",
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.unprocessed_audio_path is None
        assert post.processed_audio_path is not None
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0


def test_cleanup_eligible_missing_output_finishes_derived_cleanup(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("eligible-missing-output", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "new-valid-output",
            release_date=now,
            processed_path=_audio(srv_root / "new-valid-output.mp3"),
        )
        input_path = _audio(in_root / "retry-input.mp3")
        post = _create_post(
            feed,
            "eligible-missing-output",
            release_date=now - timedelta(days=1),
            processed_path=srv_root / "already-gone.mp3",
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path is None
        assert post.unprocessed_audio_path is None
        assert db.session.get(ModelCall, model_call_id) is None
        assert not input_path.exists()
        assert result.cleaned_count == 1


def test_disabled_policy_reconciles_missing_output_without_removing_reusable_state(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("disabled-missing-output")
        input_path = _audio(in_root / "reusable-input.mp3")
        post = _create_post(
            feed,
            "disabled-missing-output",
            release_date=datetime.utcnow(),
            processed_path=srv_root / "missing-disabled-output.mp3",
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path is None
        assert post.unprocessed_audio_path == str(input_path)
        assert input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert any("missing processed" in warning for warning in result.warnings)


def test_path_escape_is_preserved_and_reported_unsafe(
    app, data_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("unsafe-path", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "safe-retained",
            release_date=now,
            processed_path=_audio(srv_root / "safe-retained.mp3"),
        )
        escaped = _audio(tmp_path / "outside.mp3")
        post = _create_post(
            feed,
            "unsafe-candidate",
            release_date=now - timedelta(days=1),
            processed_path=escaped,
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path == str(escaped)
        assert escaped.exists()
        assert result.cleaned_count == 0
        assert result.unsafe_skips == 1
        assert result.skipped_count == 1


def test_database_failure_rolls_back_and_reports_retryable_partial_state(
    app, data_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("db-failure", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "db-retained",
            release_date=now,
            processed_path=_audio(srv_root / "db-retained.mp3"),
        )
        output = _audio(srv_root / "db-failure.mp3")
        post = _create_post(
            feed,
            "db-failure",
            release_date=now - timedelta(days=1),
            processed_path=output,
        )
        post_id = post.id
        db.session.commit()
        session = db.session()

        def fail_commit() -> None:
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)

        result = run_storage_cleanup(None, trigger="test")

        restored = db.session.get(Post, post_id)
        assert restored is not None
        assert restored.processed_audio_path == str(output)
        assert not output.exists()
        assert result.cleaned_count == 0
        assert result.failed_count == 1
        assert any("retry" in error for error in result.errors)


def test_cleanup_repairs_affected_explicit_run_and_singleton_counters(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("run-repair", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "run-retained",
            release_date=now,
            processed_path=_audio(srv_root / "run-retained.mp3"),
        )
        target = _create_post(
            feed,
            "run-cleaned",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "run-cleaned.mp3"),
        )
        explicit = JobsManagerRun(
            id="cleanup-explicit-run",
            status="running",
            trigger="manual",
            total_jobs=1,
            completed_jobs=1,
            counters_reset_at=now - timedelta(days=2),
        )
        singleton = JobsManagerRun(
            id=SINGLETON_RUN_ID,
            status="running",
            trigger="scheduler",
            total_jobs=7,
            queued_jobs=7,
            counters_reset_at=now - timedelta(days=2),
        )
        db.session.add_all([explicit, singleton])
        db.session.add(
            ProcessingJob(
                id="run-cleaned-job",
                jobs_manager_run_id=explicit.id,
                post_guid=target.guid,
                feed_id=feed.id,
                status="completed",
                created_at=now - timedelta(days=1),
                completed_at=now - timedelta(days=1),
            )
        )
        db.session.commit()

        run_storage_cleanup(None, trigger="test")

        db.session.refresh(explicit)
        db.session.refresh(singleton)
        assert explicit.status == "completed"
        assert explicit.total_jobs == 0
        assert singleton.status == "idle"
        assert singleton.total_jobs == 0


def test_legacy_cleanup_entrypoint_delegates_without_deleting_posts(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("compatibility", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "compat-retained",
            release_date=now,
            processed_path=_audio(srv_root / "compat-retained.mp3"),
        )
        cleaned = _create_post(
            feed,
            "compat-cleaned",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "compat-cleaned.mp3"),
        )
        cleaned_id = cleaned.id
        db.session.commit()

        removed = cleanup_processed_posts(retention_days=None)

        assert removed == 1
        assert db.session.get(Post, cleaned_id) is not None
        assert db.session.get(Post, cleaned_id).processed_audio_path is None


def test_feed_scoped_run_emits_exactly_one_structured_summary(
    app,
    data_roots: tuple[Path, Path],
    caplog: pytest.LogCaptureFixture,
) -> None:
    del data_roots
    with app.app_context(), caplog.at_level(logging.INFO, logger="global_logger"):
        feed = _create_feed("summary")
        db.session.commit()
        feed_id = feed.id

        run_storage_cleanup(None, feed_id=feed_id, trigger="feed-scoped")

    summaries = [
        record.getMessage().removeprefix("storage_cleanup_summary ")
        for record in caplog.records
        if record.getMessage().startswith("storage_cleanup_summary ")
    ]
    assert len(summaries) == 1
    payload = json.loads(summaries[0])
    assert payload["trigger"] == "feed-scoped"
    assert payload["scope"] == {"feed_id": feed_id}
    assert payload["policies"] == [{"feed_id": feed_id, "policy": "disabled"}]
    assert {
        "policies",
        "candidates",
        "episodes_cleaned",
        "active_skips",
        "ambiguous_skips",
        "unsafe_skips",
        "grace_skips",
        "files_removed",
        "attempts_removed",
        "reclaimed_bytes",
        "warnings",
        "errors",
    }.issubset(payload)


def test_unique_legacy_job_timestamp_is_attributable_for_age_cleanup(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("unique-legacy-age")
        old = datetime.utcnow() - timedelta(days=10)
        input_path = _audio(in_root / "unique-legacy-input.mp3")
        post = _create_post(
            feed,
            "unique-legacy-guid",
            release_date=old,
            processed_path=srv_root / "unique-legacy-missing.mp3",
            input_path=input_path,
        )
        db.session.add(
            ProcessingJob(
                id="unique-legacy-completed",
                post_guid=post.guid,
                feed_id=None,
                status="completed",
                created_at=old,
                completed_at=old,
            )
        )
        db.session.commit()

        result = run_storage_cleanup(5, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path is None
        assert post.unprocessed_audio_path is None
        assert db.session.get(ProcessingJob, "unique-legacy-completed") is None
        assert result.cleaned_count == 1


def test_symlinked_parent_is_rejected_even_when_it_resolves_inside_root(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    real_dir = srv_root / "real"
    real_dir.mkdir()
    target = _audio(real_dir / "target.mp3")
    alias_dir = srv_root / "alias"
    alias_dir.symlink_to(real_dir, target_is_directory=True)
    with app.app_context():
        feed = _create_feed("symlink-parent", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "symlink-retained",
            release_date=now,
            processed_path=_audio(srv_root / "symlink-retained.mp3"),
        )
        post = _create_post(
            feed,
            "symlink-candidate",
            release_date=now - timedelta(days=1),
            processed_path=alias_dir / "target.mp3",
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path == str(alias_dir / "target.mp3")
        assert target.exists()
        assert result.unsafe_skips == 1


def test_unlink_failure_preserves_failed_pointer_and_derived_state(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("unlink-failure", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "unlink-retained",
            release_date=now,
            processed_path=_audio(srv_root / "unlink-retained.mp3"),
        )
        input_path = _audio(in_root / "unlink-input.mp3")
        output_path = _audio(srv_root / "unlink-output.mp3")
        post = _create_post(
            feed,
            "unlink-failure",
            release_date=now - timedelta(days=1),
            processed_path=output_path,
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()
        original_unlink = os.unlink

        def selective_unlink(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *args: object,
            **kwargs: object,
        ) -> None:
            if path == output_path.name and kwargs.get("dir_fd") is not None:
                raise OSError("synthetic unlink failure")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", selective_unlink)

        with caplog.at_level(logging.INFO, logger="global_logger"):
            result = run_storage_cleanup(None, trigger="partial-failure")

        db.session.refresh(post)
        assert post.processed_audio_path == str(output_path)
        assert post.unprocessed_audio_path is None
        assert output_path.exists()
        assert not input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert result.failed_count == 1
        assert (
            sum(
                record.getMessage().startswith("storage_cleanup_summary ")
                for record in caplog.records
            )
            == 1
        )


def test_database_failure_for_one_episode_does_not_abort_other_candidates(
    app, data_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("isolated-db-failure", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "isolated-retained",
            release_date=now,
            processed_path=_audio(srv_root / "isolated-retained.mp3"),
        )
        first_output = _audio(srv_root / "isolated-first.mp3")
        first = _create_post(
            feed,
            "isolated-first",
            release_date=now - timedelta(days=1),
            processed_path=first_output,
        )
        second = _create_post(
            feed,
            "isolated-second",
            release_date=now - timedelta(days=2),
            processed_path=_audio(srv_root / "isolated-second.mp3"),
        )
        first_id = first.id
        second_id = second.id
        db.session.commit()
        session = db.session()
        original_commit = session.commit
        calls = 0

        def fail_first_commit() -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("first episode commit failed")
            original_commit()

        monkeypatch.setattr(session, "commit", fail_first_commit)

        result = run_storage_cleanup(None, trigger="test")

        first_after = db.session.get(Post, first_id)
        second_after = db.session.get(Post, second_id)
        assert first_after is not None
        assert second_after is not None
        assert first_after.processed_audio_path == str(first_output)
        assert second_after.processed_audio_path is None
        assert result.cleaned_count == 1
        assert result.failed_count == 1


def test_age_cleanup_skips_when_no_processed_timestamp_is_trustworthy(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("untrusted-age")
        input_path = _audio(in_root / "untrusted-input.mp3")
        post = _create_post(
            feed,
            "untrusted-age",
            release_date=datetime.utcnow() - timedelta(days=30),
            processed_path=srv_root / "untrusted-missing-output.mp3",
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()

        result = run_storage_cleanup(5, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path is None
        assert post.unprocessed_audio_path == str(input_path)
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert result.skipped_count == 1
        assert any("trustworthy" in warning for warning in result.warnings)


def test_count_order_is_release_desc_nulls_last_then_id_desc(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("ordering", retention_count=3)
        release = datetime.utcnow()
        dated_first = _create_post(
            feed,
            "dated-first",
            release_date=release,
            processed_path=_audio(srv_root / "dated-first.mp3"),
        )
        dated_second = _create_post(
            feed,
            "dated-second",
            release_date=release,
            processed_path=_audio(srv_root / "dated-second.mp3"),
        )
        null_first = _create_post(
            feed,
            "null-first",
            release_date=None,
            processed_path=_audio(srv_root / "null-first.mp3"),
        )
        null_second = _create_post(
            feed,
            "null-second",
            release_date=None,
            processed_path=_audio(srv_root / "null-second.mp3"),
        )
        db.session.commit()

        run_storage_cleanup(None, trigger="test")

        for retained in (dated_first, dated_second, null_second):
            db.session.refresh(retained)
            assert retained.processed_audio_path is not None
        db.session.refresh(null_first)
        assert null_first.processed_audio_path is None


def test_unsafe_input_preflight_prevents_deleting_safe_output(
    app, data_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("unsafe-input", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "unsafe-input-retained",
            release_date=now,
            processed_path=_audio(srv_root / "unsafe-input-retained.mp3"),
        )
        output = _audio(srv_root / "unsafe-input-output.mp3")
        outside_input = _audio(tmp_path / "outside-input.mp3")
        post = _create_post(
            feed,
            "unsafe-input-candidate",
            release_date=now - timedelta(days=1),
            processed_path=output,
            input_path=outside_input,
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path == str(output)
        assert post.unprocessed_audio_path == str(outside_input)
        assert output.exists()
        assert outside_input.exists()
        assert result.cleaned_count == 0
        assert result.unsafe_skips == 1


def test_age_policy_reports_unsafe_processed_path_without_mutation(
    app, data_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    del data_roots
    with app.app_context():
        feed = _create_feed("unsafe-age")
        outside = _audio(tmp_path / "unsafe-age.mp3")
        post = _create_post(
            feed,
            "unsafe-age",
            release_date=datetime.utcnow() - timedelta(days=30),
            processed_path=outside,
        )
        _completed_job(post, datetime.utcnow() - timedelta(days=30))
        db.session.commit()

        result = run_storage_cleanup(5, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path == str(outside)
        assert outside.exists()
        assert result.unsafe_skips == 1


def test_scheduled_entrypoint_emits_one_scheduled_summary(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del data_roots
    with app.app_context():
        _create_feed("scheduled-summary")
        db.session.commit()
    monkeypatch.setattr(scheduler, "app", app)

    with caplog.at_level(logging.INFO, logger="global_logger"):
        scheduled_cleanup_processed_posts()

    summaries = [
        json.loads(record.getMessage().removeprefix("storage_cleanup_summary "))
        for record in caplog.records
        if record.getMessage().startswith("storage_cleanup_summary ")
    ]
    assert len(summaries) == 1
    assert summaries[0]["trigger"] == "scheduled"


def test_non_null_count_override_excludes_feed_from_global_age_policy(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        count_feed = _create_feed("count-overrides-age", retention_count=1)
        inherited_feed = _create_feed("inherits-age")
        old = datetime.utcnow() - timedelta(days=30)
        count_post = _create_post(
            count_feed,
            "count-old",
            release_date=old,
            processed_path=_audio(srv_root / "count-old.mp3"),
        )
        inherited_post = _create_post(
            inherited_feed,
            "inherited-old",
            release_date=old,
            processed_path=_audio(srv_root / "inherited-old.mp3"),
        )
        os.utime(
            srv_root / "inherited-old.mp3",
            (old.timestamp(), old.timestamp()),
        )
        _completed_job(count_post, old)
        _completed_job(inherited_post, old)
        db.session.commit()

        run_storage_cleanup(5, trigger="test")

        db.session.refresh(count_post)
        db.session.refresh(inherited_post)
        assert count_post.processed_audio_path is not None
        assert inherited_post.processed_audio_path is None


def test_non_positive_global_age_remains_disabled_for_compatibility(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("zero-age")
        output = _audio(srv_root / "zero-age.mp3")
        post = _create_post(
            feed,
            "zero-age",
            release_date=datetime.utcnow() - timedelta(days=30),
            processed_path=output,
        )
        _completed_job(post, datetime.utcnow() - timedelta(days=30))
        db.session.commit()

        removed = cleanup_processed_posts(0)

        db.session.refresh(post)
        assert removed == 0
        assert post.processed_audio_path == str(output)
        assert output.exists()


def test_file_disappearing_during_unlink_is_confirmed_absent_and_cleared(
    app, data_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("unlink-race", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "unlink-race-retained",
            release_date=now,
            processed_path=_audio(srv_root / "unlink-race-retained.mp3"),
        )
        output = _audio(srv_root / "unlink-race-output.mp3")
        post = _create_post(
            feed,
            "unlink-race",
            release_date=now - timedelta(days=1),
            processed_path=output,
        )
        db.session.commit()
        original_unlink = os.unlink

        def disappear_then_raise(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *args: object,
            **kwargs: object,
        ) -> None:
            if path == output.name and kwargs.get("dir_fd") is not None:
                original_unlink(path, *args, **kwargs)
                raise FileNotFoundError(str(path))
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", disappear_then_raise)

        result = run_storage_cleanup(None, trigger="test")

        db.session.refresh(post)
        assert post.processed_audio_path is None
        assert result.cleaned_count == 1
        assert result.failed_count == 0


def test_count_candidates_keep_provisional_release_order_after_reconciliation(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("candidate-order", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "candidate-order-retained",
            release_date=now,
            processed_path=_audio(srv_root / "candidate-order-retained.mp3"),
        )
        valid = _create_post(
            feed,
            "candidate-order-valid",
            release_date=now - timedelta(days=1),
            processed_path=_audio(srv_root / "candidate-order-valid.mp3"),
        )
        missing = _create_post(
            feed,
            "candidate-order-missing",
            release_date=now - timedelta(days=2),
            processed_path=srv_root / "candidate-order-missing.mp3",
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="test")

        assert result.candidate_post_ids == [valid.id, missing.id]


def test_input_unlink_failure_keeps_output_selectable_for_next_run(
    app, data_roots: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("input-retry", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "input-retry-retained",
            release_date=now,
            processed_path=_audio(srv_root / "input-retry-retained.mp3"),
        )
        input_path = _audio(in_root / "input-retry.mp3")
        output_path = _audio(srv_root / "output-retry.mp3")
        post = _create_post(
            feed,
            "input-retry-candidate",
            release_date=now - timedelta(days=1),
            processed_path=output_path,
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        model_call_id = model_call.id
        db.session.commit()
        original_unlink = os.unlink
        failed_once = False

        def fail_input_once(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal failed_once
            if (
                path == input_path.name
                and kwargs.get("dir_fd") is not None
                and not failed_once
            ):
                failed_once = True
                raise OSError("synthetic input unlink failure")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", fail_input_once)

        first_result = run_storage_cleanup(None, trigger="first-pass")

        db.session.refresh(post)
        assert first_result.cleaned_count == 0
        assert first_result.failed_count == 1
        assert post.unprocessed_audio_path == str(input_path)
        assert post.processed_audio_path == str(output_path)
        assert input_path.exists()
        assert output_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None

        second_result = run_storage_cleanup(None, trigger="second-pass")

        db.session.refresh(post)
        assert second_result.cleaned_count == 1
        assert post.unprocessed_audio_path is None
        assert post.processed_audio_path is None
        assert not input_path.exists()
        assert not output_path.exists()
        assert db.session.get(ModelCall, model_call_id) is None


def test_per_post_database_exception_does_not_abort_later_candidate_or_summary(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("post-exception", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "post-exception-retained",
            release_date=now,
            processed_path=_audio(srv_root / "post-exception-retained.mp3"),
        )
        first_output = _audio(srv_root / "post-exception-first.mp3")
        first = _create_post(
            feed,
            "post-exception-first",
            release_date=now - timedelta(days=1),
            processed_path=first_output,
        )
        second = _create_post(
            feed,
            "post-exception-second",
            release_date=now - timedelta(days=2),
            processed_path=_audio(srv_root / "post-exception-second.mp3"),
        )
        first_id = first.id
        second_id = second.id
        db.session.commit()
        original_delete = storage_cleanup_module._delete_derived_records
        calls = 0

        def fail_first_delete(post: Post, result: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("synthetic derived-row failure")
            original_delete(post, result)

        monkeypatch.setattr(
            storage_cleanup_module, "_delete_derived_records", fail_first_delete
        )

        with caplog.at_level(logging.INFO, logger="global_logger"):
            result = run_storage_cleanup(None, trigger="post-exception")

        first_after = db.session.get(Post, first_id)
        second_after = db.session.get(Post, second_id)
        assert first_after is not None
        assert second_after is not None
        assert first_after.processed_audio_path == str(first_output)
        assert not first_output.exists()
        assert second_after.processed_audio_path is None
        assert result.failed_count == 1
        assert result.cleaned_count == 1
        assert any("synthetic derived-row failure" in error for error in result.errors)
        assert (
            sum(
                record.getMessage().startswith("storage_cleanup_summary ")
                for record in caplog.records
            )
            == 1
        )


def test_stat_race_preserves_episode_and_does_not_abort_later_candidate(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("stat-race", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "stat-race-retained",
            release_date=now,
            processed_path=_audio(srv_root / "stat-race-retained.mp3"),
        )
        first_output = _audio(srv_root / "stat-race-first.mp3")
        first = _create_post(
            feed,
            "stat-race-first",
            release_date=now - timedelta(days=1),
            processed_path=first_output,
        )
        second = _create_post(
            feed,
            "stat-race-second",
            release_date=now - timedelta(days=2),
            processed_path=_audio(srv_root / "stat-race-second.mp3"),
        )
        first_id = first.id
        second_id = second.id
        db.session.commit()
        original_stat = os.stat

        def fail_cleanup_stat(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            *args: object,
            **kwargs: object,
        ):
            if (
                path == first_output.name
                and kwargs.get("dir_fd") is not None
                and kwargs.get("follow_symlinks") is False
            ):
                raise PermissionError("synthetic stat race")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", fail_cleanup_stat)

        with caplog.at_level(logging.INFO, logger="global_logger"):
            result = run_storage_cleanup(None, trigger="stat-race")

        first_after = db.session.get(Post, first_id)
        second_after = db.session.get(Post, second_id)
        assert first_after is not None
        assert second_after is not None
        assert first_after.processed_audio_path == str(first_output)
        assert first_output.exists()
        assert second_after.processed_audio_path is None
        assert result.failed_count == 1
        assert result.cleaned_count == 1
        assert result.files_removed == 1
        assert any("synthetic stat race" in error for error in result.errors)
        assert (
            sum(
                record.getMessage().startswith("storage_cleanup_summary ")
                for record in caplog.records
            )
            == 1
        )


def test_active_work_on_retained_missing_input_records_one_skip(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("retained-active-input", retention_count=1)
        now = datetime.utcnow()
        missing_input = in_root / "retained-active-missing-input.mp3"
        post = _create_post(
            feed,
            "retained-active-input",
            release_date=now,
            processed_path=_audio(srv_root / "retained-active-output.mp3"),
            input_path=missing_input,
        )
        db.session.add(
            ProcessingJob(
                id="retained-active-input-job",
                post_guid=post.guid,
                feed_id=feed.id,
                status="running",
                current_step=2,
                total_steps=4,
                progress_percentage=50.0,
                created_at=now,
                started_at=now,
            )
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="retained-active-input")

        db.session.refresh(post)
        assert post.unprocessed_audio_path == str(missing_input)
        assert result.cleaned_count == 0
        assert result.failed_count == 0
        assert result.skipped_count == 1
        assert result.active_skips == 1


def test_age_missing_output_with_active_work_records_one_skip(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("age-active-missing")
        now = datetime.utcnow()
        missing_output = srv_root / "age-active-missing.mp3"
        post = _create_post(
            feed,
            "age-active-missing",
            release_date=now - timedelta(days=30),
            processed_path=missing_output,
        )
        db.session.add(
            ProcessingJob(
                id="age-active-missing-job",
                post_guid=post.guid,
                feed_id=feed.id,
                status="running",
                current_step=2,
                total_steps=4,
                progress_percentage=50.0,
                created_at=now,
                started_at=now,
            )
        )
        db.session.commit()

        result = run_storage_cleanup(5, trigger="age-active-missing")

        db.session.refresh(post)
        assert post.processed_audio_path == str(missing_output)
        assert result.cleaned_count == 0
        assert result.failed_count == 0
        assert result.skipped_count == 1
        assert result.active_skips == 1


def test_age_evaluation_failure_does_not_abort_later_candidate_or_summary(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("age-evaluation-failure")
        old = datetime.utcnow() - timedelta(days=30)
        first_output = _audio(srv_root / "age-evaluation-first.mp3")
        second_output = _audio(srv_root / "age-evaluation-second.mp3")
        os.utime(first_output, (old.timestamp(), old.timestamp()))
        os.utime(second_output, (old.timestamp(), old.timestamp()))
        first = _create_post(
            feed,
            "age-evaluation-first",
            release_date=old,
            processed_path=first_output,
        )
        second = _create_post(
            feed,
            "age-evaluation-second",
            release_date=old,
            processed_path=second_output,
        )
        first_id = first.id
        second_id = second.id
        db.session.commit()
        original_latest = storage_cleanup_module._latest_successful_completion

        def fail_first_evaluation(post: Post):
            if post.id == first_id:
                raise RuntimeError("synthetic age evaluation failure")
            return original_latest(post)

        monkeypatch.setattr(
            storage_cleanup_module,
            "_latest_successful_completion",
            fail_first_evaluation,
        )

        with caplog.at_level(logging.INFO, logger="global_logger"):
            result = run_storage_cleanup(5, trigger="age-evaluation-failure")

        first_after = db.session.get(Post, first_id)
        second_after = db.session.get(Post, second_id)
        assert first_after is not None
        assert second_after is not None
        assert first_after.processed_audio_path == str(first_output)
        assert first_output.exists()
        assert second_after.processed_audio_path is None
        assert not second_output.exists()
        assert result.failed_count == 1
        assert result.cleaned_count == 1
        assert any(
            "synthetic age evaluation failure" in error for error in result.errors
        )
        assert (
            sum(
                record.getMessage().startswith("storage_cleanup_summary ")
                for record in caplog.records
            )
            == 1
        )


def test_count_reconciliation_failure_does_not_abort_later_feed_or_summary(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        first_feed = _create_feed("count-reconciliation-failure", retention_count=1)
        now = datetime.utcnow()
        missing_input = in_root / "count-reconciliation-missing-input.mp3"
        first = _create_post(
            first_feed,
            "count-reconciliation-first",
            release_date=now,
            processed_path=_audio(srv_root / "count-reconciliation-first.mp3"),
            input_path=missing_input,
        )
        later_feed = _create_feed("count-reconciliation-later", retention_count=1)
        _create_post(
            later_feed,
            "count-reconciliation-retained",
            release_date=now,
            processed_path=_audio(srv_root / "count-reconciliation-retained.mp3"),
        )
        later_output = _audio(srv_root / "count-reconciliation-later.mp3")
        later = _create_post(
            later_feed,
            "count-reconciliation-later",
            release_date=now - timedelta(days=1),
            processed_path=later_output,
        )
        first_id = first.id
        later_id = later.id
        db.session.commit()
        original_active_skip = storage_cleanup_module._record_active_skip

        def fail_first_query(post: Post, result: object) -> bool:
            if post.id == first_id:
                raise RuntimeError("synthetic count reconciliation query failure")
            return original_active_skip(post, result)

        monkeypatch.setattr(
            storage_cleanup_module, "_record_active_skip", fail_first_query
        )

        with caplog.at_level(logging.INFO, logger="global_logger"):
            result = run_storage_cleanup(None, trigger="count-reconciliation-failure")

        first_after = db.session.get(Post, first_id)
        later_after = db.session.get(Post, later_id)
        assert first_after is not None
        assert later_after is not None
        assert first_after.unprocessed_audio_path == str(missing_input)
        assert later_after.processed_audio_path is None
        assert not later_output.exists()
        assert result.failed_count == 1
        assert result.cleaned_count == 1
        assert any(
            "synthetic count reconciliation query failure" in error
            for error in result.errors
        )
        assert (
            sum(
                record.getMessage().startswith("storage_cleanup_summary ")
                for record in caplog.records
            )
            == 1
        )


def test_same_feed_shared_processed_file_is_preserved_for_retained_post(
    app, data_roots: tuple[Path, Path]
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("shared-processed", retention_count=1)
        now = datetime.utcnow()
        shared_output = _audio(srv_root / "shared-processed.mp3")
        retained = _create_post(
            feed,
            "shared-processed-retained",
            release_date=now,
            processed_path=shared_output,
        )
        cleaned = _create_post(
            feed,
            "shared-processed-cleaned",
            release_date=now - timedelta(days=1),
            processed_path=shared_output,
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="shared-processed")

        db.session.refresh(retained)
        db.session.refresh(cleaned)
        assert cleaned.processed_audio_path is None
        assert retained.processed_audio_path == str(shared_output)
        assert shared_output.exists()
        assert result.cleaned_count == 1
        assert result.files_removed == 0


def test_cross_feed_shared_input_file_is_preserved_for_other_post(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        target_feed = _create_feed("shared-input-target", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            target_feed,
            "shared-input-retained",
            release_date=now,
            processed_path=_audio(srv_root / "shared-input-retained.mp3"),
        )
        shared_input = _audio(in_root / "shared-input.mp3")
        target_output = _audio(srv_root / "shared-input-target.mp3")
        target = _create_post(
            target_feed,
            "shared-input-target",
            release_date=now - timedelta(days=1),
            processed_path=target_output,
            input_path=shared_input,
        )
        other_feed = _create_feed("shared-input-other")
        other = _create_post(
            other_feed,
            "shared-input-other",
            release_date=now,
            input_path=shared_input,
        )
        db.session.commit()

        result = run_storage_cleanup(None, trigger="shared-input")

        db.session.refresh(target)
        db.session.refresh(other)
        assert target.unprocessed_audio_path is None
        assert target.processed_audio_path is None
        assert other.unprocessed_audio_path == str(shared_input)
        assert shared_input.exists()
        assert not target_output.exists()
        assert result.cleaned_count == 1
        assert result.files_removed == 1


def test_age_expired_missing_output_cleans_remaining_input_and_derived_state(
    app, data_roots: tuple[Path, Path]
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("age-missing-expired")
        old = datetime.utcnow() - timedelta(days=30)
        input_path = _audio(in_root / "age-missing-expired-input.mp3")
        post = _create_post(
            feed,
            "age-missing-expired",
            release_date=old,
            processed_path=srv_root / "age-missing-expired-output.mp3",
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        job = _completed_job(post, old)
        db.session.add(model_call)
        db.session.flush()
        post_id = post.id
        model_call_id = model_call.id
        job_id = job.id
        db.session.commit()

        result = run_storage_cleanup(5, trigger="age-missing-expired")

        cleaned = db.session.get(Post, post_id)
        assert cleaned is not None
        assert cleaned.processed_audio_path is None
        assert cleaned.unprocessed_audio_path is None
        assert not input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is None
        assert db.session.get(ProcessingJob, job_id) is None
        assert result.selected_count == 1
        assert result.cleaned_count == 1


def test_age_missing_output_retries_after_filesystem_success_and_database_rollback(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    in_root, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("age-missing-rollback")
        old = datetime.utcnow() - timedelta(days=30)
        input_path = _audio(in_root / "age-missing-rollback-input.mp3")
        missing_output = srv_root / "age-missing-rollback-output.mp3"
        post = _create_post(
            feed,
            "age-missing-rollback",
            release_date=old,
            processed_path=missing_output,
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        _completed_job(post, old)
        db.session.add(model_call)
        db.session.flush()
        post_id = post.id
        model_call_id = model_call.id
        db.session.commit()
        session = db.session()
        original_commit = session.commit
        failed_once = False

        def fail_first_commit() -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("synthetic age retry rollback")
            original_commit()

        monkeypatch.setattr(session, "commit", fail_first_commit)

        first_result = run_storage_cleanup(5, trigger="age-missing-rollback-first")

        first_after = db.session.get(Post, post_id)
        assert first_after is not None
        assert first_after.processed_audio_path == str(missing_output)
        assert first_after.unprocessed_audio_path == str(input_path)
        assert not input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert first_result.failed_count == 1
        assert first_result.cleaned_count == 0

        second_result = run_storage_cleanup(5, trigger="age-missing-rollback-second")

        second_after = db.session.get(Post, post_id)
        assert second_after is not None
        assert second_after.processed_audio_path is None
        assert second_after.unprocessed_audio_path is None
        assert db.session.get(ModelCall, model_call_id) is None
        assert second_result.selected_count == 1
        assert second_result.cleaned_count == 1


@pytest.mark.parametrize("new_retention_count", [None, 2])
def test_feed_policy_change_after_selection_prevents_stale_count_deletion(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    new_retention_count: int | None,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("stale-policy", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "stale-policy-retained",
            release_date=now,
            processed_path=_audio(srv_root / "stale-policy-retained.mp3"),
        )
        target_output = _audio(srv_root / "stale-policy-target.mp3")
        target = _create_post(
            feed,
            "stale-policy-target",
            release_date=now - timedelta(days=1),
            processed_path=target_output,
        )
        model_call = ModelCall(
            post_id=target.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        target_id = target.id
        feed_id = feed.id
        model_call_id = model_call.id
        db.session.commit()
        original_cleanup = storage_cleanup_module._cleanup_candidate_and_commit
        policy_changed = False

        def change_policy_before_cleanup(
            post: Post, result: object, global_retention_days: int | None
        ) -> None:
            nonlocal policy_changed
            if post.id == target_id and not policy_changed:
                policy_changed = True
                db.session.query(Feed).filter(Feed.id == feed_id).update(
                    {Feed.processed_episode_retention_count: new_retention_count}
                )
                db.session.commit()
            original_cleanup(post, result, global_retention_days)

        monkeypatch.setattr(
            storage_cleanup_module,
            "_cleanup_candidate_and_commit",
            change_policy_before_cleanup,
        )

        result = run_storage_cleanup(None, trigger="stale-policy")

        after = db.session.get(Post, target_id)
        assert after is not None
        assert after.processed_audio_path == str(target_output)
        assert target_output.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert result.skipped_count == 1


def test_parent_swap_before_unlink_cannot_delete_outside_file(
    app,
    data_roots: tuple[Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("parent-swap", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "parent-swap-retained",
            release_date=now,
            processed_path=_audio(srv_root / "parent-swap-retained.mp3"),
        )
        inside_parent = srv_root / "swappable-parent"
        inside_output = _audio(inside_parent / "episode.mp3", b"inside")
        parked_parent = srv_root / "swappable-parent-original"
        outside_parent = tmp_path / "outside-parent"
        outside_output = _audio(outside_parent / "episode.mp3", b"outside")
        target = _create_post(
            feed,
            "parent-swap-target",
            release_date=now - timedelta(days=1),
            processed_path=inside_output,
        )
        target_id = target.id
        db.session.commit()
        original_open = os.open
        swapped = False

        def swap_parent_on_descriptor_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            nonlocal swapped
            if path == "swappable-parent" and dir_fd is not None and not swapped:
                inside_parent.rename(parked_parent)
                inside_parent.symlink_to(outside_parent, target_is_directory=True)
                swapped = True
            return original_open(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, "open", swap_parent_on_descriptor_open)

        result = run_storage_cleanup(None, trigger="parent-swap")

        after = db.session.get(Post, target_id)
        assert after is not None
        assert swapped is True
        assert after.processed_audio_path == str(inside_output)
        assert outside_output.read_bytes() == b"outside"
        assert (parked_parent / "episode.mp3").read_bytes() == b"inside"
        assert result.cleaned_count == 0
        assert result.failed_count == 1
        assert result.unsafe_skips == 1


def test_age_eligibility_is_revalidated_after_fresh_output_appears(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, srv_root = data_roots
    with app.app_context(), caplog.at_level(logging.INFO, logger="global_logger"):
        feed = _create_feed("fresh-age-revalidation")
        now = datetime.utcnow()
        old = now - timedelta(days=30)
        input_path = _audio(in_root / "fresh-age-revalidation-input.mp3")
        output_path = _audio(srv_root / "fresh-age-revalidation-output.mp3", b"old")
        os.utime(output_path, (old.timestamp(), old.timestamp()))
        target = _create_post(
            feed,
            "fresh-age-revalidation",
            release_date=old,
            processed_path=output_path,
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=target.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        _completed_job(target, old)
        db.session.add(model_call)
        db.session.flush()
        target_id = target.id
        model_call_id = model_call.id
        db.session.commit()
        original_cleanup = storage_cleanup_module._cleanup_candidate_and_commit
        refreshed = False

        def refresh_before_cleanup(
            post: Post, result: object, global_retention_days: int | None
        ) -> None:
            nonlocal refreshed
            if post.id == target_id and not refreshed:
                refreshed = True
                output_path.write_bytes(b"fresh")
                os.utime(output_path, (now.timestamp(), now.timestamp()))
                _completed_job(post, now)
                db.session.commit()
            original_cleanup(post, result, global_retention_days)

        monkeypatch.setattr(
            storage_cleanup_module,
            "_cleanup_candidate_and_commit",
            refresh_before_cleanup,
        )

        result = run_storage_cleanup(5, trigger="fresh-age-revalidation")

        after = db.session.get(Post, target_id)
        summaries = [
            record
            for record in caplog.records
            if record.getMessage().startswith("storage_cleanup_summary ")
        ]
        assert refreshed is True
        assert after is not None
        assert after.processed_audio_path == str(output_path)
        assert after.unprocessed_audio_path == str(input_path)
        assert output_path.read_bytes() == b"fresh"
        assert input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert result.skipped_count == 1
        assert len(summaries) == 1


def test_count_revalidation_preserves_missing_provisionally_retained_post(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    in_root, srv_root = data_roots
    with app.app_context(), caplog.at_level(logging.INFO, logger="global_logger"):
        feed = _create_feed("count-revalidation", retention_count=1)
        now = datetime.utcnow()
        _create_post(
            feed,
            "count-revalidation-newest",
            release_date=now,
            processed_path=_audio(srv_root / "count-revalidation-newest.mp3"),
        )
        input_path = _audio(in_root / "count-revalidation-input.mp3")
        output_path = _audio(srv_root / "count-revalidation-target.mp3")
        target = _create_post(
            feed,
            "count-revalidation-target",
            release_date=now - timedelta(days=1),
            processed_path=output_path,
            input_path=input_path,
        )
        model_call = ModelCall(
            post_id=target.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="test",
            prompt="prompt",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()
        target_id = target.id
        feed_id = feed.id
        model_call_id = model_call.id
        db.session.commit()
        original_cleanup = storage_cleanup_module._cleanup_candidate_and_commit
        policy_changed = False

        def increase_count_before_cleanup(
            post: Post, result: object, global_retention_days: int | None
        ) -> None:
            nonlocal policy_changed
            if post.id == target_id and not policy_changed:
                policy_changed = True
                db.session.query(Feed).filter(Feed.id == feed_id).update(
                    {Feed.processed_episode_retention_count: 2}
                )
                output_path.unlink()
                db.session.commit()
            original_cleanup(post, result, global_retention_days)

        monkeypatch.setattr(
            storage_cleanup_module,
            "_cleanup_candidate_and_commit",
            increase_count_before_cleanup,
        )

        result = run_storage_cleanup(None, trigger="count-revalidation")

        after = db.session.get(Post, target_id)
        summaries = [
            record
            for record in caplog.records
            if record.getMessage().startswith("storage_cleanup_summary ")
        ]
        assert policy_changed is True
        assert after is not None
        assert after.processed_audio_path is None
        assert after.unprocessed_audio_path == str(input_path)
        assert input_path.exists()
        assert db.session.get(ModelCall, model_call_id) is not None
        assert result.cleaned_count == 0
        assert result.skipped_count == 1
        assert len(summaries) == 1


def test_count_policy_revalidation_inspects_each_ranked_path_once(
    app,
    data_roots: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, srv_root = data_roots
    with app.app_context():
        feed = _create_feed("count-revalidation-linear", retention_count=1)
        now = datetime.utcnow()
        posts = [
            _create_post(
                feed,
                f"count-revalidation-linear-{index}",
                release_date=now - timedelta(days=index),
                processed_path=_audio(
                    srv_root / f"count-revalidation-linear-{index}.mp3"
                ),
            )
            for index in range(3)
        ]
        db.session.commit()
        contained_file_calls = 0
        original_contained_file = storage_cleanup_module._contained_file

        def count_contained_file_calls(path_text: str, root: Path):
            nonlocal contained_file_calls
            contained_file_calls += 1
            return original_contained_file(path_text, root)

        monkeypatch.setattr(
            storage_cleanup_module, "_contained_file", count_contained_file_calls
        )

        allowed = storage_cleanup_module._current_policy_allows_cleanup(
            posts[-1],
            storage_cleanup_module.StorageCleanupResult(
                trigger="count-revalidation-linear", scope={"feed_id": feed.id}
            ),
            None,
        )

        assert allowed is True
        assert contained_file_calls == len(posts)
