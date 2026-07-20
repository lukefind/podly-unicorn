"""Tests for RSS poll cost: ETag/Last-Modified 304s and async debounced refresh."""

import datetime
import uuid
from unittest import mock

import feedparser
import pytest

from app.extensions import db
from app.feeds import refresh_feed
from app.models import Feed, Post
from app.routes import feed_routes
from app.routes.feed_routes import feed_bp


@pytest.fixture
def feed_app(app):
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.register_blueprint(feed_bp)
    # Isolate the module-level debounce registry between tests.
    feed_routes._BACKGROUND_REFRESH_LAST_KICKOFF.clear()
    yield app
    feed_routes._BACKGROUND_REFRESH_LAST_KICKOFF.clear()


def _create_feed():
    feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
    db.session.add(feed)
    db.session.commit()
    return feed


def test_get_feed_sets_cache_validator_headers(feed_app):
    feed = _create_feed()
    client = feed_app.test_client()

    with mock.patch.object(feed_routes, "_spawn_async_refresh"):
        response = client.get(f"/feed/{feed.id}")

    assert response.status_code == 200
    assert response.headers.get("ETag")
    assert response.headers.get("Last-Modified")
    assert "max-age=60" in response.headers.get("Cache-Control", "")


def test_get_feed_returns_304_when_client_is_current(feed_app):
    feed = _create_feed()
    client = feed_app.test_client()

    with mock.patch.object(feed_routes, "_spawn_async_refresh"):
        first = client.get(f"/feed/{feed.id}")
        etag = first.headers.get("ETag")
        assert etag

        second = client.get(f"/feed/{feed.id}", headers={"If-None-Match": etag})

    assert second.status_code == 304
    assert second.get_data() == b""
    assert second.headers.get("ETag") == etag


def test_get_feed_returns_200_again_after_feed_changes(feed_app):
    feed = _create_feed()
    client = feed_app.test_client()

    with mock.patch.object(feed_routes, "_spawn_async_refresh"):
        first = client.get(f"/feed/{feed.id}")
        etag = first.headers.get("ETag")

        feed.last_changed_at = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=5
        )
        db.session.commit()

        third = client.get(f"/feed/{feed.id}", headers={"If-None-Match": etag})

    assert third.status_code == 200
    assert third.headers.get("ETag") != etag


def test_get_feed_does_not_refresh_synchronously(feed_app):
    feed = _create_feed()
    client = feed_app.test_client()

    with (
        mock.patch.object(feed_routes, "refresh_feed") as mock_refresh,
        mock.patch.object(feed_routes, "_spawn_async_refresh") as mock_spawn,
    ):
        response = client.get(f"/feed/{feed.id}")

    assert response.status_code == 200
    mock_refresh.assert_not_called()
    mock_spawn.assert_called_once()


def test_async_refresh_is_debounced_per_feed(feed_app):
    feed = _create_feed()
    client = feed_app.test_client()

    with mock.patch.object(feed_routes, "_spawn_async_refresh") as mock_spawn:
        client.get(f"/feed/{feed.id}")
        client.get(f"/feed/{feed.id}")

    assert mock_spawn.call_count == 1


def _entry(audio_url, guid, title="Ep"):
    entry = feedparser.FeedParserDict()
    link = feedparser.FeedParserDict()
    link["type"] = "audio/mpeg"
    link["href"] = audio_url
    entry["links"] = [link]
    entry["id"] = guid
    entry["title"] = title
    return entry


def _feed_data(entries):
    feed_data = feedparser.FeedParserDict()
    feed_data["feed"] = feedparser.FeedParserDict()
    feed_data["entries"] = entries
    return feed_data


def test_refresh_feed_touches_last_changed_at_on_new_post(app):
    feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
    db.session.add(feed)
    db.session.commit()
    before = feed.last_changed_at

    entries = [_entry("https://cdn.example.com/ep1.mp3", "guid-1")]
    with mock.patch("app.feeds.fetch_feed", return_value=_feed_data(entries)):
        refresh_feed(feed)

    assert feed.last_changed_at is not None
    assert before is None or feed.last_changed_at > before


def test_refresh_feed_leaves_last_changed_at_when_nothing_changed(app):
    feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
    db.session.add(feed)
    db.session.commit()

    entries = [_entry("https://cdn.example.com/ep1.mp3", "guid-1")]
    with mock.patch("app.feeds.fetch_feed", return_value=_feed_data(entries)):
        refresh_feed(feed)
    marker = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    feed.last_changed_at = marker
    db.session.commit()

    with mock.patch("app.feeds.fetch_feed", return_value=_feed_data(entries)):
        refresh_feed(feed)

    assert feed.last_changed_at == marker
