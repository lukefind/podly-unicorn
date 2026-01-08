from __future__ import annotations

import logging
import re
from typing import Any

from flask import Response, current_app, g, jsonify, request, session

from app.auth.feed_tokens import FeedTokenAuthResult, authenticate_feed_token
from app.auth.service import AuthenticatedUser
from app.auth.state import failure_rate_limiter
from app.models import User

logger = logging.getLogger("global_logger")

SESSION_USER_KEY = "user_id"

# Paths that remain public even when auth is required.
# Frontend routes are public so the SPA shell loads; the frontend handles auth redirects.
_PUBLIC_PATHS: set[str] = {
    "/",
    "/health",
    "/robots.txt",
    "/manifest.json",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/signup",
    "/api/auth/password-reset/request",
    "/api/auth/password-reset/confirm",
    "/api/auth/status",
    # Frontend shell routes - serve SPA, let React handle auth
    "/settings",
    "/presets",
    "/podcasts",
    "/login",
    "/signup",
    "/forgot-password",
    "/reset-password",
}

_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/assets/",
    "/images/",
    "/fonts/",
    "/.well-known/",
)

_PUBLIC_EXTENSIONS: tuple[str, ...] = (
    ".js",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".txt",
)


_TOKEN_PROTECTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/feed/[^/]+$"),
    re.compile(r"^/api/posts/[^/]+/(audio|download(?:/original)?)$"),
    re.compile(r"^/post/[^/]+(?:\\.mp3|/original\\.mp3)$"),
    re.compile(r"^/trigger$"),  # Trigger page authenticates via feed token
    re.compile(r"^/api/trigger/status$"),  # Trigger status polling endpoint
)


def init_auth_middleware(app: Any) -> None:
    """Attach the authentication guard to the Flask app."""

    @app.before_request  # type: ignore[misc]
    def enforce_authentication() -> Response | None:
        # pylint: disable=too-many-return-statements
        if request.method == "OPTIONS":
            return None

        settings = current_app.config.get("AUTH_SETTINGS")
        if not settings or not settings.require_auth:
            return None

        if _is_public_request(request.path):
            return None

        client_identifier = request.remote_addr or "unknown"

        session_user = _load_session_user()
        if session_user is not None:
            g.current_user = session_user
            g.feed_token = None
            failure_rate_limiter.register_success(client_identifier)
            return None

        if _is_token_protected_endpoint(request.path):
            retry_after = failure_rate_limiter.retry_after(client_identifier)
            if retry_after:
                logger.info(
                    "TRIGGER_AUTH_RATELIMIT path=%s client=%s retry_after=%d",
                    request.path, client_identifier, retry_after
                )
                return _too_many_requests(retry_after)

            token_result = _authenticate_feed_token_from_query()
            if token_result is None:
                # Log auth failure with safe token prefix/suffix
                feed_token = request.args.get("feed_token") or ""
                token_prefix = feed_token[:6] if len(feed_token) >= 6 else feed_token
                token_suffix = feed_token[-4:] if len(feed_token) >= 4 else ""
                guid = request.args.get("guid") or ""
                logger.info(
                    "TRIGGER_AUTH_FAIL path=%s guid=%s token=%s...%s",
                    request.path, guid, token_prefix, token_suffix
                )
                backoff = failure_rate_limiter.register_failure(client_identifier)
                response = _token_unauthorized()
                if backoff:
                    response.headers["Retry-After"] = str(backoff)
                return response

            failure_rate_limiter.register_success(client_identifier)
            g.current_user = token_result.user
            g.feed_token = token_result
            return None

        return _json_unauthorized()


def _load_session_user() -> AuthenticatedUser | None:
    raw_user_id = session.get(SESSION_USER_KEY)
    if isinstance(raw_user_id, str) and raw_user_id.isdigit():
        user_id = int(raw_user_id)
    elif isinstance(raw_user_id, int):
        user_id = raw_user_id
    else:
        return None

    user = User.query.get(user_id)
    if user is None:
        session.pop(SESSION_USER_KEY, None)
        return None

    return AuthenticatedUser(id=user.id, username=user.username, role=user.role)


def _is_token_protected_endpoint(path: str) -> bool:
    return any(pattern.match(path) for pattern in _TOKEN_PROTECTED_PATTERNS)


def _authenticate_feed_token_from_query() -> FeedTokenAuthResult | None:
    token_id = request.args.get("feed_token")
    secret = request.args.get("feed_secret")
    if not token_id or not secret:
        return None

    return authenticate_feed_token(token_id, secret, request.path, req=request)


def _is_public_request(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True

    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return True

    if any(path.endswith(ext) for ext in _PUBLIC_EXTENSIONS):
        return True

    return False


def _json_unauthorized(message: str = "Authentication required.") -> Response:
    response = jsonify({"error": message})
    response.status_code = 401
    return response


def _token_unauthorized() -> Response:
    """Return JSON 401 for invalid/missing feed token (not HTML/text)."""
    response = jsonify({"state": "error", "message": "Invalid or missing feed token"})
    response.status_code = 401
    response.headers["Cache-Control"] = "no-store"
    return response


def _too_many_requests(retry_after: int) -> Response:
    """Return JSON 429 for rate limiting (not HTML/text)."""
    response = jsonify({"state": "error", "message": "Too many authentication attempts"})
    response.status_code = 429
    response.headers["Retry-After"] = str(retry_after)
    response.headers["Cache-Control"] = "no-store"
    return response
