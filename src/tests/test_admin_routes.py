from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from flask import Flask

from app.auth import AuthSettings
from app.auth.middleware import SESSION_USER_KEY, init_auth_middleware
from app.extensions import db
from app.models import Feed, Identification, ModelCall, Post, TranscriptSegment, User
from app.routes.admin_routes import admin_bp


@pytest.fixture
def app_with_admin_routes(tmp_path: Path) -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'test.sqlite3.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    app.testing = True

    with app.app_context():
        db.init_app(app)
        db.create_all()

    init_auth_middleware(app)
    app.register_blueprint(admin_bp)
    return app


def _login(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session[SESSION_USER_KEY] = user_id


def _create_user(app: Flask, username: str, role: str) -> int:
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_post_with_transcript(app: Flask) -> str:
    with app.app_context():
        feed = Feed(title="Transcript Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.flush()

        post = Post(
            feed_id=feed.id,
            guid="transcript-guid",
            download_url="https://example.com/audio.mp3",
            title="Transcript Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.flush()

        segment_1 = TranscriptSegment(
            post_id=post.id,
            sequence_num=0,
            start_time=0.0,
            end_time=10.0,
            text="Sponsored by a mattress company",
        )
        segment_2 = TranscriptSegment(
            post_id=post.id,
            sequence_num=1,
            start_time=10.0,
            end_time=20.0,
            text="Back to the show",
        )
        db.session.add_all([segment_1, segment_2])
        db.session.flush()

        model_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=1,
            model_name="test-model",
            prompt="prompt",
            response="response",
            status="completed",
        )
        db.session.add(model_call)
        db.session.flush()

        db.session.add(
            Identification(
                transcript_segment_id=segment_1.id,
                model_call_id=model_call.id,
                confidence=0.99,
                label="ad",
            )
        )
        db.session.commit()
        return post.guid


def test_bulk_transcript_export_returns_zip_archive_for_requested_format(
    app_with_admin_routes: Flask,
) -> None:
    admin_id = _create_user(app_with_admin_routes, "adminuser", "admin")
    post_guid = _create_post_with_transcript(app_with_admin_routes)

    client = app_with_admin_routes.test_client()
    _login(client, admin_id)

    response = client.post(
        "/api/transcripts/export-bulk",
        json={"post_guids": [post_guid], "format": "srt"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/zip")

    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = archive.namelist()
    assert any(name.endswith(".srt") for name in names)
    srt_name = next(name for name in names if name.endswith(".srt"))
    srt_content = archive.read(srt_name).decode("utf-8")
    assert "Sponsored by a mattress company" in srt_content
    assert "[AD]" in srt_content


def test_backup_database_requires_auth_when_auth_enabled(
    app_with_admin_routes: Flask,
) -> None:
    client = app_with_admin_routes.test_client()

    response = client.post("/api/admin/backup")

    assert response.status_code == 401


def test_backup_database_downloads_file_when_sqlite_uri_has_query_params(
    app_with_admin_routes: Flask,
) -> None:
    admin_id = _create_user(app_with_admin_routes, "backup-admin", "admin")

    db_uri = app_with_admin_routes.config["SQLALCHEMY_DATABASE_URI"]
    app_with_admin_routes.config["SQLALCHEMY_DATABASE_URI"] = f"{db_uri}?timeout=90"

    client = app_with_admin_routes.test_client()
    _login(client, admin_id)

    response = client.post("/api/admin/backup")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/x-sqlite3")
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.data.startswith(b"SQLite format 3")


def test_restore_rejects_invalid_database_upload(app_with_admin_routes: Flask) -> None:
    admin_id = _create_user(app_with_admin_routes, "restore-admin", "admin")

    client = app_with_admin_routes.test_client()
    _login(client, admin_id)

    response = client.post(
        "/api/admin/restore",
        data={"file": (io.BytesIO(b"not-a-sqlite-file"), "invalid.db")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload is not None
    assert "valid SQLite" in payload["error"]
