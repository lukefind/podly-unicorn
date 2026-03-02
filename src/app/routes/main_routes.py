import logging
import os

import flask
import werkzeug.exceptions
from flask import Blueprint, current_app, g, send_from_directory

from app.extensions import db
from app.models import Feed, Post
from app.runtime_config import config

logger = logging.getLogger("global_logger")


main_bp = Blueprint("main", __name__)


def _require_legacy_endpoint_auth() -> flask.Response | None:
    """Legacy mutating routes are only allowed when session auth is enabled."""
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return flask.make_response(("Authentication required.", 401))

    if getattr(g, "current_user", None) is None:
        return flask.make_response(("Authentication required.", 401))

    return None


@main_bp.route("/")
def index() -> flask.Response:
    """Serve the React app's index.html."""
    static_folder = current_app.static_folder
    if static_folder and os.path.exists(os.path.join(static_folder, "index.html")):
        return send_from_directory(static_folder, "index.html")

    feeds = Feed.query.all()
    return flask.make_response(
        flask.render_template("index.html", feeds=feeds, config=config), 200
    )


@main_bp.route("/<path:path>")
def catch_all(path: str) -> flask.Response:
    """Serve React app for all frontend routes, or serve static files."""
    # Don't handle API routes - let them be handled by API blueprint
    if path.startswith("api/"):
        flask.abort(404)

    static_folder = current_app.static_folder
    if static_folder:
        # Try to serve a static file; send_from_directory validates path safety
        try:
            return send_from_directory(static_folder, path)
        except werkzeug.exceptions.NotFound:
            pass

        # If it's not a static file, serve the React SPA shell
        try:
            return send_from_directory(static_folder, "index.html")
        except werkzeug.exceptions.NotFound:
            pass

    # Fallback to 404
    flask.abort(404)


@main_bp.route("/feed/<int:f_id>/toggle-whitelist-all/<val>", methods=["POST"])
def whitelist_all(f_id: int, val: str) -> flask.Response:
    auth_error = _require_legacy_endpoint_auth()
    if auth_error is not None:
        return auth_error

    feed = Feed.query.get_or_404(f_id)
    for post in feed.posts:
        post.whitelisted = val.lower() == "true"
    db.session.commit()
    return flask.make_response("", 200)


@main_bp.route("/set_whitelist/<string:p_guid>/<val>", methods=["POST"])
def set_whitelist(p_guid: str, val: str) -> flask.Response:
    auth_error = _require_legacy_endpoint_auth()
    if auth_error is not None:
        return auth_error

    logger.info(f"Setting whitelist status for post with GUID: {p_guid} to {val}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    post.whitelisted = val.lower() == "true"
    db.session.commit()

    return index()
