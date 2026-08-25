from __future__ import annotations

from datetime import datetime, timedelta

from app.extensions import db
from app.jobs_manager import JobsManager
from app.jobs_manager_run_service import (
    SINGLETON_RUN_ID,
    recalculate_affected_run_counts,
)
from app.models import Feed, JobsManagerRun, Post, ProcessingJob, ProcessingStatistics
from podcast_processor.processing_status_manager import ProcessingStatusManager


def _create_feed_and_post() -> tuple[Feed, Post]:
    feed = Feed(
        title="History Feed",
        rss_url="https://example.com/history.xml",
        image_url="https://example.com/feed.png",
    )
    db.session.add(feed)
    db.session.flush()

    post = Post(
        feed_id=feed.id,
        guid="history-guid",
        download_url="https://example.com/episode.mp3",
        title="History Episode",
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    return feed, post


def _make_manager() -> JobsManager:
    manager = JobsManager.__new__(JobsManager)
    manager._status_manager = ProcessingStatusManager(db.session)
    return manager


def test_recover_interrupted_jobs_preserves_completed_history(app) -> None:
    with app.app_context():
        _, post = _create_feed_and_post()

        completed_at = datetime.utcnow() - timedelta(minutes=15)
        db.session.add_all(
            [
                ProcessingJob(
                    id="job-completed",
                    post_guid=post.guid,
                    status="completed",
                    current_step=4,
                    total_steps=4,
                    progress_percentage=100.0,
                    created_at=completed_at,
                    started_at=completed_at,
                    completed_at=completed_at,
                ),
                ProcessingJob(
                    id="job-running",
                    post_guid=post.guid,
                    status="running",
                    current_step=2,
                    total_steps=4,
                    progress_percentage=50.0,
                    created_at=datetime.utcnow() - timedelta(minutes=5),
                    started_at=datetime.utcnow() - timedelta(minutes=4),
                ),
                ProcessingJob(
                    id="job-pending",
                    post_guid=post.guid,
                    status="pending",
                    current_step=0,
                    total_steps=4,
                    progress_percentage=0.0,
                    created_at=datetime.utcnow() - timedelta(minutes=3),
                ),
            ]
        )
        db.session.commit()

        result = _make_manager().recover_interrupted_jobs()

        db.session.expire_all()
        completed_job = db.session.get(ProcessingJob, "job-completed")
        running_job = db.session.get(ProcessingJob, "job-running")
        pending_job = db.session.get(ProcessingJob, "job-pending")

        assert result["preserved_count"] == 1
        assert result["recovered_count"] == 2
        assert completed_job is not None
        assert completed_job.status == "completed"
        assert running_job is not None
        assert running_job.status == "failed"
        assert running_job.completed_at is not None
        assert "restart" in (running_job.error_message or "").lower()
        assert pending_job is not None
        assert pending_job.status == "failed"
        assert pending_job.completed_at is not None
        assert "restart" in (pending_job.error_message or "").lower()


def test_create_job_captures_feed_and_post_snapshot(app) -> None:
    with app.app_context():
        feed, post = _create_feed_and_post()

        status_manager = ProcessingStatusManager(db.session)
        job = status_manager.create_job(post.guid, "job-snapshot")

        assert job.feed_id == feed.id
        assert job.feed_title == feed.title
        assert job.post_title == post.title


def test_sync_job_metrics_from_post_copies_processing_statistics(app) -> None:
    with app.app_context():
        feed, post = _create_feed_and_post()

        job = ProcessingJob(
            id="job-metrics",
            post_guid=post.guid,
            status="completed",
            current_step=4,
            total_steps=4,
            progress_percentage=100.0,
            feed_id=feed.id,
            feed_title=feed.title,
            post_title=post.title,
        )
        db.session.add(job)
        db.session.flush()

        db.session.add(
            ProcessingStatistics(
                post_id=post.id,
                total_ad_segments_removed=3,
                total_duration_removed_seconds=97.5,
                original_duration_seconds=3600.0,
                processed_duration_seconds=3502.5,
                percentage_removed=2.7,
            )
        )
        db.session.commit()

        status_manager = ProcessingStatusManager(db.session)
        status_manager.sync_job_metrics_from_post(job, post)

        db.session.refresh(job)
        assert job.total_ad_segments_removed == 3
        assert job.total_duration_removed_seconds == 97.5
        assert job.original_duration_seconds == 3600.0
        assert job.processed_duration_seconds == 3502.5
        assert job.percentage_removed == 2.7


def test_recalculate_affected_runs_repairs_explicit_run_and_singleton(app) -> None:
    with app.app_context():
        now = datetime.utcnow()
        explicit = JobsManagerRun(
            id="explicit-history-run",
            status="running",
            trigger="manual",
            total_jobs=9,
            queued_jobs=2,
            running_jobs=1,
            completed_jobs=6,
            counters_reset_at=now - timedelta(days=1),
        )
        singleton = JobsManagerRun(
            id=SINGLETON_RUN_ID,
            status="running",
            trigger="scheduler",
            total_jobs=9,
            queued_jobs=9,
            counters_reset_at=now - timedelta(days=1),
        )
        db.session.add_all([explicit, singleton])
        db.session.add_all(
            [
                ProcessingJob(
                    id="removed-history-job",
                    jobs_manager_run_id=explicit.id,
                    post_guid="removed",
                    status="completed",
                    created_at=now,
                    completed_at=now,
                ),
                ProcessingJob(
                    id="singleton-pending-job",
                    jobs_manager_run_id=SINGLETON_RUN_ID,
                    post_guid="active",
                    status="pending",
                    created_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.query(ProcessingJob).filter_by(id="removed-history-job").delete()

        recalculated = recalculate_affected_run_counts(
            db.session, {"explicit-history-run"}
        )
        db.session.commit()

        assert recalculated == {"explicit-history-run", SINGLETON_RUN_ID}
        assert explicit.status == "completed"
        assert explicit.total_jobs == 0
        assert singleton.status == "pending"
        assert singleton.total_jobs == 1
        assert singleton.queued_jobs == 1


def test_recalculate_explicit_run_preserves_remaining_terminal_history(app) -> None:
    with app.app_context():
        now = datetime.utcnow()
        reset_at = now - timedelta(days=1)
        explicit = JobsManagerRun(
            id="explicit-terminal-history",
            status="running",
            trigger="manual",
            total_jobs=99,
            queued_jobs=10,
            running_jobs=5,
            completed_jobs=80,
            failed_jobs=4,
            skipped_jobs=0,
            counters_reset_at=reset_at,
        )
        singleton = JobsManagerRun(
            id=SINGLETON_RUN_ID,
            status="running",
            trigger="scheduler",
            total_jobs=99,
            queued_jobs=99,
            counters_reset_at=reset_at,
        )
        db.session.add_all([explicit, singleton])
        jobs = [
            ProcessingJob(
                id="explicit-removed",
                jobs_manager_run_id=explicit.id,
                post_guid="removed",
                status="completed",
                created_at=now,
                completed_at=now,
            ),
            ProcessingJob(
                id="explicit-completed-one",
                jobs_manager_run_id=explicit.id,
                post_guid="completed-one",
                status="completed",
                created_at=reset_at - timedelta(hours=1),
                completed_at=now,
            ),
            ProcessingJob(
                id="explicit-completed-two",
                jobs_manager_run_id=explicit.id,
                post_guid="completed-two",
                status="completed",
                created_at=now,
                completed_at=now,
            ),
            ProcessingJob(
                id="explicit-failed",
                jobs_manager_run_id=explicit.id,
                post_guid="failed",
                status="failed",
                created_at=now,
                completed_at=now,
            ),
            ProcessingJob(
                id="explicit-skipped",
                jobs_manager_run_id=explicit.id,
                post_guid="skipped",
                status="skipped",
                created_at=now,
                completed_at=now,
            ),
        ]
        db.session.add_all(jobs)
        db.session.commit()
        db.session.delete(jobs[0])

        recalculate_affected_run_counts(db.session, {explicit.id})
        db.session.commit()

        assert explicit.status == "failed"
        assert explicit.total_jobs == 4
        assert explicit.queued_jobs == 0
        assert explicit.running_jobs == 0
        assert explicit.completed_jobs == 2
        assert explicit.failed_jobs == 1
        assert explicit.skipped_jobs == 1
        assert explicit.completed_at is not None
        assert explicit.counters_reset_at == reset_at
        assert singleton.status == "idle"
        assert singleton.total_jobs == 0
