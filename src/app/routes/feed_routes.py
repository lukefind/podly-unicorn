import logging
import re
from pathlib import Path
from threading import Thread
from typing import Any, cast
from urllib.parse import urlencode, urlparse, urlunparse

import requests
import validators
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    make_response,
    redirect,
    request,
    send_from_directory,
    url_for,
)
from flask.typing import ResponseReturnValue

from app.auth.feed_tokens import create_feed_access_token
from app.extensions import db
from app.feeds import add_or_refresh_feed, generate_feed_xml, refresh_feed
from app.jobs_manager import get_jobs_manager
from app.models import (
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
    User,
)
from podcast_processor.podcast_downloader import sanitize_title
from shared.processing_paths import get_in_root, get_srv_root

logger = logging.getLogger("global_logger")


feed_bp = Blueprint("feed", __name__)


def fix_url(url: str) -> str:
    url = re.sub(r"(http(s)?):/([^/])", r"\1://\3", url)
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


@feed_bp.route("/feed", methods=["POST"])
def add_feed() -> ResponseReturnValue:
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    url = request.form.get("url")
    if not url:
        return make_response(("URL is required", 400))

    url = fix_url(url)

    if not validators.url(url):
        return make_response(("Invalid URL", 400))

    try:
        feed = add_or_refresh_feed(url)
        
        # Auto-subscribe the user who added the feed
        settings = current_app.config.get("AUTH_SETTINGS")
        current = getattr(g, "current_user", None)
        if settings and settings.require_auth and current and feed:
            existing_sub = UserFeedSubscription.query.filter_by(
                user_id=current.id, feed_id=feed.id
            ).first()
            if not existing_sub:
                subscription = UserFeedSubscription(user_id=current.id, feed_id=feed.id)
                db.session.add(subscription)
                db.session.commit()
                logger.info(f"Auto-subscribed user {current.id} to feed {feed.id}")
        
        app = cast(Any, current_app)._get_current_object()
        Thread(
            target=_enqueue_pending_jobs_async,
            args=(app,),
            daemon=True,
            name="enqueue-jobs-after-add",
        ).start()
        
        # Return JSON for API calls, redirect for form submissions
        if request.headers.get('Accept', '').startswith('application/json') or request.is_json:
            return jsonify({"status": "success", "feed_id": feed.id, "title": feed.title})
        return redirect(url_for("main.index"))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error adding feed: {e}")
        if request.headers.get('Accept', '').startswith('application/json') or request.is_json:
            return jsonify({"error": str(e)}), 500
        return make_response((f"Error adding feed: {e}", 500))


@feed_bp.route("/api/feeds/<int:feed_id>/share-link", methods=["POST"])
def create_feed_share_link(feed_id: int) -> ResponseReturnValue:
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return jsonify({"error": "Authentication is disabled."}), 404

    current = getattr(g, "current_user", None)
    if current is None:
        return jsonify({"error": "Authentication required."}), 401

    feed = Feed.query.get_or_404(feed_id)
    user = User.query.get(current.id)
    if user is None:
        return jsonify({"error": "User not found."}), 404

    token_id, secret = create_feed_access_token(user, feed)

    parsed = urlparse(request.host_url)
    netloc = parsed.netloc
    scheme = parsed.scheme
    path = f"/feed/{feed.id}"
    query = urlencode({"feed_token": token_id, "feed_secret": secret})
    prefilled_url = urlunparse((scheme, netloc, path, "", query, ""))

    return (
        jsonify(
            {
                "url": prefilled_url,
                "feed_token": token_id,
                "feed_secret": secret,
                "feed_id": feed.id,
            }
        ),
        201,
    )


@feed_bp.route("/api/feeds/search", methods=["GET"])
def search_feeds() -> ResponseReturnValue:
    term = (request.args.get("term") or "").strip()
    if not term:
        return jsonify({"error": "term parameter is required"}), 400

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }
        response = requests.get(
            "http://api.podcastindex.org/search",
            headers=headers,
            params={"term": term},
            timeout=10,
        )
        response.raise_for_status()
        upstream_data = response.json()
    except requests.exceptions.RequestException as exc:
        logger.error("Podcast search request failed: %s", exc)
        return jsonify({"error": "Search request failed"}), 502
    except ValueError:
        logger.error("Podcast search returned non-JSON response")
        return (
            jsonify({"error": "Unexpected response from search provider"}),
            502,
        )

    results = upstream_data.get("results") or []
    transformed_results = []

    for item in results:
        feed_url = item.get("feedUrl")
        if not feed_url:
            continue

        transformed_results.append(
            {
                "title": item.get("collectionName")
                or item.get("trackName")
                or "Unknown title",
                "author": item.get("artistName") or "",
                "feedUrl": feed_url,
                "artworkUrl": item.get("artworkUrl100")
                or item.get("artworkUrl600")
                or "",
                "description": item.get("collectionCensoredName")
                or item.get("trackCensoredName")
                or "",
                "genres": item.get("genres") or [],
            }
        )

    total = upstream_data.get("resultCount")
    if not isinstance(total, int) or total == 0:
        total = len(transformed_results)

    return jsonify(
        {
            "results": transformed_results,
            "total": total,
        }
    )


@feed_bp.route("/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> Response:
    feed = Feed.query.get_or_404(f_id)

    # Refresh the feed
    refresh_feed(feed)

    # Generate the XML
    xml_content = generate_feed_xml(feed)

    response = make_response(xml_content)
    response.headers["Content-Type"] = "application/rss+xml"
    return response


@feed_bp.route("/feed/<int:f_id>", methods=["DELETE"])
def delete_feed(f_id: int) -> Response:
    """Delete a feed. For non-admin users, this unsubscribes them from the feed.
    The feed is only fully deleted if no other subscribers remain."""
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    feed = Feed.query.get_or_404(f_id)
    
    settings = current_app.config.get("AUTH_SETTINGS")
    current = getattr(g, "current_user", None)
    
    # If auth is enabled, handle subscription-based deletion
    if settings and settings.require_auth and current:
        user = User.query.get(current.id)
        
        # Remove user's subscription to this feed
        subscription = UserFeedSubscription.query.filter_by(
            user_id=current.id, feed_id=f_id
        ).first()
        if subscription:
            db.session.delete(subscription)
            db.session.commit()
        
        # Count remaining subscribers
        remaining_subscribers = UserFeedSubscription.query.filter_by(feed_id=f_id).count()
        
        # If there are still other subscribers, just unsubscribe (don't delete feed)
        if remaining_subscribers > 0:
            logger.info(f"User {current.id} unsubscribed from feed {f_id}. {remaining_subscribers} subscribers remain.")
            return make_response("", 204)
        
        # No remaining subscribers - proceed to full deletion
        logger.info(f"Feed {f_id} has no remaining subscribers. Proceeding with full deletion.")
    
    # Full deletion (admin or no auth)
    from app.models import FeedAccessToken, ProcessingStatistics, UserDownload  # pylint: disable=import-outside-toplevel
    from sqlalchemy import text  # pylint: disable=import-outside-toplevel
    
    # Store info before we start deleting
    feed_id_to_delete = feed.id
    feed_title = feed.title
    
    # Get post info for file cleanup (before we touch the session)
    posts_info = [(post.id, post.guid, post.unprocessed_audio_path, post.processed_audio_path) 
                  for post in feed.posts]
    post_ids = [p[0] for p in posts_info]
    post_guids = [p[1] for p in posts_info]

    # Delete audio files if they exist
    for _, _, unprocessed_path, processed_path in posts_info:
        if unprocessed_path and Path(unprocessed_path).exists():
            try:
                Path(unprocessed_path).unlink()
                logger.info(f"Deleted unprocessed audio: {unprocessed_path}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Error deleting unprocessed audio {unprocessed_path}: {e}")

        if processed_path and Path(processed_path).exists():
            try:
                Path(processed_path).unlink()
                logger.info(f"Deleted processed audio: {processed_path}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(f"Error deleting processed audio {processed_path}: {e}")

    # Clean up directory structures
    _cleanup_feed_directories(feed)
    
    # Rollback any pending changes and use raw SQL to avoid ORM cascade issues
    db.session.rollback()

    # Delete all related records using raw SQL in correct order
    if post_ids:
        post_ids_str = ','.join(str(pid) for pid in post_ids)
        
        # Get transcript segment IDs for this feed's posts
        segment_ids_result = db.session.execute(
            text(f"SELECT id FROM transcript_segment WHERE post_id IN ({post_ids_str})")
        ).fetchall()
        segment_ids = [r[0] for r in segment_ids_result]
        
        if segment_ids:
            segment_ids_str = ','.join(str(sid) for sid in segment_ids)
            # Delete identifications
            db.session.execute(
                text(f"DELETE FROM identification WHERE transcript_segment_id IN ({segment_ids_str})")
            )
        
        # Delete transcript segments
        db.session.execute(text(f"DELETE FROM transcript_segment WHERE post_id IN ({post_ids_str})"))
        
        # Delete model calls
        db.session.execute(text(f"DELETE FROM model_call WHERE post_id IN ({post_ids_str})"))
        
        # Delete processing statistics
        db.session.execute(text(f"DELETE FROM processing_statistics WHERE post_id IN ({post_ids_str})"))
        
        # Delete user downloads
        db.session.execute(text(f"DELETE FROM user_download WHERE post_id IN ({post_ids_str})"))
    
    # Delete processing jobs by guid
    if post_guids:
        guids_str = ','.join(f"'{g}'" for g in post_guids)
        db.session.execute(text(f"DELETE FROM processing_job WHERE post_guid IN ({guids_str})"))
    
    # Delete posts
    db.session.execute(text(f"DELETE FROM post WHERE feed_id = {feed_id_to_delete}"))
    
    # Delete subscriptions
    db.session.execute(text(f"DELETE FROM user_feed_subscription WHERE feed_id = {feed_id_to_delete}"))
    
    # Delete feed access tokens
    db.session.execute(text(f"DELETE FROM feed_access_token WHERE feed_id = {feed_id_to_delete}"))
    
    # Delete the feed
    db.session.execute(text(f"DELETE FROM feed WHERE id = {feed_id_to_delete}"))
    
    db.session.commit()

    logger.info(f"Deleted feed: {feed_title} (ID: {feed_id_to_delete}) with {len(post_ids)} posts")
    return make_response("", 204)


@feed_bp.route("/api/feeds/<int:f_id>/refresh", methods=["POST"])
def refresh_feed_endpoint(f_id: int) -> ResponseReturnValue:
    """
    Refresh the specified feed and return a JSON response indicating the result.
    """
    feed = Feed.query.get_or_404(f_id)
    feed_title = feed.title
    app = cast(Any, current_app)._get_current_object()

    Thread(
        target=_refresh_feed_background,
        args=(app, f_id),
        daemon=True,
        name=f"feed-refresh-{f_id}",
    ).start()

    return (
        jsonify(
            {
                "status": "accepted",
                "message": f'Feed "{feed_title}" refresh queued for processing',
            }
        ),
        202,
    )


def _refresh_feed_background(app: Flask, feed_id: int) -> None:
    with app.app_context():
        feed = Feed.query.get(feed_id)
        if not feed:
            logger.warning("Feed %s disappeared before refresh could run", feed_id)
            return

        try:
            refresh_feed(feed)
            get_jobs_manager().enqueue_pending_jobs(
                trigger="feed_refresh", context={"feed_id": feed_id}
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to refresh feed %s asynchronously: %s", feed_id, exc)


@feed_bp.route("/api/feeds/refresh-all", methods=["POST"])
def refresh_all_feeds_endpoint() -> Response:
    """Trigger a refresh for all feeds and enqueue pending jobs."""
    result = get_jobs_manager().start_refresh_all_feeds(trigger="manual_refresh")
    feed_count = Feed.query.count()
    return jsonify(
        {
            "status": "success",
            "feeds_refreshed": feed_count,
            "jobs_enqueued": result.get("enqueued", 0),
        }
    )


def _enqueue_pending_jobs_async(app: Flask) -> None:
    with app.app_context():
        try:
            get_jobs_manager().enqueue_pending_jobs(trigger="feed_refresh")
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to enqueue pending jobs asynchronously: %s", exc)


def _cleanup_feed_directories(feed: Feed) -> None:
    """
    Clean up directory structures for a feed in both in/ and srv/ directories.

    Args:
        feed: The Feed object being deleted
    """
    # Clean up srv/ directory (processed audio)
    # srv/{sanitized_feed_title}/
    sanitized_feed_title = sanitize_title(feed.title)
    # Use the same sanitization logic as in processing_paths.py
    sanitized_feed_title = re.sub(
        r"[^a-zA-Z0-9\s_.-]", "", sanitized_feed_title
    ).strip()
    sanitized_feed_title = sanitized_feed_title.rstrip(".")
    sanitized_feed_title = re.sub(r"\s+", "_", sanitized_feed_title)

    srv_feed_dir = get_srv_root() / sanitized_feed_title
    if srv_feed_dir.exists() and srv_feed_dir.is_dir():
        try:
            # Remove all files in the directory first
            for file_path in srv_feed_dir.iterdir():
                if file_path.is_file():
                    file_path.unlink()
                    logger.info(f"Deleted processed audio file: {file_path}")
            # Remove the directory itself
            srv_feed_dir.rmdir()
            logger.info(f"Deleted processed audio directory: {srv_feed_dir}")
        except Exception as e:  # pylint: disable=broad-except
            logger.error(
                f"Error deleting processed audio directory {srv_feed_dir}: {e}"
            )

    # Clean up in/ directories (unprocessed audio)
    # in/{sanitized_post_title}/
    for post in feed.posts:  # type: ignore[attr-defined]
        sanitized_post_title = sanitize_title(post.title)
        in_post_dir = get_in_root() / sanitized_post_title
        if in_post_dir.exists() and in_post_dir.is_dir():
            try:
                # Remove all files in the directory first
                for file_path in in_post_dir.iterdir():
                    if file_path.is_file():
                        file_path.unlink()
                        logger.info(f"Deleted unprocessed audio file: {file_path}")
                # Remove the directory itself
                in_post_dir.rmdir()
                logger.info(f"Deleted unprocessed audio directory: {in_post_dir}")
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    f"Error deleting unprocessed audio directory {in_post_dir}: {e}"
                )


@feed_bp.route("/<path:something_or_rss>", methods=["GET"])
def get_feed_by_alt_or_url(something_or_rss: str) -> Response:
    # first try to serve ANY static file matching the path
    if current_app.static_folder is not None:
        # Use Flask's safe helper to prevent directory traversal outside static_folder
        try:
            return send_from_directory(current_app.static_folder, something_or_rss)
        except Exception:
            # Not a valid static file; fall through to RSS/DB lookup
            pass
    feed = Feed.query.filter_by(rss_url=something_or_rss).first()
    if feed:
        xml_content = generate_feed_xml(feed)
        response = make_response(xml_content)
        response.headers["Content-Type"] = "application/rss+xml"
        return response

    return make_response(("Feed not found", 404))


@feed_bp.route("/feeds", methods=["GET"])
def api_feeds() -> Response:
    """Get feeds list. All users (including admins) only see feeds they've subscribed to."""
    from sqlalchemy import func  # pylint: disable=import-outside-toplevel
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    settings = current_app.config.get("AUTH_SETTINGS")
    current = getattr(g, "current_user", None)
    
    # Build base query with posts count (efficient single query)
    base_query = db.session.query(
        Feed,
        func.count(Post.id).label('posts_count')
    ).outerjoin(Post, Feed.id == Post.feed_id).group_by(Feed.id)
    
    # Get user's subscription privacy status
    subscriptions_map: dict = {}  # feed_id -> is_private
    if settings and settings.require_auth and current:
        for sub in UserFeedSubscription.query.filter_by(user_id=current.id).all():
            subscriptions_map[sub.feed_id] = sub.is_private
        # Filter to subscribed feeds only
        base_query = base_query.filter(Feed.id.in_(subscriptions_map.keys()))
    
    results = base_query.all()
    
    feeds_data = [
        {
            "id": feed.id,
            "title": feed.title,
            "rss_url": feed.rss_url,
            "description": feed.description,
            "author": feed.author,
            "image_url": feed.image_url,
            "posts_count": posts_count,
            "is_private": subscriptions_map.get(feed.id, False),
        }
        for feed, posts_count in results
    ]
    return jsonify(feeds_data)


@feed_bp.route("/api/feeds/<int:feed_id>/subscribe", methods=["POST"])
def subscribe_to_feed(feed_id: int) -> ResponseReturnValue:
    """Subscribe the current user to a feed. Optionally mark as private."""
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return jsonify({"error": "Authentication is disabled."}), 404
    
    current = getattr(g, "current_user", None)
    if current is None:
        return jsonify({"error": "Authentication required."}), 401
    
    feed = Feed.query.get_or_404(feed_id)
    
    # Get private flag from request
    is_private = request.json.get("private", False) if request.is_json else False
    
    # Check if already subscribed
    existing = UserFeedSubscription.query.filter_by(
        user_id=current.id, feed_id=feed_id
    ).first()
    
    if existing:
        # Update privacy setting if changed
        if existing.is_private != is_private:
            existing.is_private = is_private
            db.session.commit()
            return jsonify({"message": "Subscription updated", "subscribed": True, "is_private": is_private})
        return jsonify({"message": "Already subscribed", "subscribed": True, "is_private": existing.is_private})
    
    subscription = UserFeedSubscription(user_id=current.id, feed_id=feed_id, is_private=is_private)
    db.session.add(subscription)
    db.session.commit()
    
    return jsonify({"message": f"Subscribed to {feed.title}", "subscribed": True, "is_private": is_private})


@feed_bp.route("/api/feeds/<int:feed_id>/unsubscribe", methods=["POST"])
def unsubscribe_from_feed(feed_id: int) -> ResponseReturnValue:
    """Unsubscribe the current user from a feed."""
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return jsonify({"error": "Authentication is disabled."}), 404
    
    current = getattr(g, "current_user", None)
    if current is None:
        return jsonify({"error": "Authentication required."}), 401
    
    subscription = UserFeedSubscription.query.filter_by(
        user_id=current.id, feed_id=feed_id
    ).first()
    
    if subscription:
        db.session.delete(subscription)
        db.session.commit()
        return jsonify({"message": "Unsubscribed", "subscribed": False})
    
    return jsonify({"message": "Not subscribed", "subscribed": False})


@feed_bp.route("/api/feeds/all", methods=["GET"])
def api_all_feeds() -> Response:
    """Get all feeds with subscription status - for subscription management.
    
    Only shows feeds that have at least one PUBLIC subscriber, OR feeds the current user is subscribed to.
    This ensures privately-subscribed-only feeds remain hidden from other users.
    """
    from sqlalchemy import func  # pylint: disable=import-outside-toplevel
    from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
    
    current = getattr(g, "current_user", None)
    
    # Get user's subscriptions with privacy status
    user_subscriptions: dict = {}  # feed_id -> is_private
    if current:
        for sub in UserFeedSubscription.query.filter_by(user_id=current.id).all():
            user_subscriptions[sub.feed_id] = sub.is_private
    
    # Get feeds that have at least one PUBLIC subscription
    feeds_with_public_subs = set(
        row[0] for row in 
        db.session.query(UserFeedSubscription.feed_id)
        .filter_by(is_private=False)
        .distinct()
        .all()
    )
    
    # Efficient query with posts count
    results = db.session.query(
        Feed,
        func.count(Post.id).label('posts_count')
    ).outerjoin(Post, Feed.id == Post.feed_id).group_by(Feed.id).all()
    
    feeds_data = []
    for feed, posts_count in results:
        # Show feed if:
        # 1. User is already subscribed to it (so they can manage their subscription), OR
        # 2. Feed has at least one public subscriber (so it's "discoverable")
        is_user_subscribed = feed.id in user_subscriptions
        has_public_subscriber = feed.id in feeds_with_public_subs
        
        if is_user_subscribed or has_public_subscriber:
            feeds_data.append({
                "id": feed.id,
                "title": feed.title,
                "rss_url": feed.rss_url,
                "description": feed.description,
                "author": feed.author,
                "image_url": feed.image_url,
                "posts_count": posts_count,
                "is_subscribed": is_user_subscribed,
                "is_private": user_subscriptions.get(feed.id, False),
            })
    
    return jsonify(feeds_data)


@feed_bp.route("/api/admin/feed-subscriptions", methods=["GET"])
def api_admin_feed_subscriptions() -> ResponseReturnValue:
    """Admin endpoint: Get all feeds with subscriber details and stats."""
    from sqlalchemy import func  # pylint: disable=import-outside-toplevel
    from app.models import UserFeedSubscription, ProcessingStatistics  # pylint: disable=import-outside-toplevel
    
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return jsonify({"error": "Authentication is disabled."}), 404
    
    current = getattr(g, "current_user", None)
    if current is None:
        return jsonify({"error": "Authentication required."}), 401
    
    user = User.query.get(current.id)
    if not user or user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403
    
    # Get all feeds with posts count
    feeds_with_counts = db.session.query(
        Feed,
        func.count(Post.id).label('posts_count')
    ).outerjoin(Post, Feed.id == Post.feed_id).group_by(Feed.id).all()
    
    # Get all subscriptions grouped by feed (including private - admin sees all for usage tracking)
    all_subscriptions = UserFeedSubscription.query.all()
    subscriptions_by_feed: dict = {}
    for sub in all_subscriptions:
        if sub.feed_id not in subscriptions_by_feed:
            subscriptions_by_feed[sub.feed_id] = []
        subscriptions_by_feed[sub.feed_id].append({
            "user_id": sub.user_id,
            "username": sub.user.username if sub.user else "Unknown",
            "subscribed_at": sub.subscribed_at.isoformat() if sub.subscribed_at else None,
            "is_private": sub.is_private,
        })
    
    # Get processing stats per feed
    feed_stats: dict = {}
    for feed, _ in feeds_with_counts:
        processed_count = Post.query.filter(
            Post.feed_id == feed.id,
            Post.processed_audio_path.isnot(None)
        ).count()
        
        # Sum ad time removed for this feed
        total_ad_time = db.session.query(
            func.sum(ProcessingStatistics.total_duration_removed_seconds)
        ).join(Post, ProcessingStatistics.post_id == Post.id).filter(
            Post.feed_id == feed.id
        ).scalar() or 0.0
        
        feed_stats[feed.id] = {
            "processed_count": processed_count,
            "total_ad_time_removed": round(total_ad_time, 1),
        }
    
    feeds_data = [
        {
            "id": feed.id,
            "title": feed.title,
            "rss_url": feed.rss_url,
            "description": feed.description,
            "author": feed.author,
            "image_url": feed.image_url,
            "posts_count": posts_count,
            "subscribers": subscriptions_by_feed.get(feed.id, []),
            "subscriber_count": len(subscriptions_by_feed.get(feed.id, [])),
            "stats": feed_stats.get(feed.id, {"processed_count": 0, "total_ad_time_removed": 0}),
        }
        for feed, posts_count in feeds_with_counts
    ]
    
    # Sort by subscriber count descending
    feeds_data.sort(key=lambda x: x["subscriber_count"], reverse=True)
    
    return jsonify({
        "feeds": feeds_data,
        "total_feeds": len(feeds_data),
        "total_subscriptions": len(all_subscriptions),
    })
