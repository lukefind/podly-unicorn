from __future__ import annotations

import logging
from typing import cast

from flask import Blueprint, Response, current_app, g, jsonify, request, session

from app.auth.service import (
    AuthServiceError,
    DuplicateUserError,
    InvalidCredentialsError,
    LastAdminRemovalError,
    PasswordValidationError,
    authenticate,
    change_password,
    create_user,
    delete_user,
    list_users,
    set_role,
    update_password,
)
from app.auth.state import failure_rate_limiter
from app.models import Feed, Post, ProcessingJob, ProcessingStatistics, User, UserDownload

logger = logging.getLogger("global_logger")


auth_bp = Blueprint("auth", __name__)

RouteResult = Response | tuple[Response, int] | tuple[Response, int, dict[str, str]]

SESSION_USER_KEY = "user_id"


def _auth_enabled() -> bool:
    settings = current_app.config.get("AUTH_SETTINGS")
    return bool(settings and settings.require_auth)


@auth_bp.route("/api/auth/status", methods=["GET"])
def auth_status() -> Response:
    return jsonify({"require_auth": _auth_enabled()})


@auth_bp.route("/api/auth/login", methods=["POST"])
def login() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    client_identifier = request.remote_addr or "unknown"
    retry_after = failure_rate_limiter.retry_after(client_identifier)
    if retry_after:
        return (
            jsonify({"error": "Too many failed attempts.", "retry_after": retry_after}),
            429,
            {"Retry-After": str(retry_after)},
        )

    authenticated = authenticate(username, password)
    if authenticated is None:
        backoff = failure_rate_limiter.register_failure(client_identifier)
        response_headers: dict[str, str] = {}
        if backoff:
            response_headers["Retry-After"] = str(backoff)
        response = jsonify({"error": "Invalid username or password."})
        if response_headers:
            return response, 401, response_headers
        return response, 401

    failure_rate_limiter.register_success(client_identifier)
    session.clear()
    session[SESSION_USER_KEY] = authenticated.id
    session.permanent = True
    return jsonify(
        {
            "user": {
                "id": authenticated.id,
                "username": authenticated.username,
                "role": authenticated.role,
            }
        }
    )


@auth_bp.route("/api/auth/logout", methods=["POST"])
def logout() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    if getattr(g, "current_user", None) is None:
        session.clear()
        return jsonify({"error": "Authentication required."}), 401

    session.clear()
    return Response(status=204)


@auth_bp.route("/api/auth/me", methods=["GET"])
def auth_me() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    return jsonify(
        {
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
            }
        }
    )


@auth_bp.route("/api/auth/change-password", methods=["POST"])
def change_password_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    payload = request.get_json(silent=True) or {}
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""

    if not current_password or not new_password:
        return (
            jsonify({"error": "Current and new passwords are required."}),
            400,
        )

    try:
        change_password(user, current_password, new_password)
    except InvalidCredentialsError as exc:
        return jsonify({"error": str(exc)}), 401
    except PasswordValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except AuthServiceError as exc:  # fallback
        logger.error("Password change failed: %s", exc)
        return jsonify({"error": "Unable to change password."}), 500

    return jsonify({"status": "ok"})


@auth_bp.route("/api/auth/users", methods=["GET"])
def list_users_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    if not user.role == "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    users = list_users()
    return jsonify(
        {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "role": u.role,
                    "created_at": u.created_at.isoformat(),
                    "updated_at": u.updated_at.isoformat(),
                }
                for u in users
            ]
        }
    )


@auth_bp.route("/api/auth/users", methods=["POST"])
def create_user_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()
    if user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or "user").strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    try:
        new_user = create_user(username, password, role)
    except (PasswordValidationError, DuplicateUserError, AuthServiceError) as exc:
        status = 409 if isinstance(exc, DuplicateUserError) else 400
        return jsonify({"error": str(exc)}), status

    return (
        jsonify(
            {
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "role": new_user.role,
                    "created_at": new_user.created_at.isoformat(),
                    "updated_at": new_user.updated_at.isoformat(),
                }
            }
        ),
        201,
    )


@auth_bp.route("/api/auth/users/<string:username>", methods=["PATCH"])
def update_user_route(username: str) -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    acting_user = _require_authenticated_user()
    if acting_user is None:
        return _unauthorized_response()

    if acting_user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    target = User.query.filter_by(username=username.lower()).first()
    if target is None:
        return jsonify({"error": "User not found."}), 404

    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    new_password = payload.get("password")

    try:
        if role is not None:
            set_role(target, role)
        if new_password:
            update_password(target, new_password)
        return jsonify({"status": "ok"})
    except (PasswordValidationError, LastAdminRemovalError, AuthServiceError) as exc:
        status_code = 400
        return jsonify({"error": str(exc)}), status_code


@auth_bp.route("/api/auth/users/<string:username>", methods=["DELETE"])
def delete_user_route(username: str) -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    acting_user = _require_authenticated_user()
    if acting_user is None:
        return _unauthorized_response()
    if acting_user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    target = User.query.filter_by(username=username.lower()).first()
    if target is None:
        return jsonify({"error": "User not found."}), 404

    try:
        delete_user(target)
    except LastAdminRemovalError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"status": "ok"})


def _require_authenticated_user() -> User | None:
    if not _auth_enabled():
        return None

    current = getattr(g, "current_user", None)
    if current is None:
        return None

    return cast(User | None, User.query.get(current.id))


def _unauthorized_response() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    return jsonify({"error": "Authentication required."}), 401


@auth_bp.route("/api/admin/user-stats", methods=["GET"])
def admin_user_stats() -> RouteResult:
    """Get usage statistics for all users. Admin only."""
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()
    if user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    from sqlalchemy import func
    from app.extensions import db

    users = User.query.all()
    user_stats = []

    for u in users:
        # Episodes processed (triggered by this user)
        episodes_processed = (
            ProcessingJob.query.filter_by(
                triggered_by_user_id=u.id, status="completed"
            ).count()
        )

        # Downloads by this user
        downloads = UserDownload.query.filter_by(user_id=u.id).all()
        total_downloads = len(downloads)
        processed_downloads = len([d for d in downloads if d.is_processed])

        # Total ad time removed from processed downloads by this user
        # This counts ad time saved for episodes the user actually downloaded
        ad_time_removed = 0.0
        seen_post_ids = set()
        for download in downloads:
            if download.is_processed and download.post_id not in seen_post_ids:
                seen_post_ids.add(download.post_id)
                post = download.post
                if post and post.statistics:
                    ad_time_removed += post.statistics.total_duration_removed_seconds

        # Last activity (most recent download or job)
        last_download = (
            UserDownload.query.filter_by(user_id=u.id)
            .order_by(UserDownload.downloaded_at.desc())
            .first()
        )
        last_job = (
            ProcessingJob.query.filter_by(triggered_by_user_id=u.id)
            .order_by(ProcessingJob.created_at.desc())
            .first()
        )
        last_activity = None
        if last_download and last_job:
            last_activity = max(
                last_download.downloaded_at, last_job.created_at
            ).isoformat()
        elif last_download:
            last_activity = last_download.downloaded_at.isoformat()
        elif last_job:
            last_activity = last_job.created_at.isoformat()

        # Recent downloads (last 10)
        recent_downloads = (
            UserDownload.query.filter_by(user_id=u.id)
            .order_by(UserDownload.downloaded_at.desc())
            .limit(10)
            .all()
        )

        # Feed subscriptions count
        from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
        subscriptions_count = UserFeedSubscription.query.filter_by(user_id=u.id).count()

        user_stats.append({
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at.isoformat(),
            "episodes_processed": episodes_processed,
            "ad_time_removed_seconds": round(ad_time_removed, 1),
            "ad_time_removed_formatted": _format_duration(ad_time_removed),
            "total_downloads": total_downloads,
            "processed_downloads": processed_downloads,
            "subscriptions_count": subscriptions_count,
            "last_activity": last_activity,
            "recent_downloads": [
                {
                    "post_id": d.post_id,
                    "post_title": d.post.title if d.post else "Unknown",
                    "downloaded_at": d.downloaded_at.isoformat(),
                    "is_processed": d.is_processed,
                }
                for d in recent_downloads
            ],
        })

    # Global stats
    total_feeds = Feed.query.count()
    total_episodes = Post.query.count()
    total_processed = Post.query.filter(Post.processed_audio_path.isnot(None)).count()

    return jsonify({
        "users": user_stats,
        "global_stats": {
            "total_feeds": total_feeds,
            "total_episodes": total_episodes,
            "total_processed": total_processed,
        },
    })


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s" if secs else f"{mins}m"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"
