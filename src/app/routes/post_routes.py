import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from typing import Any, cast

import flask
from flask import Blueprint, Flask, current_app, g, jsonify, request, send_file
from flask.typing import ResponseReturnValue

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.models import Identification, ModelCall, Post, ProcessingJob, TranscriptSegment, UserDownload, UserFeedSubscription
from app.posts import clear_post_processing_data

logger = logging.getLogger("global_logger")


post_bp = Blueprint("post", __name__)


def _increment_download_count(post: Post) -> None:
    """Safely increment the download counter for a post."""
    try:
        updated = Post.query.filter_by(id=post.id).update(
            {Post.download_count: (Post.download_count or 0) + 1},
            synchronize_session=False,
        )
        if updated:
            post.download_count = (post.download_count or 0) + 1
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to increment download count for post %s: %s", post.guid, exc
        )
        db.session.rollback()


def _track_user_download(post: Post, is_processed: bool = True) -> None:
    """Track a successful download for the current user if authenticated."""
    try:
        current_user = getattr(g, "current_user", None)
        if not current_user:
            return  # No user to track
        feed_token = getattr(g, "feed_token", None)
        download_source = "rss" if feed_token is not None else "web"
        
        # Determine auth_type
        auth_type = "session"
        if feed_token is not None:
            auth_type = "combined" if feed_token.feed_id is None else "feed_scoped"
        
        # Get file size if available
        file_size = None
        audio_path = post.processed_audio_path if is_processed else post.unprocessed_audio_path
        if audio_path and Path(audio_path).exists():
            file_size = Path(audio_path).stat().st_size
        
        download = UserDownload(
            user_id=current_user.id,
            post_id=post.id,
            is_processed=is_processed,
            file_size_bytes=file_size,
            download_source=download_source,
            auth_type=auth_type,
            decision="SERVED_AUDIO",
        )
        db.session.add(download)
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to track download for user %s post %s: %s",
            getattr(getattr(g, "current_user", None), "id", "?"),
            post.guid,
            exc,
        )


def _record_download_attempt(
    post: Post, current_user: Any, auth_type: str, decision: str
) -> None:
    """Record a download attempt for audit trail (not necessarily a successful download).
    
    This is used to track:
    - Combined token attempts that didn't trigger processing
    - Triggered processing attempts
    - Job-exists responses
    """
    try:
        download = UserDownload(
            user_id=current_user.id if current_user else None,
            post_id=post.id,
            is_processed=False,
            file_size_bytes=None,
            download_source="rss",
            auth_type=auth_type,
            decision=decision,
        )
        db.session.add(download)
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to record download attempt for post %s: %s",
            post.guid,
            exc,
        )
        db.session.rollback()


@post_bp.route("/api/feeds/<int:feed_id>/posts", methods=["GET"])
def api_feed_posts(feed_id: int) -> flask.Response:
    """Returns a JSON list of posts for a specific feed."""
    from app.models import Feed  # local import to avoid circular in other modules

    # Verify feed exists
    feed = Feed.query.get_or_404(feed_id)
    
    # Use optimized direct query with only needed columns
    posts_query = Post.query.filter_by(feed_id=feed_id).order_by(Post.release_date.desc())
    
    posts = [
        {
            "id": post.id,
            "guid": post.guid,
            "title": post.title,
            "description": post.description,
            "release_date": (
                post.release_date.isoformat() if post.release_date else None
            ),
            "duration": post.duration,
            "whitelisted": post.whitelisted,
            "has_processed_audio": post.processed_audio_path is not None,
            "has_unprocessed_audio": post.unprocessed_audio_path is not None,
            "download_url": post.download_url,
            "image_url": post.image_url,
            "download_count": post.download_count,
        }
        for post in posts_query
    ]
    return flask.jsonify(posts)


@post_bp.route("/post/<string:p_guid>/json", methods=["GET"])
def get_post_json(p_guid: str) -> flask.Response:
    logger.info(f"API request for post details with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(jsonify({"error": "Post not found"}), 404)

    segment_count = post.segments.count()
    transcript_segments = []

    if segment_count > 0:
        sample_segments = post.segments.limit(5).all()
        for segment in sample_segments:
            transcript_segments.append(
                {
                    "id": segment.id,
                    "sequence_num": segment.sequence_num,
                    "start_time": segment.start_time,
                    "end_time": segment.end_time,
                    "text": (
                        segment.text[:100] + "..."
                        if len(segment.text) > 100
                        else segment.text
                    ),
                }
            )

    whisper_model_calls = []
    for model_call in post.model_calls.filter(
        ModelCall.model_name.like("%whisper%")
    ).all():
        whisper_model_calls.append(
            {
                "id": model_call.id,
                "model_name": model_call.model_name,
                "status": model_call.status,
                "first_segment": model_call.first_segment_sequence_num,
                "last_segment": model_call.last_segment_sequence_num,
                "timestamp": (
                    model_call.timestamp.isoformat() if model_call.timestamp else None
                ),
                "response": (
                    model_call.response[:100] + "..."
                    if model_call.response and len(model_call.response) > 100
                    else model_call.response
                ),
                "error": model_call.error_message,
            }
        )

    post_data = {
        "id": post.id,
        "guid": post.guid,
        "title": post.title,
        "feed_id": post.feed_id,
        "unprocessed_audio_path": post.unprocessed_audio_path,
        "processed_audio_path": post.processed_audio_path,
        "has_unprocessed_audio": post.unprocessed_audio_path is not None,
        "has_processed_audio": post.processed_audio_path is not None,
        "transcript_segment_count": segment_count,
        "transcript_sample": transcript_segments,
        "model_call_count": post.model_calls.count(),
        "whisper_model_calls": whisper_model_calls,
        "whitelisted": post.whitelisted,
        "download_count": post.download_count,
    }

    return flask.jsonify(post_data)


@post_bp.route("/post/<string:p_guid>/debug", methods=["GET"])
def post_debug(p_guid: str) -> flask.Response:
    """Debug view for a post, showing model calls, transcript segments, and identifications."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    model_calls = (
        ModelCall.query.filter_by(post_id=post.id)
        .order_by(ModelCall.model_name, ModelCall.first_segment_sequence_num)
        .all()
    )

    transcript_segments = post.segments.all()

    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )

    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    for call in model_calls:
        if call.status not in model_call_statuses:
            model_call_statuses[call.status] = 0
        model_call_statuses[call.status] += 1

        if call.model_name not in model_types:
            model_types[call.model_name] = 0
        model_types[call.model_name] += 1

    content_segments = sum(1 for i in identifications if i.label == "content")
    ad_segments = sum(1 for i in identifications if i.label == "ad")

    stats = {
        "total_segments": len(transcript_segments),
        "total_model_calls": len(model_calls),
        "total_identifications": len(identifications),
        "content_segments": content_segments,
        "ad_segments_count": ad_segments,
        "model_call_statuses": model_call_statuses,
        "model_types": model_types,
        "download_count": post.download_count,
    }

    return flask.make_response(
        flask.render_template(
            "post_debug.html",
            post=post,
            model_calls=model_calls,
            transcript_segments=transcript_segments,
            identifications=identifications,
            stats=stats,
        ),
        200,
    )


@post_bp.route("/api/posts/<string:p_guid>/stats", methods=["GET"])
def api_post_stats(p_guid: str) -> flask.Response:
    """Get processing statistics for a post in JSON format."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(flask.jsonify({"error": "Post not found"}), 404)

    model_calls = (
        ModelCall.query.filter_by(post_id=post.id)
        .order_by(ModelCall.model_name, ModelCall.first_segment_sequence_num)
        .all()
    )

    transcript_segments = post.segments.all()

    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )

    model_call_statuses: Dict[str, int] = {}
    model_types: Dict[str, int] = {}

    for call in model_calls:
        if call.status not in model_call_statuses:
            model_call_statuses[call.status] = 0
        model_call_statuses[call.status] += 1

        if call.model_name not in model_types:
            model_types[call.model_name] = 0
        model_types[call.model_name] += 1

    content_segments = sum(1 for i in identifications if i.label == "content")
    ad_segments = sum(1 for i in identifications if i.label == "ad")

    # Calculate estimated ad time by summing duration of ad-labeled segments
    ad_segment_ids = {i.transcript_segment_id for i in identifications if i.label == "ad"}
    estimated_ad_time_seconds = sum(
        (seg.end_time - seg.start_time)
        for seg in transcript_segments
        if seg.id in ad_segment_ids
    )

    model_call_details = []
    for call in model_calls:
        model_call_details.append(
            {
                "id": call.id,
                "model_name": call.model_name,
                "status": call.status,
                "segment_range": f"{call.first_segment_sequence_num}-{call.last_segment_sequence_num}",
                "first_segment_sequence_num": call.first_segment_sequence_num,
                "last_segment_sequence_num": call.last_segment_sequence_num,
                "timestamp": call.timestamp.isoformat() if call.timestamp else None,
                "retry_attempts": call.retry_attempts,
                "error_message": call.error_message,
                "prompt": call.prompt,
                "response": call.response,
            }
        )

    transcript_segments_data = []
    for segment in transcript_segments:
        segment_identifications = [
            i for i in identifications if i.transcript_segment_id == segment.id
        ]

        has_ad_label = any(i.label == "ad" for i in segment_identifications)
        primary_label = "ad" if has_ad_label else "content"

        transcript_segments_data.append(
            {
                "id": segment.id,
                "sequence_num": segment.sequence_num,
                "start_time": round(segment.start_time, 1),
                "end_time": round(segment.end_time, 1),
                "text": segment.text,
                "primary_label": primary_label,
                "identifications": [
                    {
                        "id": ident.id,
                        "label": ident.label,
                        "confidence": (
                            round(ident.confidence, 2) if ident.confidence else None
                        ),
                        "model_call_id": ident.model_call_id,
                    }
                    for ident in segment_identifications
                ],
            }
        )

    identifications_data = []
    for identification in identifications:
        segment = identification.transcript_segment
        identifications_data.append(
            {
                "id": identification.id,
                "transcript_segment_id": identification.transcript_segment_id,
                "label": identification.label,
                "confidence": (
                    round(identification.confidence, 2)
                    if identification.confidence
                    else None
                ),
                "model_call_id": identification.model_call_id,
                "segment_sequence_num": segment.sequence_num,
                "segment_start_time": round(segment.start_time, 1),
                "segment_end_time": round(segment.end_time, 1),
                "segment_text": segment.text,
            }
        )

    # Get preset info if available
    preset_info = None
    if post.processed_with_preset_id:
        from app.models import PromptPreset
        preset = PromptPreset.query.get(post.processed_with_preset_id)
        if preset:
            preset_info = {
                "id": preset.id,
                "name": preset.name,
                "aggressiveness": preset.aggressiveness,
                "min_confidence": preset.min_confidence,
            }

    # Get the most recent completed processing job for this post
    from app.models import ProcessingJob, User
    last_job = (
        ProcessingJob.query.filter_by(post_guid=post.guid, status="completed")
        .order_by(ProcessingJob.completed_at.desc())
        .first()
    )
    job_info = None
    if last_job:
        triggered_by_user = User.query.get(last_job.triggered_by_user_id) if last_job.triggered_by_user_id else None
        job_info = {
            "job_id": last_job.id,
            "trigger_source": last_job.trigger_source,
            "triggered_by_user_id": last_job.triggered_by_user_id,
            "triggered_by_username": triggered_by_user.username if triggered_by_user else None,
            "started_at": last_job.started_at.isoformat() if last_job.started_at else None,
            "completed_at": last_job.completed_at.isoformat() if last_job.completed_at else None,
        }

    stats_data = {
        "post": {
            "guid": post.guid,
            "title": post.title,
            "duration": post.duration,
            "release_date": (
                post.release_date.isoformat() if post.release_date else None
            ),
            "whitelisted": post.whitelisted,
            "has_processed_audio": post.processed_audio_path is not None,
            "download_count": post.download_count,
            "processed_with_preset": preset_info,
        },
        "processing_stats": {
            "total_segments": len(transcript_segments),
            "total_model_calls": len(model_calls),
            "total_identifications": len(identifications),
            "content_segments": content_segments,
            "ad_segments_count": ad_segments,
            "estimated_ad_time_seconds": round(estimated_ad_time_seconds, 1),
            "model_call_statuses": model_call_statuses,
            "model_types": model_types,
        },
        "model_calls": model_call_details,
        "transcript_segments": transcript_segments_data,
        "identifications": identifications_data,
        "job_info": job_info,
    }

    return flask.jsonify(stats_data)


@post_bp.route("/api/posts/<string:p_guid>/whitelist", methods=["POST"])
def api_toggle_whitelist(p_guid: str) -> flask.Response:
    """Toggle whitelist status for a post via API."""
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(flask.jsonify({"error": "Post not found"}), 404)

    data = request.get_json()
    if data is None or "whitelisted" not in data:
        return flask.make_response(
            flask.jsonify({"error": "Missing whitelisted field"}), 400
        )

    post.whitelisted = bool(data["whitelisted"])
    db.session.commit()

    return flask.jsonify(
        {
            "guid": post.guid,
            "whitelisted": post.whitelisted,
            "message": "Whitelist status updated successfully",
        }
    )


@post_bp.route("/api/feeds/<int:feed_id>/toggle-whitelist-all", methods=["POST"])
def api_toggle_whitelist_all(feed_id: int) -> flask.Response:
    """Intelligently toggle whitelist status for all posts in a feed."""
    from app.models import Feed  # local import to avoid circular in other modules

    feed = Feed.query.get_or_404(feed_id)

    if not feed.posts:
        return flask.jsonify(
            {
                "message": "No posts found in this feed",
                "whitelisted_count": 0,
                "total_count": 0,
            }
        )

    all_whitelisted = all(post.whitelisted for post in feed.posts)
    new_status = not all_whitelisted

    for post in feed.posts:
        post.whitelisted = new_status

    db.session.commit()

    whitelisted_count = sum(1 for post in feed.posts if post.whitelisted)

    return flask.jsonify(
        {
            "message": f"{'Whitelisted' if new_status else 'Unwhitelisted'} all posts",
            "whitelisted_count": whitelisted_count,
            "total_count": len(feed.posts),
            "all_whitelisted": new_status,
        }
    )


@post_bp.route("/api/posts/<string:p_guid>/process", methods=["POST"])
def api_process_post(p_guid: str) -> ResponseReturnValue:
    """Start processing a post and return immediately."""
    post = Post.query.filter_by(guid=p_guid).first()
    if not post:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }
            ),
            404,
        )

    if not post.whitelisted:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                }
            ),
            400,
        )

    if post.processed_audio_path and os.path.exists(post.processed_audio_path):
        return flask.jsonify(
            {
                "status": "completed",
                "message": "Post already processed",
                "download_url": f"/api/posts/{p_guid}/download",
            }
        )

    try:
        # Get current user ID if authenticated
        current_user = getattr(g, "current_user", None)
        user_id = current_user.id if current_user else None
        
        result = get_jobs_manager().start_post_processing(
            p_guid, priority="interactive", triggered_by_user_id=user_id,
            trigger_source="manual_ui"
        )
        status_code = 200 if result.get("status") in ("started", "completed") else 400
        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to start processing job for {p_guid}: {e}")
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "JOB_START_FAILED",
                    "message": f"Failed to start processing job: {str(e)}",
                }
            ),
            500,
        )


@post_bp.route("/api/posts/<string:p_guid>/reprocess", methods=["POST"])
def api_reprocess_post(p_guid: str) -> ResponseReturnValue:
    """Clear all processing data for a post and start processing from scratch."""
    post = Post.query.filter_by(guid=p_guid).first()
    if not post:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_FOUND",
                    "message": "Post not found",
                }
            ),
            404,
        )

    if not post.whitelisted:
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "NOT_WHITELISTED",
                    "message": "Post not whitelisted",
                }
            ),
            400,
        )

    try:
        # Get current user ID if authenticated
        current_user = getattr(g, "current_user", None)
        user_id = current_user.id if current_user else None
        
        get_jobs_manager().cancel_post_jobs(p_guid)
        clear_post_processing_data(post)
        result = get_jobs_manager().start_post_processing(
            p_guid, priority="interactive", triggered_by_user_id=user_id,
            trigger_source="manual_reprocess"
        )
        status_code = 200 if result.get("status") in ("started", "completed") else 400
        if result.get("status") == "started":
            result["message"] = "Post cleared and reprocessing started"
        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to reprocess post {p_guid}: {e}", exc_info=True)
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "REPROCESS_FAILED",
                    "message": f"Failed to reprocess post: {str(e)}",
                }
            ),
            500,
        )


@post_bp.route("/api/posts/<string:p_guid>/status", methods=["GET"])
def api_post_status(p_guid: str) -> ResponseReturnValue:
    """Get the current processing status of a post via JobsManager."""
    result = get_jobs_manager().get_post_status(p_guid)
    status_code = (
        200
        if result.get("status") != "error"
        else (404 if result.get("error_code") == "NOT_FOUND" else 400)
    )
    return flask.jsonify(result), status_code


@post_bp.route("/api/posts/<string:p_guid>/audio", methods=["GET"])
def api_get_post_audio(p_guid: str) -> ResponseReturnValue:
    """API endpoint to serve processed audio files with proper CORS headers."""
    logger.info(f"API request for audio file with GUID: {p_guid}")

    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(
            jsonify({"error": "Post not found", "error_code": "NOT_FOUND"}), 404
        )

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(
            jsonify({"error": "Post not whitelisted", "error_code": "NOT_WHITELISTED"}),
            403,
        )

    if not post.processed_audio_path or not Path(post.processed_audio_path).exists():
        logger.warning(f"Processed audio not found for post: {post.id}")
        return flask.make_response(
            jsonify(
                {
                    "error": "Processed audio not available",
                    "error_code": "AUDIO_NOT_READY",
                    "message": "Post needs to be processed first",
                }
            ),
            404,
        )

    try:
        response = send_file(
            path_or_file=Path(post.processed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=False,
        )
        response.headers["Accept-Ranges"] = "bytes"
        return response
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving audio file for {p_guid}: {e}")
        return flask.make_response(
            jsonify(
                {"error": "Error serving audio file", "error_code": "SERVER_ERROR"}
            ),
            500,
        )


# Cooldown duration for on-demand processing triggers (DB-backed via ProcessingJob.created_at)
_ON_DEMAND_COOLDOWN_SECONDS = 600  # 10 minutes between triggers for same GUID

# Probe detection: Range requests with end < this value are treated as probes and won't trigger processing
# Podcast apps often probe with bytes=0-0, bytes=0-1023, etc. before real downloads
_PROBE_MAX_BYTES = 1048576  # 1 MB


def _is_probe_request(range_header: str | None) -> bool:
    """Determine if a Range request is a probe (small prefetch) vs real download.
    
    Probes are:
    - bytes=0-0
    - bytes=0-1023
    - bytes=0-<end> where end < _PROBE_MAX_BYTES (1MB)
    
    Real downloads are:
    - No Range header
    - bytes=<start>-<end> where start > 0
    - bytes=0-<end> where end >= _PROBE_MAX_BYTES
    - bytes=0- (open-ended)
    """
    if not range_header:
        return False  # No Range = real download attempt
    
    # Parse Range header: "bytes=0-1023" or "bytes=0-" or "bytes=1024-2047"
    if not range_header.startswith("bytes="):
        return False
    
    range_spec = range_header[6:]  # Remove "bytes="
    
    # Handle multiple ranges (rare, treat as real download)
    if "," in range_spec:
        return False
    
    parts = range_spec.split("-")
    if len(parts) != 2:
        return False
    
    start_str, end_str = parts
    
    try:
        start = int(start_str) if start_str else 0
    except ValueError:
        return False
    
    # If start > 0, this is seeking into the file = real download
    if start > 0:
        return False
    
    # If end is empty (open-ended range like "bytes=0-"), it's a real download
    if not end_str:
        return False
    
    try:
        end = int(end_str)
    except ValueError:
        return False
    
    # If end < _PROBE_MAX_BYTES, it's a probe
    return end < _PROBE_MAX_BYTES


@post_bp.route("/api/posts/<string:p_guid>/download", methods=["GET", "HEAD"])
def api_download_post(p_guid: str) -> flask.Response:
    """API endpoint to download processed audio files.
    
    On-demand processing flow for podcast apps (Overcast, Pocket Casts, Apple Podcasts):
    
    1. HEAD requests: Never trigger processing, return 204 No Content
    2. Small Range requests (bytes=0-<1MB>): Probe, never trigger, return 204
    3. GET requests for unprocessed episodes:
       - If job already pending/running: Return 503 with Retry-After
       - If within cooldown window: Return 503 with Retry-After (no new job)
       - Otherwise: Start job, return 503 with Retry-After
    4. GET requests for processed episodes: Return audio file
    
    Key design decisions:
    - HEAD = probe, never triggers (return 204)
    - Small Range (bytes=0-<1MB>) = probe, never triggers (return 204)
    - Full GET or large Range CAN trigger processing
    - Cooldown prevents trigger storms from aggressive clients
    - 503 Service Unavailable for "not ready" (NOT 202, which confuses podcast apps)
    - Authorization via feed token in URL (podcast apps don't send cookies)
    """
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Download request for non-existent post: {p_guid}")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Download request for non-whitelisted post: {post.title}")
        return flask.make_response(("Post not whitelisted", 403))

    # Gather request metadata for logging and decisions
    current_user = getattr(g, "current_user", None)
    feed_token = getattr(g, "feed_token", None)  # FeedTokenAuthResult or None
    range_header = flask.request.headers.get("Range")
    user_agent = flask.request.headers.get("User-Agent", "")
    request_method = flask.request.method
    
    # Detect if this is a probe request
    is_probe = request_method == "HEAD" or _is_probe_request(range_header)
    
    # --- DETERMINE AUTH TYPE ---
    # Auth types:
    # - "session": User logged in via web session (can trigger processing if subscribed)
    # - "feed_scoped": Feed token with specific feed_id matching post.feed_id (can trigger)
    # - "combined": Combined feed token (feed_id=None) - READ ONLY, cannot trigger processing
    # - "none": No valid auth
    auth_type = "none"
    is_authorized_to_read = False
    can_trigger_processing = False
    
    if feed_token is not None:
        # Authenticated via feed token
        if feed_token.feed_id is None:
            # Combined feed token - read access only, NO processing trigger
            auth_type = "combined"
            is_authorized_to_read = True
            can_trigger_processing = False
        elif feed_token.feed_id == post.feed_id:
            # Feed-scoped token matching this post's feed - full access
            auth_type = "feed_scoped"
            is_authorized_to_read = True
            can_trigger_processing = True
        else:
            # Feed-scoped token for different feed - no access
            auth_type = "feed_scoped_mismatch"
            is_authorized_to_read = False
            can_trigger_processing = False
    elif current_user and post.feed_id:
        # Session auth - check subscription
        subscription = UserFeedSubscription.query.filter_by(
            user_id=current_user.id,
            feed_id=post.feed_id,
        ).first()
        if subscription:
            auth_type = "session"
            is_authorized_to_read = True
            can_trigger_processing = True
    
    # Check if episode is already processed and available
    is_processed = post.processed_audio_path and Path(post.processed_audio_path).exists()
    
    # Helper to log decision with consistent format
    def _log_decision(decision: str, status: int, extra: str = "") -> None:
        logger.info(
            "DOWNLOAD_DECISION post=%s method=%s range=%s ua=%s auth=%s decision=%s status=%d%s",
            post.guid[:16],
            request_method,
            range_header or "none",
            user_agent[:40] if user_agent else "none",
            auth_type,
            decision,
            status,
            f" {extra}" if extra else "",
        )
    
    if is_processed:
        # Episode is ready - serve it (read access is sufficient)
        if not is_authorized_to_read:
            _log_decision("NOT_AUTHORIZED_READ", 401)
            return flask.make_response(("Authentication required", 401))
        # Fall through to file serving below
        _log_decision("SERVED_AUDIO", 200)
    else:
        # Episode not yet processed - determine response
        
        # --- TIER 1: Probes (HEAD or small Range) = never trigger ---
        if is_probe:
            _log_decision("PROBE", 204)
            # 204 No Content - tells client "nothing here yet" without implying retry
            return flask.make_response(("", 204))
        
        # --- AUTHORIZATION CHECK FOR READ ---
        if not is_authorized_to_read:
            _log_decision("NOT_AUTHORIZED", 401)
            return flask.make_response(("Authentication required", 401))
        
        # --- COMBINED TOKEN: READ-ONLY, NO PROCESSING TRIGGER ---
        # Combined feed tokens can read processed audio but CANNOT trigger processing
        # This prevents the unified feed from causing expensive processing jobs
        if not can_trigger_processing:
            _log_decision("NO_TRIGGER_COMBINED", 503)
            # Record the attempt for audit trail
            _record_download_attempt(
                post, current_user, auth_type, "NOT_READY_NO_TRIGGER"
            )
            # Return 503 Service Unavailable (NOT 202 which confuses podcast apps)
            # The episode must be processed via per-feed access or manual UI
            response = flask.make_response(("Episode not yet processed", 503))
            response.headers["Retry-After"] = "300"  # 5 minutes
            return response
        
        # --- CHECK FOR EXISTING JOB ---
        existing_job = ProcessingJob.query.filter(
            ProcessingJob.post_guid == post.guid,
            ProcessingJob.status.in_(["pending", "running"])
        ).first()
        
        if existing_job:
            _log_decision("JOB_EXISTS", 503, f"job_id={existing_job.id}")
            response = flask.make_response(("Processing in progress", 503))
            response.headers["Retry-After"] = "120"
            return response
        
        # --- COOLDOWN CHECK (DB-backed via ProcessingJob.created_at) ---
        last_job = ProcessingJob.query.filter(
            ProcessingJob.post_guid == post.guid
        ).order_by(ProcessingJob.created_at.desc()).first()
        
        if last_job and last_job.created_at:
            job_age_seconds = (datetime.now(timezone.utc) - last_job.created_at.replace(tzinfo=timezone.utc)).total_seconds()
            cooldown_remaining = _ON_DEMAND_COOLDOWN_SECONDS - job_age_seconds
            
            if cooldown_remaining > 0:
                # Within cooldown window - don't trigger again
                _log_decision("COOLDOWN", 503, f"remaining={int(cooldown_remaining)}s")
                response = flask.make_response(("Processing recently requested", 503))
                response.headers["Retry-After"] = str(min(int(cooldown_remaining) + 10, 300))
                return response
        
        # --- TRIGGER PROCESSING ---
        # This is a full GET from an authorized user (feed-scoped or session),
        # no existing job, cooldown expired
        _log_decision("TRIGGER", 503)
        
        # Record the trigger attempt for audit trail
        _record_download_attempt(post, current_user, auth_type, "TRIGGERED")
        
        try:
            app = cast(Any, current_app)._get_current_object()
            post_guid = post.guid
            user_id = current_user.id if current_user else None
            Thread(
                target=_start_post_processing_async,
                args=(app, post_guid, user_id),
                daemon=True,
                name=f"on-demand-process-{post_guid[:8]}",
            ).start()
            
            response = flask.make_response(("Processing started", 503))
            response.headers["Retry-After"] = "120"
            return response
        except Exception as e:
            logger.error(f"Failed to trigger on-demand processing for {p_guid}: {e}")
            response = flask.make_response(("Processing temporarily unavailable", 503))
            response.headers["Retry-After"] = "60"
            return response

    try:
        response = send_file(
            path_or_file=Path(post.processed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{post.title}.mp3",
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving file for {p_guid}: {e}")
        return flask.make_response(("Error serving file", 500))

    _increment_download_count(post)
    _track_user_download(post, is_processed=True)
    return response


@post_bp.route("/api/posts/<string:p_guid>/download/original", methods=["GET"])
def api_download_original_post(p_guid: str) -> flask.Response:
    """API endpoint to download original (unprocessed) audio files."""
    logger.info(f"Request to download original post with GUID: {p_guid}")
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Post with GUID: {p_guid} not found")
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Post: {post.title} is not whitelisted")
        return flask.make_response(("Post not whitelisted", 403))

    if (
        not post.unprocessed_audio_path
        or not Path(post.unprocessed_audio_path).exists()
    ):
        logger.warning(f"Original audio not found for post: {post.id}")
        return flask.make_response(("Original audio not found", 404))

    try:
        response = send_file(
            path_or_file=Path(post.unprocessed_audio_path).resolve(),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{post.title}_original.mp3",
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Error serving original file for {p_guid}: {e}")
        return flask.make_response(("Error serving file", 500))

    _increment_download_count(post)
    _track_user_download(post, is_processed=False)
    return response


def _start_post_processing_async(app: Flask, post_guid: str, user_id: int = None) -> None:
    """Start post processing in a background thread with proper app context."""
    with app.app_context():
        try:
            result = get_jobs_manager().start_post_processing(
                post_guid,
                priority="interactive",
                triggered_by_user_id=user_id,
                trigger_source="on_demand_rss",
            )
            logger.info(f"On-demand processing started for {post_guid}: {result}")
        except Exception as exc:  # pylint: disable=broad-except
            logger.error(f"Failed to start on-demand processing for {post_guid}: {exc}")


# Legacy endpoints for backward compatibility
@post_bp.route("/post/<string:p_guid>.mp3", methods=["GET"])
def download_post_legacy(p_guid: str) -> flask.Response:
    return api_download_post(p_guid)


@post_bp.route("/post/<string:p_guid>/original.mp3", methods=["GET"])
def download_original_post_legacy(p_guid: str) -> flask.Response:
    return api_download_original_post(p_guid)
