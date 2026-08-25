"""API contracts for storage-cleanup policies and dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from app.auth import AuthSettings
from app.auth.middleware import SESSION_USER_KEY, init_auth_middleware
from app.config_store import ensure_defaults
from app.extensions import db
from app.models import AppSettings, Feed, User, UserFeedSubscription
from app.routes import config_routes, feed_routes
from app.routes.config_routes import config_bp
from app.routes.feed_routes import feed_bp
from app.storage_cleanup import MAX_RETENTION_COUNT


@pytest.fixture
def storage_routes_app(tmp_path: Path) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="storage-cleanup-test",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'storage-routes.sqlite3'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        AUTH_SETTINGS=AuthSettings(
            require_auth=True,
            admin_username="admin",
            admin_password="password",
        ),
        REQUIRE_AUTH=True,
    )
    app.testing = True

    db.init_app(app)
    with app.app_context():
        db.create_all()
        admin = User(username="cleanup-admin", role="admin")
        admin.set_password("password123")
        listener = User(username="cleanup-listener", role="user")
        listener.set_password("password123")
        feed = Feed(title="Cleanup Feed", rss_url="https://example.com/cleanup.xml")
        db.session.add_all(
            [
                admin,
                listener,
                feed,
                AppSettings(id=1, post_cleanup_retention_days=14),
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                UserFeedSubscription(user_id=admin.id, feed_id=feed.id),
                UserFeedSubscription(user_id=listener.id, feed_id=feed.id),
            ]
        )
        db.session.commit()
        ensure_defaults()
        app.config["TEST_IDS"] = {
            "admin": admin.id,
            "listener": listener.id,
            "feed": feed.id,
        }

    init_auth_middleware(app)
    app.register_blueprint(feed_bp)
    app.register_blueprint(config_bp)
    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()


def _login(app: Flask, client: Any, user: str) -> None:
    with client.session_transaction() as session:
        session[SESSION_USER_KEY] = app.config["TEST_IDS"][user]


def _feed_id(app: Flask) -> int:
    return int(app.config["TEST_IDS"]["feed"])


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        ("feed", "POST", {"retention_count": 3}),
        ("manual", "POST", None),
        ("config", "PUT", {"app": {"post_cleanup_retention_days": 3}}),
    ],
)
def test_cleanup_mutations_require_admin_when_auth_is_enabled(
    storage_routes_app: Flask,
    path: str,
    method: str,
    payload: dict[str, Any] | None,
) -> None:
    endpoint = (
        f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy"
        if path == "feed"
        else (
            "/api/admin/storage-cleanup/run" if path == "manual" else "/api/config"
        )
    )

    anonymous = storage_routes_app.test_client()
    assert anonymous.open(endpoint, method=method, json=payload).status_code == 401

    listener = storage_routes_app.test_client()
    _login(storage_routes_app, listener, "listener")
    assert listener.open(endpoint, method=method, json=payload).status_code == 403


def test_cleanup_routes_follow_auth_disabled_admin_convention(
    storage_routes_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_routes_app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=False,
        admin_username=None,
        admin_password=None,
    )
    calls: list[dict[str, Any]] = []
    dispatch = lambda **kwargs: calls.append(kwargs) or "scheduler_disabled"
    monkeypatch.setattr(feed_routes, "request_storage_cleanup", dispatch, raising=False)
    monkeypatch.setattr(config_routes, "request_storage_cleanup", dispatch, raising=False)

    client = storage_routes_app.test_client()
    feed_response = client.post(
        f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy",
        json={"retention_count": 2},
    )
    manual_response = client.post("/api/admin/storage-cleanup/run")

    assert feed_response.status_code == 202
    assert manual_response.status_code == 202
    assert calls == [
        {"feed_id": _feed_id(storage_routes_app), "trigger": "feed_policy_save"},
        {"trigger": "manual_admin"},
    ]


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -1, 1.5, "5", [], {}, 10**100],
)
def test_feed_cleanup_policy_rejects_non_positive_non_integer_and_excessive_values(
    storage_routes_app: Flask, value: Any
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.post(
        f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy",
        json={"retention_count": value},
    )

    assert response.status_code == 400
    with storage_routes_app.app_context():
        assert db.session.get(Feed, _feed_id(storage_routes_app)).processed_episode_retention_count is None


def test_feed_cleanup_policy_rejects_missing_and_malformed_json(
    storage_routes_app: Flask,
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")
    endpoint = f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy"

    assert client.post(endpoint, json={}).status_code == 400
    assert (
        client.post(
            endpoint,
            data='{"retention_count":',
            content_type="application/json",
        ).status_code
        == 400
    )


def test_feed_cleanup_policy_returns_404_for_missing_feed(
    storage_routes_app: Flask,
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.post(
        "/api/feeds/999999/cleanup-policy", json={"retention_count": 2}
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("saved_value", "expected_type", "expected_value_key", "expected_value"),
    [
        (3, "count", "retention_count", 3),
        (None, "age", "retention_days", 14),
    ],
)
def test_feed_cleanup_policy_commits_before_feed_scoped_dispatch(
    storage_routes_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    saved_value: int | None,
    expected_type: str,
    expected_value_key: str,
    expected_value: int,
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")
    dispatch_calls: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> str:
        feed = db.session.get(Feed, _feed_id(storage_routes_app))
        assert feed is not None
        assert feed.processed_episode_retention_count == saved_value
        assert not db.session.dirty
        dispatch_calls.append(kwargs)
        return "queued"

    monkeypatch.setattr(feed_routes, "request_storage_cleanup", dispatch, raising=False)

    response = client.post(
        f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy",
        json={"retention_count": saved_value},
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["feed_id"] == _feed_id(storage_routes_app)
    assert body["processed_episode_retention_count"] == saved_value
    assert body["effective_cleanup_policy"]["type"] == expected_type
    assert body["effective_cleanup_policy"][expected_value_key] == expected_value
    assert body["effective_cleanup_policy"]["orphan_maintenance_active"] is True
    assert body["cleanup_dispatch"] == {"requested": True, "status": "queued"}
    assert dispatch_calls == [
        {"feed_id": _feed_id(storage_routes_app), "trigger": "feed_policy_save"}
    ]


def test_disabled_inherited_age_policy_still_reports_orphan_maintenance(
    storage_routes_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with storage_routes_app.app_context():
        settings = db.session.get(AppSettings, 1)
        assert settings is not None
        settings.post_cleanup_retention_days = None
        db.session.commit()
    monkeypatch.setattr(
        feed_routes,
        "request_storage_cleanup",
        lambda **_kwargs: "scheduler_disabled",
        raising=False,
    )
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.post(
        f"/api/feeds/{_feed_id(storage_routes_app)}/cleanup-policy",
        json={"retention_count": None},
    )

    policy = response.get_json()["effective_cleanup_policy"]
    assert policy == {
        "type": "disabled",
        "source": "global",
        "retention_days": None,
        "inherited": True,
        "orphan_maintenance_active": True,
    }
    assert response.get_json()["cleanup_dispatch"]["status"] == "scheduler_disabled"


def test_feeds_response_serializes_configured_and_effective_cleanup_policy(
    storage_routes_app: Flask,
) -> None:
    with storage_routes_app.app_context():
        feed = db.session.get(Feed, _feed_id(storage_routes_app))
        assert feed is not None
        feed.processed_episode_retention_count = 4
        db.session.commit()
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "listener")

    response = client.get("/feeds")

    assert response.status_code == 200
    feed_payload = response.get_json()[0]
    assert feed_payload["processed_episode_retention_count"] == 4
    assert feed_payload["effective_cleanup_policy"] == {
        "type": "count",
        "source": "feed",
        "retention_count": 4,
        "inherited": False,
        "orphan_maintenance_active": True,
    }


@pytest.mark.parametrize("stored_value", [0, -1, MAX_RETENTION_COUNT + 1])
def test_feeds_response_reports_invalid_non_null_count_as_disabled_feed_policy(
    storage_routes_app: Flask, stored_value: int
) -> None:
    with storage_routes_app.app_context():
        feed = db.session.get(Feed, _feed_id(storage_routes_app))
        assert feed is not None
        feed.processed_episode_retention_count = stored_value
        db.session.commit()
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "listener")

    response = client.get("/feeds")

    assert response.status_code == 200
    assert response.get_json()[0]["effective_cleanup_policy"] == {
        "type": "disabled",
        "source": "feed",
        "retention_count": stored_value,
        "inherited": False,
        "invalid_configured_value": True,
        "orphan_maintenance_active": True,
    }


@pytest.mark.parametrize(
    ("old_value", "new_value"),
    [(None, 21), (14, 30), (14, 7)],
)
def test_positive_global_retention_changes_dispatch_after_commit_and_hydration(
    storage_routes_app: Flask,
    monkeypatch: pytest.MonkeyPatch,
    old_value: int | None,
    new_value: int,
) -> None:
    with storage_routes_app.app_context():
        settings = db.session.get(AppSettings, 1)
        assert settings is not None
        settings.post_cleanup_retention_days = old_value
        db.session.commit()
    dispatch_calls: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> str:
        settings = db.session.get(AppSettings, 1)
        assert settings is not None
        assert settings.post_cleanup_retention_days == new_value
        assert config_routes.runtime_config.post_cleanup_retention_days == new_value
        assert not db.session.dirty
        dispatch_calls.append(kwargs)
        return "coalesced"

    monkeypatch.setattr(config_routes, "request_storage_cleanup", dispatch, raising=False)
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put(
        "/api/config", json={"app": {"post_cleanup_retention_days": new_value}}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["config"]["app"]["post_cleanup_retention_days"] == new_value
    assert body["cleanup_dispatch"] == {"requested": True, "status": "coalesced"}
    assert dispatch_calls == [{"trigger": "global_policy_save"}]


def test_disabling_global_retention_saves_without_dispatch(
    storage_routes_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatch = pytest.fail
    monkeypatch.setattr(config_routes, "request_storage_cleanup", dispatch, raising=False)
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put(
        "/api/config", json={"app": {"post_cleanup_retention_days": None}}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["config"]["app"]["post_cleanup_retention_days"] is None
    assert body["cleanup_dispatch"] == {
        "requested": False,
        "status": "not_requested",
    }


def test_unrelated_config_save_reports_cleanup_not_requested(
    storage_routes_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        config_routes, "request_storage_cleanup", pytest.fail, raising=False
    )
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put("/api/config", json={"app": {"allow_signup": False}})

    assert response.status_code == 200
    assert response.get_json()["cleanup_dispatch"] == {
        "requested": False,
        "status": "not_requested",
    }


def test_config_update_envelope_keeps_raw_secrets_sanitized(
    storage_routes_app: Flask,
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put(
        "/api/config", json={"llm": {"llm_api_key": "sk-test-secret-value"}}
    )

    assert response.status_code == 200
    llm = response.get_json()["config"]["llm"]
    assert "llm_api_key" not in llm
    assert llm["llm_api_key_preview"] == "sk-t...alue"
    assert response.get_json()["cleanup_dispatch"]["status"] == "not_requested"


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "14", 10**100])
def test_global_retention_rejects_invalid_enabled_values(
    storage_routes_app: Flask, value: Any
) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put(
        "/api/config", json={"app": {"post_cleanup_retention_days": value}}
    )

    assert response.status_code == 400
    with storage_routes_app.app_context():
        assert db.session.get(AppSettings, 1).post_cleanup_retention_days == 14


def test_config_update_rejects_malformed_json(storage_routes_app: Flask) -> None:
    client = storage_routes_app.test_client()
    _login(storage_routes_app, client, "admin")

    response = client.put(
        "/api/config", data='{"app":', content_type="application/json"
    )

    assert response.status_code == 400
