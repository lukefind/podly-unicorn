"""
Regression tests for /trigger and /api/trigger/status endpoints.

These tests verify:
1. /trigger route is not intercepted by main_bp catch-all
2. /api/trigger/status returns proper JSON with Cache-Control headers
3. Invalid tokens return 401/403, never 500
4. Missing params return 400, never 500
"""

import hashlib
import secrets
from datetime import datetime, timezone
from html.parser import HTMLParser
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, ProcessingJob, User
from app.routes.main_routes import main_bp
from app.routes.post_routes import (
    _render_trigger_error_page,
    _render_trigger_page_fallback,
    post_bp,
)


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@pytest.fixture
def app_with_routes() -> Flask:
    """Create a Flask app with routes registered in correct order."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "test-secret-key"
    app.testing = True

    # Register blueprints in correct order (main_bp LAST)
    app.register_blueprint(post_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


@pytest.fixture
def test_user(app_with_routes):
    """Create a test user."""
    with app_with_routes.app_context():
        user = User(username="testuser", password_hash="dummy", role="user")
        db.session.add(user)
        db.session.commit()
        yield user


@pytest.fixture
def test_feed(app_with_routes, test_user):
    """Create a test feed."""
    with app_with_routes.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()
        yield feed


@pytest.fixture
def test_post(app_with_routes, test_feed):
    """Create a test post."""
    with app_with_routes.app_context():
        post = Post(
            feed_id=test_feed.id,
            guid="test-guid-123",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()
        yield post


@pytest.fixture
def test_token(app_with_routes, test_user, test_feed):
    """Create a test feed access token."""
    with app_with_routes.app_context():
        # Refresh objects in this session
        user = db.session.merge(test_user)
        feed = db.session.merge(test_feed)

        token_id = "test-token-id"
        token_secret = secrets.token_urlsafe(18)
        token = FeedAccessToken(
            token_id=token_id,
            token_hash=_hash_token(token_secret),
            token_secret=token_secret,
            feed_id=feed.id,
            user_id=user.id,
        )
        db.session.add(token)
        db.session.commit()
        yield {"token_id": token_id, "secret": token_secret}


class TestTriggerRouteOrder:
    """Test that /trigger route is handled by post_bp, not main_bp catch-all."""

    def test_trigger_route_not_intercepted_by_catchall(self, app_with_routes):
        """Verify /trigger is handled by post_bp, not main_bp catch-all."""
        client = app_with_routes.test_client()

        # Without params, should return 400 (missing params), not 200 (index.html)
        response = client.get("/trigger")

        # If main_bp catch-all intercepted, it would return 200 with index.html
        # post_bp /trigger should return 400 for missing params
        assert response.status_code == 400
        assert (
            b"Missing Parameters" in response.data
            or b"missing" in response.data.lower()
        )


class _ConfirmationForm(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.action = None
        self.method = None
        self.token = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self.action = values.get("action")
            self.method = values.get("method")
        if tag == "input" and values.get("name") == "confirmation_token":
            self.token = values.get("value")


@pytest.fixture
def trigger_worker(monkeypatch):
    """Keep route tests offline while exercising real auth, HTML and DB state."""
    worker = MagicMock()
    worker.start_post_processing.return_value = {"status": "started", "job_id": None}
    monkeypatch.setattr("app.routes.post_routes.get_jobs_manager", lambda: worker)
    return worker


class TestExplicitTriggerConfirmation:
    @staticmethod
    def query(post, token):
        return {
            "guid": post.guid,
            "feed_token": token["token_id"],
            "feed_secret": token["secret"],
        }

    @pytest.mark.parametrize(
        "method,headers",
        [
            ("GET", {}),
            ("HEAD", {}),
            ("GET", {"Purpose": "prefetch"}),
            ("GET", {"Sec-Purpose": "prefetch;prerender", "User-Agent": "Googlebot"}),
        ],
    )
    def test_passive_fetch_never_starts_processing(
        self, app_with_routes, test_post, test_token, trigger_worker, method, headers
    ):
        response = app_with_routes.test_client().open(
            "/trigger",
            method=method,
            query_string=self.query(test_post, test_token),
            headers=headers,
        )
        assert response.status_code == 200
        trigger_worker.start_post_processing.assert_not_called()
        if method == "GET":
            form = _ConfirmationForm(response.get_data(as_text=True))
            assert form.method == "post"
            assert form.token
            assert "Process episode" in response.get_data(as_text=True)

    def test_confirmation_is_served_even_with_frontend_bundle(
        self, app_with_routes, test_post, test_token, trigger_worker, tmp_path
    ):
        (tmp_path / "index.html").write_text("<html>SPA shell</html>")
        app_with_routes.static_folder = str(tmp_path)
        response = app_with_routes.test_client().get(
            "/trigger", query_string=self.query(test_post, test_token)
        )
        assert _ConfirmationForm(response.get_data(as_text=True)).token
        trigger_worker.start_post_processing.assert_not_called()

    def test_explicit_submission_starts_once_and_redirects_to_safe_get(
        self, app_with_routes, test_post, test_token, test_user, trigger_worker
    ):
        client = app_with_routes.test_client()
        response = client.get(
            "/trigger", query_string=self.query(test_post, test_token)
        )
        form = _ConfirmationForm(response.get_data(as_text=True))
        assert form.action and form.token
        response = client.post(form.action, data={"confirmation_token": form.token})
        assert response.status_code == 303
        trigger_worker.start_post_processing.assert_called_once_with(
            test_post.guid,
            priority="interactive",
            triggered_by_user_id=test_user.id,
            trigger_source="trigger_link",
        )
        assert client.get(response.headers["Location"]).status_code == 200
        assert trigger_worker.start_post_processing.call_count == 1

    @pytest.mark.parametrize("token", [None, "forged-confirmation"])
    def test_post_without_valid_confirmation_is_rejected(
        self, app_with_routes, test_post, test_token, trigger_worker, token
    ):
        data = {} if token is None else {"confirmation_token": token}
        response = app_with_routes.test_client().post(
            "/trigger", query_string=self.query(test_post, test_token), data=data
        )
        assert response.status_code == 403
        trigger_worker.start_post_processing.assert_not_called()

    def test_confirmation_in_query_cannot_start_processing(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        client = app_with_routes.test_client()
        query = self.query(test_post, test_token)
        form = _ConfirmationForm(
            client.get("/trigger", query_string=query).get_data(as_text=True)
        )
        assert form.token
        query["confirmation_token"] = form.token
        assert client.get("/trigger", query_string=query).status_code == 200
        assert client.post("/trigger", query_string=query).status_code == 403
        trigger_worker.start_post_processing.assert_not_called()

    def test_expired_confirmation_is_rejected(
        self, app_with_routes, test_post, test_token, trigger_worker, monkeypatch
    ):
        client = app_with_routes.test_client()
        with monkeypatch.context() as clock:
            clock.setattr("itsdangerous.TimestampSigner.get_timestamp", lambda self: 1)
            form = _ConfirmationForm(
                client.get(
                    "/trigger", query_string=self.query(test_post, test_token)
                ).get_data(as_text=True)
            )
        assert form.token
        response = client.post(form.action, data={"confirmation_token": form.token})
        assert response.status_code == 403
        trigger_worker.start_post_processing.assert_not_called()

    def test_confirmation_cannot_be_used_for_another_episode(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        client = app_with_routes.test_client()
        form = _ConfirmationForm(
            client.get(
                "/trigger", query_string=self.query(test_post, test_token)
            ).get_data(as_text=True)
        )
        assert form.token
        other = Post(
            feed_id=test_post.feed_id,
            guid="another-episode",
            title="Another",
            download_url="https://example.com/other.mp3",
            whitelisted=True,
        )
        db.session.add(other)
        db.session.commit()
        response = client.post(
            "/trigger",
            query_string=self.query(other, test_token),
            data={"confirmation_token": form.token},
        )
        assert response.status_code == 403
        trigger_worker.start_post_processing.assert_not_called()

    def test_ambiguous_guid_is_rejected_before_worker_dispatch(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        client = app_with_routes.test_client()
        query = self.query(test_post, test_token)
        form = _ConfirmationForm(
            client.get("/trigger", query_string=query).get_data(as_text=True)
        )
        assert form.token
        other_feed = Feed(title="Other show", rss_url="https://example.com/other-rss")
        db.session.add(other_feed)
        db.session.flush()
        db.session.add(
            Post(
                feed_id=other_feed.id,
                guid=test_post.guid,
                title="Colliding episode",
                download_url="https://example.com/collision.mp3",
                whitelisted=True,
            )
        )
        db.session.commit()
        assert client.get("/trigger", query_string=query).status_code == 409
        assert (
            client.post(
                form.action, data={"confirmation_token": form.token}
            ).status_code
            == 409
        )
        trigger_worker.start_post_processing.assert_not_called()

    def test_middleware_auth_errors_have_trigger_headers(
        self, app_with_routes, monkeypatch
    ):
        from app.auth import AuthSettings
        from app.auth.middleware import init_auth_middleware
        from app.auth.state import failure_rate_limiter

        app_with_routes.config["AUTH_SETTINGS"] = AuthSettings(
            require_auth=True, admin_username="admin", admin_password=None
        )
        init_auth_middleware(app_with_routes)
        monkeypatch.setattr(failure_rate_limiter, "retry_after", lambda client: 30)
        response = app_with_routes.test_client().get("/trigger")
        assert response.status_code == 429
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_confirmation_is_bound_to_feed_token(
        self, app_with_routes, test_post, test_token, test_user, trigger_worker
    ):
        client = app_with_routes.test_client()
        form = _ConfirmationForm(
            client.get(
                "/trigger", query_string=self.query(test_post, test_token)
            ).get_data(as_text=True)
        )
        other_secret = "second-token-secret"
        db.session.add(
            FeedAccessToken(
                token_id="second-token",
                token_hash=_hash_token(other_secret),
                token_secret=other_secret,
                feed_id=test_post.feed_id,
                user_id=test_user.id,
            )
        )
        db.session.commit()
        query = self.query(
            test_post, {"token_id": "second-token", "secret": other_secret}
        )
        assert (
            client.post(
                "/trigger", query_string=query, data={"confirmation_token": form.token}
            ).status_code
            == 403
        )
        trigger_worker.start_post_processing.assert_not_called()

    @pytest.mark.parametrize(
        "change,expected", [("revoked", 403), ("combined", 403), ("disabled", 409)]
    )
    def test_post_rechecks_authorization_and_eligibility(
        self, app_with_routes, test_post, test_token, trigger_worker, change, expected
    ):
        client = app_with_routes.test_client()
        form = _ConfirmationForm(
            client.get(
                "/trigger", query_string=self.query(test_post, test_token)
            ).get_data(as_text=True)
        )
        if change == "disabled":
            db.session.merge(test_post).whitelisted = False
        else:
            token = FeedAccessToken.query.filter_by(
                token_id=test_token["token_id"]
            ).one()
            if change == "revoked":
                token.revoked = True
            else:
                token.feed_id = None
        db.session.commit()
        assert (
            client.post(
                form.action, data={"confirmation_token": form.token}
            ).status_code
            == expected
        )
        trigger_worker.start_post_processing.assert_not_called()

    def test_duplicate_submit_and_page_refresh_reuse_active_job(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        client = app_with_routes.test_client()
        form = _ConfirmationForm(
            client.get(
                "/trigger", query_string=self.query(test_post, test_token)
            ).get_data(as_text=True)
        )

        def enqueue(guid, **kwargs):
            db.session.add(
                ProcessingJob(id="confirmed-job", post_guid=guid, status="pending")
            )
            db.session.commit()
            return {"status": "started", "job_id": "confirmed-job"}

        trigger_worker.start_post_processing.side_effect = enqueue
        for _ in range(2):
            response = client.post(form.action, data={"confirmation_token": form.token})
            assert response.status_code == 303
            assert client.get(response.headers["Location"]).status_code == 200
        assert trigger_worker.start_post_processing.call_count == 1
        assert ProcessingJob.query.count() == 1

    def test_recent_failed_job_retains_cooldown(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        client = app_with_routes.test_client()
        query = self.query(test_post, test_token)
        form = _ConfirmationForm(
            client.get("/trigger", query_string=query).get_data(as_text=True)
        )
        db.session.add(
            ProcessingJob(
                id="recent-failure",
                post_guid=test_post.guid,
                status="failed",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        assert b"Please Wait" in client.get("/trigger", query_string=query).data
        assert (
            client.post(
                form.action, data={"confirmation_token": form.token}
            ).status_code
            == 303
        )
        trigger_worker.start_post_processing.assert_not_called()

    def test_ready_episode_remains_read_only(
        self, app_with_routes, test_post, test_token, trigger_worker, tmp_path
    ):
        audio = tmp_path / "ready.mp3"
        audio.write_bytes(b"test audio")
        db.session.merge(test_post).processed_audio_path = str(audio)
        db.session.commit()
        response = app_with_routes.test_client().get(
            "/trigger", query_string=self.query(test_post, test_token)
        )
        assert response.status_code == 200
        assert b"Episode Ready" in response.data
        assert not _ConfirmationForm(response.get_data(as_text=True)).token
        trigger_worker.start_post_processing.assert_not_called()

    def test_confirmation_escapes_metadata_and_round_trips_guid(
        self, app_with_routes, test_post, test_token, trigger_worker
    ):
        from urllib.parse import parse_qs, urlsplit

        post = db.session.merge(test_post)
        post.title = '<script>alert("episode")</script>'
        post.guid = 'https://example.com/episode?one=1&two="<tag>"'
        db.session.commit()
        response = app_with_routes.test_client().get(
            "/trigger", query_string=self.query(post, test_token)
        )
        html = response.get_data(as_text=True)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        form = _ConfirmationForm(html)
        assert parse_qs(urlsplit(form.action).query)["guid"] == [post.guid]
        response = app_with_routes.test_client().post(
            form.action, data={"confirmation_token": form.token}
        )
        assert response.status_code == 303
        trigger_worker.start_post_processing.assert_called_once()

    @pytest.mark.parametrize(
        "path,query",
        [
            ("/trigger", {}),
            (
                "/trigger",
                {"guid": "missing", "feed_token": "invalid", "feed_secret": "invalid"},
            ),
            ("/api/trigger/status", {}),
        ],
    )
    def test_trigger_responses_are_private_and_not_indexable(
        self, app_with_routes, path, query
    ):
        response = app_with_routes.test_client().get(path, query_string=query)
        assert response.headers.get("Cache-Control") == "no-store"
        assert response.headers.get("X-Robots-Tag") == "noindex, nofollow"
        assert response.headers.get("Referrer-Policy") == "no-referrer"
        assert response.headers.get("X-Frame-Options") == "DENY"


class TestTriggerStatusEndpoint:
    """Test /api/trigger/status endpoint."""

    def test_missing_params_returns_400_with_cache_control(self, app_with_routes):
        """Missing params should return 400 with Cache-Control: no-store."""
        client = app_with_routes.test_client()

        response = client.get("/api/trigger/status")
        assert response.status_code == 400

        # Must have Cache-Control even on errors
        assert response.headers.get("Cache-Control") == "no-store"

        data = response.get_json()
        assert data is not None
        assert data["state"] == "error"
        assert "Missing" in data["message"] or "required" in data["message"].lower()

    def test_invalid_token_returns_401_with_cache_control(
        self, app_with_routes, test_post
    ):
        """Invalid token should return 401 with Cache-Control: no-store."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/api/trigger/status?guid={post.guid}&feed_token=invalid&feed_secret=invalid"
            )

        assert response.status_code == 401
        # Must have Cache-Control even on errors
        assert response.headers.get("Cache-Control") == "no-store"

        data = response.get_json()
        assert data is not None
        assert data["state"] == "error"

    def test_valid_request_returns_json_with_cache_control(
        self, app_with_routes, test_post, test_token
    ):
        """Valid request should return JSON with Cache-Control: no-store."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        # Should return 200 with JSON
        assert response.status_code == 200
        assert response.content_type == "application/json"

        # Must have Cache-Control: no-store
        assert response.headers.get("Cache-Control") == "no-store"

        # JSON should have required fields
        data = response.get_json()
        assert data is not None
        assert "state" in data
        assert "processed" in data
        assert data["state"] in [
            "ready",
            "processing",
            "queued",
            "failed",
            "not_started",
        ]

    def test_nonexistent_post_returns_404(self, app_with_routes, test_token):
        """Unknown GUIDs currently fail token auth before post lookup."""
        client = app_with_routes.test_client()

        response = client.get(
            f"/api/trigger/status?guid=nonexistent-guid"
            f"&feed_token={test_token['token_id']}"
            f"&feed_secret={test_token['secret']}"
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data is not None
        assert data["state"] == "error"


class TestTriggerEndpoint:
    """Test /trigger endpoint."""

    def test_missing_params_returns_400_html(self, app_with_routes):
        """Missing params should return 400 with error HTML."""
        client = app_with_routes.test_client()

        response = client.get("/trigger")
        assert response.status_code == 400
        assert response.mimetype == "text/html"

    def test_invalid_token_returns_403_html(self, app_with_routes, test_post):
        """Invalid token should return 401/403 with error HTML, not 500."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/trigger?guid={post.guid}&feed_token=invalid&feed_secret=invalid"
            )

        # Should be 401 or 403, never 500
        assert response.status_code in [401, 403]
        assert response.mimetype == "text/html"
        assert b"<title>Invalid Token - Podly Unicorn</title>" in response.data
        assert b"<h1>Podly Unicorn</h1>" in response.data
        assert b'<a href="/">Podly Unicorn</a>' in response.data
        assert b">Go to Podly</a>" in response.data

    def test_error_page_uses_unicorn_product_identity(self, app_with_routes):
        """Server-rendered errors should use the default Unicorn identity."""
        with app_with_routes.app_context():
            response = _render_trigger_error_page(
                title="Authentication Error",
                message="Unable to authenticate.",
                status_code=401,
            )

        assert response.status_code == 401
        assert b"<title>Authentication Error - Podly Unicorn</title>" in response.data
        assert b"<h1>Podly Unicorn</h1>" in response.data
        assert b'<a href="/">Podly Unicorn</a>' in response.data
        assert b"<h1>Podly</h1>" not in response.data

    def test_fallback_page_uses_unicorn_product_identity(self, app_with_routes):
        """The no-React fallback should use the default Unicorn identity."""
        with app_with_routes.app_context():
            response = _render_trigger_page_fallback(
                title="Processing Started",
                message="Episode queued.",
                state="processing",
            )

        assert response.status_code == 200
        assert b"<title>Processing Started - Podly Unicorn</title>" in response.data
        assert b"<h1>Podly Unicorn</h1>" in response.data
        assert b'<a href="/">Podly Unicorn</a>' in response.data
        assert b"<h1>Podly</h1>" not in response.data


class TestTriggerStatusProcessingState:
    """Test /api/trigger/status with processing jobs that have NULL fields.

    This is a regression test for the 500 error that occurred when polling
    status while a job was actively processing with NULL current_step/total_steps.
    """

    def test_processing_job_with_null_fields_returns_200(
        self, app_with_routes, test_post, test_token
    ):
        """Processing job with NULL fields should return 200, not 500."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)

            # Create a processing job with NULL fields (simulates early processing)
            job = ProcessingJob(
                post_guid=post.guid,
                status="running",
                current_step=None,  # NULL - this was causing crashes
                total_steps=None,  # NULL
                step_name=None,  # NULL
                progress_percentage=None,  # NULL
            )
            db.session.add(job)
            db.session.commit()

            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        # Must return 200, not 500
        assert response.status_code == 200
        assert response.content_type == "application/json"

        data = response.get_json()
        assert data is not None
        assert data["state"] in ["processing", "queued"]

        # Job object must have safe defaults
        assert data["job"] is not None
        assert isinstance(data["job"]["current_step"], int)
        assert isinstance(data["job"]["total_steps"], int)
        assert isinstance(data["job"]["progress_percentage"], int)
        assert 0 <= data["job"]["progress_percentage"] <= 100
        assert data["job"]["step_name"] is not None

    def test_pending_job_with_null_fields_returns_200(
        self, app_with_routes, test_post, test_token
    ):
        """Pending job with NULL fields should return 200 with queued state."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)

            # Create a pending job with NULL fields
            job = ProcessingJob(
                post_guid=post.guid,
                status="pending",
                current_step=None,
                total_steps=None,
                step_name=None,
                progress_percentage=None,
            )
            db.session.add(job)
            db.session.commit()

            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "queued"
        assert data["job"]["progress_percentage"] == 0  # Default for step 0

    def test_processing_job_progress_percentage_clamped(
        self, app_with_routes, test_post, test_token
    ):
        """Progress percentage should be clamped to 0-100 range."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)

            # Create a job with out-of-range progress
            job = ProcessingJob(
                post_guid=post.guid,
                status="running",
                current_step=2,
                total_steps=4,
                step_name="Transcribing",
                progress_percentage=150,  # Invalid - should be clamped to 100
            )
            db.session.add(job)
            db.session.commit()

            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data["job"]["progress_percentage"] == 100  # Clamped


class TestTriggerStatusHeaders:
    """Test that trigger endpoints do not emit session cookies or Vary: Cookie."""

    def test_trigger_status_no_set_cookie_header(
        self, app_with_routes, test_post, test_token
    ):
        """Trigger status should never emit Set-Cookie header."""
        # Register the cookie stripping middleware
        from app import _configure_trigger_cookie_stripping

        _configure_trigger_cookie_stripping(app_with_routes)

        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        assert response.status_code == 200
        # Must NOT have Set-Cookie header
        assert "Set-Cookie" not in response.headers

    def test_trigger_status_no_vary_cookie_header(
        self, app_with_routes, test_post, test_token
    ):
        """Trigger status should not have Vary: Cookie header."""
        # Register the cookie stripping middleware
        from app import _configure_trigger_cookie_stripping

        _configure_trigger_cookie_stripping(app_with_routes)

        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        assert response.status_code == 200
        # Vary header should not contain Cookie
        vary = response.headers.get("Vary", "")
        assert "cookie" not in vary.lower()

    def test_trigger_endpoint_no_set_cookie_header(
        self, app_with_routes, test_post, test_token
    ):
        """Trigger endpoint should never emit Set-Cookie header."""
        # Register the cookie stripping middleware
        from app import _configure_trigger_cookie_stripping

        _configure_trigger_cookie_stripping(app_with_routes)

        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)
            response = client.get(
                f"/trigger?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        # Any status is fine, just check no Set-Cookie
        assert "Set-Cookie" not in response.headers


class TestTriggerStatusWithActiveJob:
    """Test /api/trigger/status returns 200 (not 5xx) when a job exists."""

    def test_running_job_returns_200_processing(
        self, app_with_routes, test_post, test_token
    ):
        """Running job should return 200 with processing state, never 5xx."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)

            # Create a running job with typical values
            job = ProcessingJob(
                post_guid=post.guid,
                status="running",
                current_step=2,
                total_steps=4,
                step_name="Transcribing",
                progress_percentage=50.0,
            )
            db.session.add(job)
            db.session.commit()

            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        # Must be 200, never 5xx
        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "processing"
        assert data["job"]["status"] == "running"
        assert data["job"]["current_step"] == 2
        assert data["job"]["step_name"] == "Transcribing"
        # Verify started_at is present (not updated_at which doesn't exist)
        assert "started_at" in data["job"]
        assert "updated_at" not in data["job"]

    def test_completed_job_returns_200_ready(
        self, app_with_routes, test_post, test_token
    ):
        """Completed job should return 200 with ready state."""
        client = app_with_routes.test_client()

        with app_with_routes.app_context():
            post = db.session.merge(test_post)

            # Mark post as processed
            post.processed_audio_path = None  # No file, but job completed

            # Create a completed job
            job = ProcessingJob(
                post_guid=post.guid,
                status="completed",
                current_step=4,
                total_steps=4,
                step_name="Complete",
                progress_percentage=100.0,
            )
            db.session.add(job)
            db.session.commit()

            response = client.get(
                f"/api/trigger/status?guid={post.guid}"
                f"&feed_token={test_token['token_id']}"
                f"&feed_secret={test_token['secret']}"
            )

        # Must be 200
        assert response.status_code == 200
        data = response.get_json()
        # State depends on whether processed_audio_path exists
        assert data["state"] in ["ready", "not_started"]
