from urllib.parse import quote

from app.auth import AuthSettings
from app.auth.feed_tokens import create_feed_access_token
from app.auth.middleware import SESSION_USER_KEY, init_auth_middleware
from app.extensions import db
from app.models import Feed, Post, User, UserFeedSubscription
from app.routes.post_routes import post_bp


def test_url_shaped_guid_routes_resolve(app):
    """Routes taking a guid must accept GUIDs containing slashes (feeds like
    Supercast publish URLs as GUIDs)."""
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    init_auth_middleware(app)
    app.register_blueprint(post_bp)

    guid = "https://pub.example.com/episodes/1"
    with app.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        user = User(username="listener", role="user")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        post = Post(
            feed_id=feed.id,
            guid=guid,
            download_url="https://cdn.example.com/ep1.mp3",
            title="Test Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as session:
            session[SESSION_USER_KEY] = user.id

        response = client.get(f"/post/{guid}/json")
        assert response.status_code == 200
        assert response.get_json()["guid"] == guid


def test_download_endpoints_increment_counter(app, tmp_path):
    """Ensure both processed and original downloads increment the counter."""
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    init_auth_middleware(app)
    app.register_blueprint(post_bp)

    with app.app_context():
        feed = Feed(title="Test Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        user = User(username="listener", role="user")
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()

        subscription = UserFeedSubscription(user_id=user.id, feed_id=feed.id)
        db.session.add(subscription)
        db.session.commit()

        processed_audio = tmp_path / "processed.mp3"
        processed_audio.write_bytes(b"processed audio")

        original_audio = tmp_path / "original.mp3"
        original_audio.write_bytes(b"original audio")

        post = Post(
            feed_id=feed.id,
            guid="test-guid",
            download_url="https://example.com/audio.mp3",
            title="Test Episode",
            processed_audio_path=str(processed_audio),
            unprocessed_audio_path=str(original_audio),
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as session:
            session[SESSION_USER_KEY] = user.id

        response = client.get(f"/api/posts/{post.guid}/download")
        assert response.status_code == 200
        db.session.refresh(post)
        assert post.download_count == 1

        response = client.get(f"/api/posts/{post.guid}/download/original")
        assert response.status_code == 200
        db.session.refresh(post)
        assert post.download_count == 2


def test_feed_token_scopes_duplicate_url_guid_audio_routes_to_its_feed(app, tmp_path):
    app.testing = True
    app.config["SECRET_KEY"] = "test-secret"
    app.config["AUTH_SETTINGS"] = AuthSettings(
        require_auth=True,
        admin_username="admin",
        admin_password="password",
    )
    app.config["REQUIRE_AUTH"] = True
    init_auth_middleware(app)
    app.register_blueprint(post_bp)

    guid = "https://latenightlinux.com/?p=4503"
    with app.app_context():
        user = User(username="listener", role="user")
        user.set_password("password123")
        first_feed = Feed(title="First Feed", rss_url="https://first.example/feed")
        token_feed = Feed(title="Token Feed", rss_url="https://second.example/feed")
        db.session.add_all([user, first_feed, token_feed])
        db.session.commit()

        first_audio = tmp_path / "first.mp3"
        first_audio.write_bytes(b"wrong feed audio")
        token_audio = tmp_path / "token.mp3"
        token_audio.write_bytes(b"token feed audio")
        first_original = tmp_path / "first-original.mp3"
        first_original.write_bytes(b"wrong original audio")
        token_original = tmp_path / "token-original.mp3"
        token_original.write_bytes(b"token original audio")
        db.session.add_all(
            [
                Post(
                    feed_id=first_feed.id,
                    guid=guid,
                    download_url="https://first.example/episode.mp3",
                    title="First Feed Episode",
                    processed_audio_path=str(first_audio),
                    unprocessed_audio_path=str(first_original),
                    whitelisted=True,
                ),
                Post(
                    feed_id=token_feed.id,
                    guid=guid,
                    download_url="https://second.example/episode.mp3",
                    title="Token Feed Episode",
                    processed_audio_path=str(token_audio),
                    unprocessed_audio_path=str(token_original),
                    whitelisted=True,
                ),
            ]
        )
        db.session.commit()
        token_id, secret = create_feed_access_token(user, token_feed)

        client = app.test_client()
        query_string = {"feed_token": token_id, "feed_secret": secret}
        for suffix, expected_audio in (
            ("download", b"token feed audio"),
            ("audio", b"token feed audio"),
            ("download/original", b"token original audio"),
        ):
            response = client.get(
                f"/api/posts/{quote(guid, safe='')}/{suffix}",
                query_string=query_string,
            )

            assert response.status_code == 200
            assert response.data == expected_audio
