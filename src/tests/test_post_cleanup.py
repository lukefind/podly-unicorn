from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.extensions import db, scheduler
from app.jobs_manager_run_service import SINGLETON_RUN_ID
from app.models import Feed, Post, ProcessingJob
from app.models import (
    Identification,
    JobsManagerRun,
    ModelCall,
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
        assert explicit.status == "idle"
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
        original_unlink = Path.unlink

        def selective_unlink(path: Path, *args: object, **kwargs: object) -> None:
            if path == output_path:
                raise OSError("synthetic unlink failure")
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", selective_unlink)

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
        original_unlink = Path.unlink

        def disappear_then_raise(path: Path, *args: object, **kwargs: object) -> None:
            if path == output:
                original_unlink(path, *args, **kwargs)
                raise FileNotFoundError(str(path))
            original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", disappear_then_raise)

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
