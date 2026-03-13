from app.auth import AuthSettings
from app.auth.middleware import SESSION_USER_KEY, init_auth_middleware
from app.extensions import db
from app.models import Feed, Post, User, UserFeedSubscription
from app.routes.post_routes import post_bp


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


def test_processed_download_endpoint_advertises_streaming_headers(app, tmp_path):
    """Processed enclosure responses should look streamable to podcast apps."""
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
        processed_audio.write_bytes(b"0123456789" * 1000)

        post = Post(
            feed_id=feed.id,
            guid="stream-guid",
            download_url="https://example.com/audio.mp3",
            title="Streaming Episode",
            processed_audio_path=str(processed_audio),
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as session:
            session[SESSION_USER_KEY] = user.id

        response = client.get(f"/api/posts/{post.guid}/download")
        assert response.status_code == 200
        assert response.headers["Accept-Ranges"] == "bytes"
        assert "attachment" not in response.headers.get("Content-Disposition", "")

        head_response = client.open(
            f"/api/posts/{post.guid}/download",
            method="HEAD",
        )
        assert head_response.status_code == 200
        assert head_response.headers["Accept-Ranges"] == "bytes"
        assert "attachment" not in head_response.headers.get("Content-Disposition", "")

        range_response = client.get(
            f"/api/posts/{post.guid}/download",
            headers={"Range": "bytes=0-99"},
        )
        assert range_response.status_code == 206
        assert range_response.headers["Accept-Ranges"] == "bytes"
        assert range_response.headers["Content-Range"] == "bytes 0-99/10000"
