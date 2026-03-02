from __future__ import annotations

import logging
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from flask import Request

from flask import current_app, has_app_context

from app.auth.service import AuthenticatedUser
from app.extensions import db
from app.models import Feed, FeedAccessToken, Post, User

logger = logging.getLogger("global_logger")


@dataclass(slots=True)
class FeedTokenAuthResult:
    user: AuthenticatedUser
    feed_id: Optional[int]  # None for combined feed tokens
    token: FeedAccessToken


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _derive_token_secret(token_id: str) -> str:
    """Derive a deterministic, URL-safe token secret from app secret + token_id."""
    if has_app_context():
        key_any = current_app.config.get("SECRET_KEY")
    else:
        key_any = os.environ.get("PODLY_SECRET_KEY")
    key = key_any if isinstance(key_any, str) and key_any else None
    if not key:
        raise RuntimeError("SECRET_KEY is required to derive feed token secrets.")

    digest = hmac.new(
        key.encode("utf-8"),
        token_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:36]


def _lookup_existing_token_secret(token: FeedAccessToken) -> Optional[str]:
    """Return reusable token secret when it can be determined, else None."""
    if token.token_secret:
        return token.token_secret

    derived_secret = _derive_token_secret(token.token_id)
    if secrets.compare_digest(token.token_hash, _hash_token(derived_secret)):
        return derived_secret
    return None


def create_feed_access_token(user: User, feed: Optional[Feed] = None) -> tuple[str, str]:
    """Create or retrieve a feed access token.
    
    Args:
        user: The user to create the token for
        feed: The specific feed, or None for combined feed access
    """
    feed_id = feed.id if feed else None
    
    existing_tokens = (
        FeedAccessToken.query.filter_by(user_id=user.id, feed_id=feed_id, revoked=False)
        .order_by(FeedAccessToken.created_at.desc(), FeedAccessToken.id.desc())
        .all()
    )
    for existing in existing_tokens:
        existing_secret = _lookup_existing_token_secret(existing)
        if existing_secret is not None:
            return existing.token_id, existing_secret

    token_id = uuid.uuid4().hex
    secret = _derive_token_secret(token_id)
    token = FeedAccessToken(
        token_id=token_id,
        token_hash=_hash_token(secret),
        feed_id=feed_id,
        user_id=user.id,
    )
    db.session.add(token)
    db.session.commit()

    return token_id, secret


@dataclass(slots=True)
class FeedTokenValue:
    id: str
    secret: str


def get_or_create_feed_token(user_id: int, feed_id: int) -> Optional[FeedTokenValue]:
    """Compatibility helper for legacy call sites that expect id/secret attributes."""
    user = User.query.get(user_id)
    feed = Feed.query.get(feed_id)
    if user is None or feed is None:
        return None

    token_id, secret = create_feed_access_token(user, feed)
    return FeedTokenValue(id=token_id, secret=secret)


def authenticate_feed_token(
    token_id: str, secret: str, path: str, *, req: Optional[Request] = None
) -> Optional[FeedTokenAuthResult]:
    if not token_id:
        return None

    token = FeedAccessToken.query.filter_by(token_id=token_id, revoked=False).first()
    if token is None:
        return None

    expected_hash = _hash_token(secret)
    if not secrets.compare_digest(token.token_hash, expected_hash):
        return None

    # Check if this is a combined feed token (feed_id is None)
    is_combined_feed_token = token.feed_id is None
    
    if is_combined_feed_token:
        # Combined feed tokens can access:
        # 1. The combined feed itself
        # 2. Any post from feeds the user is subscribed to
        if path.startswith("/feed/combined"):
            pass  # Allow access to combined feed
        elif path.startswith("/api/posts/") or path.startswith("/post/"):
            # Check if the post belongs to a feed the user is subscribed to
            from app.models import UserFeedSubscription  # pylint: disable=import-outside-toplevel
            post_feed_id = _resolve_feed_id(path, req=req)
            if post_feed_id is None:
                return None
            # Verify user is subscribed to this feed
            subscription = UserFeedSubscription.query.filter_by(
                user_id=token.user_id, feed_id=post_feed_id
            ).first()
            if subscription is None:
                return None
        else:
            return None
    else:
        # Regular feed token - verify feed_id matches exactly
        feed_id = _resolve_feed_id(path, req=req)
        if feed_id is None or feed_id != token.feed_id:
            return None

    user = User.query.get(token.user_id)
    if user is None:
        return None

    token.last_used_at = datetime.utcnow()
    db.session.add(token)
    try:
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to persist feed token last_used_at: %s", exc)
        db.session.rollback()

    return FeedTokenAuthResult(
        user=AuthenticatedUser(id=user.id, username=user.username, role=user.role),
        feed_id=token.feed_id,
        token=token,
    )


def _resolve_feed_id(path: str, *, req: Optional[Request] = None) -> Optional[int]:
    if path.startswith("/feed/"):
        remainder = path[len("/feed/") :]
        try:
            return int(remainder.split("/", 1)[0])
        except ValueError:
            return None

    if path.startswith("/api/posts/"):
        parts = path.split("/")
        if len(parts) < 4:
            return None
        guid = parts[3]
        post = Post.query.filter_by(guid=guid).first()
        return post.feed_id if post else None

    # Trigger endpoints are feed-scoped via guid query param
    if path == "/api/trigger/status" or path == "/trigger":
        if req is None:
            return None
        guid = req.args.get("guid")
        if not guid:
            return None
        post = Post.query.filter_by(guid=guid).first()
        return post.feed_id if post else None

    if path.startswith("/post/"):
        remainder = path[len("/post/") :]
        guid = remainder.split("/", 1)[0]
        guid = guid.split(".", 1)[0]
        post = Post.query.filter_by(guid=guid).first()
        return post.feed_id if post else None

    return None
