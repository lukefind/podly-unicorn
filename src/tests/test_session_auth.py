from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask, Response, g, jsonify

import app.routes.auth_routes as auth_routes
from app.auth import AuthSettings
from app.auth.middleware import init_auth_middleware
from app.auth.state import failure_rate_limiter
from app.extensions import db
from app.models import AppSettings, EmailSettings, Feed, Post, User
from app.routes.auth_routes import auth_bp
from app.routes.feed_routes import feed_bp


@pytest.fixture
def auth_app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="test-secret",
        SESSION_COOKIE_NAME="podly_session",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    settings = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["AUTH_SETTINGS"] = settings
    app.config["REQUIRE_AUTH"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(username="admin", role="admin")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()

    failure_rate_limiter._storage.clear()

    init_auth_middleware(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(feed_bp)

    @app.route("/api/protected", methods=["GET"])
    def protected() -> Response:
        current = getattr(g, "current_user", None)
        if current is None:
            return jsonify({"error": "missing user"}), 500
        return jsonify({"status": "ok", "user": current.username})

    @app.route("/feed/1", methods=["GET"])
    def feed() -> Response:
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("ok", mimetype="text/plain")

    @app.route("/api/posts/<string:guid>/download", methods=["GET"])
    def download(guid: str) -> Response:
        del guid
        current = getattr(g, "current_user", None)
        if current is None:
            return Response("missing user", status=500)
        return Response("download", mimetype="text/plain")

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def test_login_sets_session_cookie_and_allows_authenticated_requests(
    auth_app: Flask,
) -> None:
    client = auth_app.test_client()

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert response.status_code == 200
    set_cookie = response.headers.get("Set-Cookie", "")
    assert "podly_session" in set_cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["user"]["username"] == "admin"

    protected = client.get("/api/protected")
    assert protected.status_code == 200
    assert protected.get_json()["status"] == "ok"


def test_logout_clears_session(auth_app: Flask) -> None:
    client = auth_app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    response = client.post("/api/auth/logout")
    assert response.status_code == 204

    protected = client.get("/api/protected")
    assert protected.status_code == 401
    assert protected.headers.get("WWW-Authenticate") is None


def test_login_allows_username_only_account(auth_app: Flask) -> None:
    with auth_app.app_context():
        user = User(username="listener", role="user")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

    client = auth_app.test_client()
    response = client.post(
        "/api/auth/login",
        json={"username": "listener", "password": "password123"},
    )

    assert response.status_code == 200
    assert response.get_json()["user"]["username"] == "listener"


def test_protected_route_without_session_returns_json_401(auth_app: Flask) -> None:
    client = auth_app.test_client()
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required."
    assert response.headers.get("WWW-Authenticate") is None


def test_feed_requires_token_when_no_session(auth_app: Flask) -> None:
    client = auth_app.test_client()

    unauthorized = client.get("/feed/1")
    assert unauthorized.status_code == 401
    assert "Invalid or missing feed token" in unauthorized.get_data(as_text=True)


def test_share_link_generates_token_and_allows_query_access(auth_app: Flask) -> None:
    client = auth_app.test_client()
    with auth_app.app_context():
        feed = Feed(title="Example", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()
        feed_id = feed.id

        post = Post(
            feed_id=feed_id,
            guid="episode-1",
            download_url="https://example.com/audio.mp3",
            title="Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

    client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    share = client.post(f"/api/feeds/{feed_id}/share-link")
    assert share.status_code == 201
    payload = share.get_json()
    assert payload["feed_id"] == feed_id

    token_id = payload["feed_token"]
    secret = payload["feed_secret"]

    parsed = urlparse(payload["url"])
    params = parse_qs(parsed.query)
    assert params.get("feed_token", [None])[0] == token_id
    assert params.get("feed_secret", [None])[0] == secret

    anon_client = auth_app.test_client()

    feed_response = anon_client.get(
        f"/feed/{feed_id}",
        query_string={"feed_token": token_id, "feed_secret": secret},
    )
    assert feed_response.status_code == 200
    assert feed_response.data == b"ok"

    download_response = anon_client.get(
        "/api/posts/episode-1/download",
        query_string={"feed_token": token_id, "feed_secret": secret},
    )
    assert download_response.status_code == 200


def test_share_link_returns_same_token_for_user_and_feed(auth_app: Flask) -> None:
    client = auth_app.test_client()
    with auth_app.app_context():
        feed = Feed(title="Stable", rss_url="https://example.com/stable.xml")
        db.session.add(feed)
        db.session.commit()
        feed_id = feed.id

    client.post("/api/auth/login", json={"username": "admin", "password": "password"})

    first = client.post(f"/api/feeds/{feed_id}/share-link").get_json()
    second = client.post(f"/api/feeds/{feed_id}/share-link").get_json()

    assert first["url"] == second["url"]
    assert first["feed_token"] == second["feed_token"]
    assert first["feed_secret"] == second["feed_secret"]


def test_signup_emails_use_unicorn_subjects(
    auth_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent_messages: list[dict[str, str]] = []
    monkeypatch.setattr(
        auth_routes, "send_email", lambda **message: sent_messages.append(message)
    )
    with auth_app.app_context():
        db.session.add(AppSettings(id=1, allow_signup=True))
        db.session.add(
            EmailSettings(
                id=1,
                admin_notify_email="owner@example.com",
                app_base_url="https://podly.example",
            )
        )
        db.session.commit()

    response = auth_app.test_client().post(
        "/api/auth/signup",
        json={"email": "listener@example.com", "password": "password123"},
    )

    assert response.status_code == 201
    assert [message["subject"] for message in sent_messages] == [
        "Podly Unicorn: Signup received",
        "Podly Unicorn: New signup pending approval",
    ]


def test_password_reset_email_uses_unicorn_subject(
    auth_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent_messages: list[dict[str, str]] = []
    monkeypatch.setattr(
        auth_routes, "send_email", lambda **message: sent_messages.append(message)
    )
    with auth_app.app_context():
        user = User(
            username="listener",
            email="listener@example.com",
            role="user",
            account_status="active",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

    response = auth_app.test_client().post(
        "/api/auth/password-reset/request",
        json={"email": "listener@example.com"},
    )

    assert response.status_code == 200
    assert [message["subject"] for message in sent_messages] == [
        "Podly Unicorn: Password reset"
    ]


def test_account_approval_email_uses_unicorn_subject(
    auth_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent_messages: list[dict[str, str]] = []
    monkeypatch.setattr(
        auth_routes, "send_email", lambda **message: sent_messages.append(message)
    )
    with auth_app.app_context():
        pending = User(
            username="pending",
            email="pending@example.com",
            role="user",
            account_status="pending",
        )
        pending.set_password("password123")
        db.session.add(pending)
        db.session.commit()
        pending_id = pending.id

    client = auth_app.test_client()
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "password"},
    )
    assert login.status_code == 200

    response = client.post(f"/api/admin/users/{pending_id}/approve")

    assert response.status_code == 200
    assert [message["subject"] for message in sent_messages] == [
        "Podly Unicorn: Account approved"
    ]
