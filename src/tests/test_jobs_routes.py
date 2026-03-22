from __future__ import annotations

from datetime import datetime, timedelta

from app.auth import AuthSettings
from app.auth.middleware import SESSION_USER_KEY, init_auth_middleware
from app.extensions import db
from app.models import ProcessingJob, User
from app.routes.jobs_routes import jobs_bp


def test_jobs_dashboard_aggregates_persisted_job_history(app) -> None:
    app.register_blueprint(jobs_bp)

    with app.app_context():
        user = User(username="analyst", password_hash="dummy", role="admin")
        db.session.add(user)
        db.session.flush()

        now = datetime.utcnow()
        db.session.add_all(
            [
                ProcessingJob(
                    id="job-recent-complete",
                    post_guid="archived-guid-1",
                    feed_id=77,
                    feed_title="Archived Feed",
                    post_title="Archived Episode",
                    triggered_by_user_id=user.id,
                    trigger_source="manual_ui",
                    status="completed",
                    current_step=4,
                    total_steps=4,
                    progress_percentage=100.0,
                    created_at=now - timedelta(hours=3),
                    started_at=now - timedelta(hours=3),
                    completed_at=now - timedelta(hours=2, minutes=55),
                    total_ad_segments_removed=4,
                    total_duration_removed_seconds=120.0,
                    original_duration_seconds=3600.0,
                    processed_duration_seconds=3480.0,
                    percentage_removed=3.3,
                ),
                ProcessingJob(
                    id="job-recent-failed",
                    post_guid="archived-guid-2",
                    feed_id=77,
                    feed_title="Archived Feed",
                    post_title="Archived Episode Failed",
                    triggered_by_user_id=user.id,
                    trigger_source="manual_ui",
                    status="failed",
                    current_step=2,
                    total_steps=4,
                    progress_percentage=50.0,
                    created_at=now - timedelta(days=1),
                    started_at=now - timedelta(days=1, minutes=-2),
                    completed_at=now - timedelta(days=1, minutes=-1),
                    error_message="boom",
                ),
                ProcessingJob(
                    id="job-old-complete",
                    post_guid="archived-guid-3",
                    feed_id=88,
                    feed_title="Older Feed",
                    post_title="Older Episode",
                    triggered_by_user_id=user.id,
                    trigger_source="manual_ui",
                    status="completed",
                    current_step=4,
                    total_steps=4,
                    progress_percentage=100.0,
                    created_at=now - timedelta(days=30),
                    started_at=now - timedelta(days=30),
                    completed_at=now - timedelta(days=30, minutes=-5),
                    total_ad_segments_removed=1,
                    total_duration_removed_seconds=30.0,
                    original_duration_seconds=1800.0,
                    processed_duration_seconds=1770.0,
                    percentage_removed=1.7,
                ),
            ]
        )
        db.session.commit()

    client = app.test_client()
    response = client.get("/api/jobs/dashboard?days=7")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload is not None
    assert payload["overview"]["total_all_time"] == 3
    assert payload["overview"]["total_period"] == 2
    assert payload["overview"]["by_status"]["completed"] == 1
    assert payload["overview"]["by_status"]["failed"] == 1
    assert payload["performance"]["completed_count"] == 1
    assert payload["performance"]["total_ads_removed"] == 4
    assert payload["performance"]["total_time_removed_seconds"] == 120.0
    assert payload["by_user"][0]["username"] == "analyst"
    assert payload["by_feed"][0]["title"] == "Archived Feed"
    assert payload["by_feed"][0]["total"] == 2
    assert payload["recent_completed"][0]["post_title"] == "Archived Episode"
    assert payload["recent_completed"][0]["feed_title"] == "Archived Feed"


def test_jobs_dashboard_requires_admin_when_auth_enabled(app) -> None:
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    init_auth_middleware(app)
    app.register_blueprint(jobs_bp)

    with app.app_context():
        user = User(username="listener", role="user")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session[SESSION_USER_KEY] = user_id

    response = client.get("/api/jobs/dashboard?days=7")
    assert response.status_code == 403


def test_clear_history_requires_admin_when_auth_enabled(app) -> None:
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    init_auth_middleware(app)
    app.register_blueprint(jobs_bp)

    with app.app_context():
        user = User(username="history-listener", role="user")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    with client.session_transaction() as session:
        session[SESSION_USER_KEY] = user_id

    response = client.post("/api/jobs/clear-history")
    assert response.status_code == 403
