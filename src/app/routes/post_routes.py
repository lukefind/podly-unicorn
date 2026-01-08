import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import flask
from flask import Blueprint, current_app, g, jsonify, request, send_file
from flask.typing import ResponseReturnValue

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.models import Feed, Identification, ModelCall, Post, ProcessingJob, TranscriptSegment, UserDownload, UserFeedSubscription
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
    """Track a successful audio download for the current user if authenticated."""
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
            event_type="AUDIO_DOWNLOAD",
            auth_type=auth_type,
            decision="SERVED_AUDIO",  # Legacy field for backwards compat
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


def _record_user_event(
    post: Post,
    current_user: Any,
    event_type: str,
    auth_type: str = "session",
    decision: str = "",
    download_source: str = "web",
) -> None:
    """Record a user activity event for audit trail.
    
    Event types:
    - AUDIO_DOWNLOAD: Actual media file served
    - TRIGGER_OPEN: User opened /trigger page
    - PROCESS_STARTED: Processing job queued
    - PROCESS_COMPLETE: Processing finished successfully
    - FAILED: Any error (auth, processing, expired token, etc.)
    """
    try:
        download = UserDownload(
            user_id=current_user.id if current_user else None,
            post_id=post.id,
            is_processed=False,
            file_size_bytes=None,
            download_source=download_source,
            event_type=event_type,
            auth_type=auth_type,
            decision=decision,  # Legacy field for backwards compat
        )
        db.session.add(download)
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(
            "Failed to record event %s for post %s: %s",
            event_type,
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
    # DEBUG: Force print to stderr to verify route is hit (bypasses logging config)
    range_hdr = flask.request.headers.get('Range')
    ua_hdr = flask.request.headers.get('User-Agent', '')
    print(f"[DOWNLOAD_HIT] guid={p_guid} method={flask.request.method} range={range_hdr} ua={ua_hdr[:50]}", file=sys.stderr, flush=True)
    
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        logger.warning(f"Download request for non-existent post: {p_guid}")
        print(f"[DOWNLOAD_RETURN] guid={p_guid} status=404 reason=post_not_found", file=sys.stderr, flush=True)
        return flask.make_response(("Post not found", 404))

    if not post.whitelisted:
        logger.warning(f"Download request for non-whitelisted post: {post.title}")
        print(f"[DOWNLOAD_RETURN] guid={p_guid} status=403 reason=not_whitelisted", file=sys.stderr, flush=True)
        return flask.make_response(("Post not whitelisted", 403))

    # Gather request metadata for logging and decisions
    current_user = getattr(g, "current_user", None)
    feed_token = getattr(g, "feed_token", None)  # FeedTokenAuthResult or None
    range_header = flask.request.headers.get("Range")
    user_agent = flask.request.headers.get("User-Agent", "")
    request_method = flask.request.method
    
    # Detect if this is a probe request
    is_probe = request_method == "HEAD" or _is_probe_request(range_header)
    print(f"[DOWNLOAD_CLASSIFY] guid={post.guid} is_probe={is_probe} method={request_method} range={range_header}", file=sys.stderr, flush=True)
    
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
    
    # Log auth classification
    token_feed_id = feed_token.feed_id if feed_token else None
    user_id_for_log = current_user.id if current_user else None
    print(f"[DOWNLOAD_AUTH] guid={post.guid} auth={auth_type} token_feed_id={token_feed_id} post_feed_id={post.feed_id} user_id={user_id_for_log} can_trigger={can_trigger_processing}", file=sys.stderr, flush=True)
    
    # Check if episode is already processed and available
    is_processed = post.processed_audio_path and Path(post.processed_audio_path).exists()
    
    # DEBUG: Log the processed state
    print(f"[POST_STATE] guid={post.guid[:16]} processed_audio_path={post.processed_audio_path or 'None'} is_processed={is_processed} auth={auth_type} can_trigger={can_trigger_processing}", file=sys.stderr, flush=True)
    
    # Helper to log decision with consistent format
    def _log_decision(decision: str, status: int, extra: str = "") -> None:
        msg = f"DOWNLOAD_DECISION post={post.guid[:16]} method={request_method} range={range_header or 'none'} ua={user_agent[:40] if user_agent else 'none'} auth={auth_type} decision={decision} status={status}{f' {extra}' if extra else ''}"
        logger.info(msg)
        # Also print to stderr to ensure visibility in docker logs
        print(f"[DECISION] {msg}", file=sys.stderr, flush=True)
    
    if is_processed:
        # Episode is ready - serve it (read access is sufficient)
        if not is_authorized_to_read:
            _log_decision("NOT_AUTHORIZED_READ", 401)
            print(f"[DOWNLOAD_RETURN] guid={post.guid} status=401 reason=not_authorized_read", file=sys.stderr, flush=True)
            return flask.make_response(("Authentication required", 401))
        # Fall through to file serving below
        _log_decision("SERVED_AUDIO", 200)
        print(f"[DOWNLOAD_RETURN] guid={post.guid} status=200 reason=served_audio", file=sys.stderr, flush=True)
    else:
        # Episode not yet processed - determine response
        
        # --- TIER 1: Probes (HEAD or small Range) = never trigger ---
        if is_probe:
            _log_decision("PROBE", 204)
            print(f"[DOWNLOAD_RETURN] guid={post.guid} status=204 reason=probe", file=sys.stderr, flush=True)
            # 204 No Content - tells client "nothing here yet" without implying retry
            return flask.make_response(("", 204))
        
        # --- AUTHORIZATION CHECK FOR READ ---
        if not is_authorized_to_read:
            _log_decision("NOT_AUTHORIZED", 401)
            print(f"[DOWNLOAD_RETURN] guid={post.guid} status=401 reason=not_authorized", file=sys.stderr, flush=True)
            return flask.make_response(("Authentication required", 401))
        
        # --- COMBINED TOKEN: READ-ONLY, NO PROCESSING TRIGGER ---
        # Combined feed tokens can read processed audio but CANNOT trigger processing
        # This prevents the unified feed from causing expensive processing jobs
        if not can_trigger_processing:
            _log_decision("NO_TRIGGER_COMBINED", 503)
            # Record the attempt for audit trail
            _record_user_event(
                post, current_user, "FAILED", auth_type, "NOT_READY_NO_TRIGGER", "rss"
            )
            # Return 503 Service Unavailable (NOT 202 which confuses podcast apps)
            # The episode must be processed via per-feed access or manual UI
            print(f"[DOWNLOAD_RETURN] guid={post.guid} status=503 reason=no_trigger_combined", file=sys.stderr, flush=True)
            response = flask.make_response(("Episode not yet processed", 503))
            response.headers["Retry-After"] = "300"  # 5 minutes
            return response
        
        # --- DOWNLOAD ENDPOINT DOES NOT CREATE JOBS ---
        # Per design: only /trigger can create jobs. Download endpoint is non-mutating.
        # This prevents processing storms from podcast app probes/prefetches.
        
        # Check if there's an existing job in progress
        existing_job = ProcessingJob.query.filter(
            ProcessingJob.post_guid == post.guid,
            ProcessingJob.status.in_(["pending", "running"])
        ).first()
        
        if existing_job:
            _log_decision("JOB_EXISTS", 503, f"job_id={existing_job.id}")
            print(f"[DOWNLOAD_RETURN] guid={post.guid} status=503 reason=job_exists job_id={existing_job.id}", file=sys.stderr, flush=True)
            response = flask.make_response(("Processing in progress", 503))
            response.headers["Retry-After"] = "120"
            return response
        
        # Episode not processed, no job in progress
        # Return 503 with hint to use trigger link
        _log_decision("NOT_PROCESSED", 503)
        print(f"[DOWNLOAD_RETURN] guid={post.guid} status=503 reason=not_processed", file=sys.stderr, flush=True)
        response = flask.make_response(("Episode not yet processed. Click the episode link in your podcast app to start processing.", 503))
        response.headers["Retry-After"] = "300"
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


# Legacy endpoints for backward compatibility
@post_bp.route("/post/<string:p_guid>.mp3", methods=["GET"])
def download_post_legacy(p_guid: str) -> flask.Response:
    return api_download_post(p_guid)


@post_bp.route("/post/<string:p_guid>/original.mp3", methods=["GET"])
def download_original_post_legacy(p_guid: str) -> flask.Response:
    return api_download_original_post(p_guid)


# =============================================================================
# TRIGGER ENDPOINTS - User-initiated processing via capability URLs
# =============================================================================

@post_bp.route("/api/posts/<string:guid>/trigger_link", methods=["GET"])
def get_trigger_link(guid: str) -> flask.Response:
    """Get the public trigger URL for an episode.
    
    Requires logged-in session auth. Returns a feed-scoped trigger URL
    that can be used without login to trigger processing.
    
    Returns JSON: { "trigger_url": "https://..." }
    """
    from app.auth.feed_tokens import get_or_create_feed_token
    from app.feeds import _get_base_url
    
    # Require session auth
    current_user = getattr(g, "current_user", None)
    if not current_user:
        return jsonify({"error": "Authentication required"}), 401
    
    # Look up the post
    post = Post.query.filter_by(guid=guid).first()
    if not post:
        return jsonify({"error": "Episode not found"}), 404
    
    # Get the feed for this post
    feed = Feed.query.get(post.feed_id)
    if not feed:
        return jsonify({"error": "Feed not found"}), 404
    
    # Get or create a feed-scoped token for this user
    token = get_or_create_feed_token(current_user.id, feed.id)
    if not token:
        return jsonify({"error": "Failed to create token"}), 500
    
    # Build the public trigger URL
    base_url = _get_base_url()
    # Force HTTPS for non-localhost
    if not base_url.startswith("http://localhost") and not base_url.startswith("http://127.0.0.1"):
        base_url = base_url.replace("http://", "https://")
    
    trigger_url = f"{base_url}/trigger?guid={post.guid}&feed_token={token.id}&feed_secret={token.secret}"
    
    return jsonify({
        "trigger_url": trigger_url,
        "guid": post.guid,
        "feed_id": feed.id,
        "feed_title": feed.title,
    })


@post_bp.route("/trigger", methods=["GET"])
def trigger_processing() -> flask.Response:
    """Trigger processing for an episode via a capability URL.
    
    This endpoint is linked from RSS <item><link> elements. When a user clicks
    the link in their podcast app, it queues the episode for processing.
    
    Required query params:
    - guid: The episode GUID
    - feed_token: The feed-scoped token ID
    - feed_secret: The feed-scoped token secret
    
    Combined tokens (feed_id=NULL) are NOT allowed to trigger processing.
    Only feed-scoped tokens can trigger.
    
    Error handling:
    - 400: Missing parameters
    - 401/403: Invalid token or unauthorized
    - 404: Episode not found
    - 409: Episode not eligible (disabled)
    - Never returns 500 - all exceptions are caught
    """
    try:
        return _handle_trigger_processing()
    except Exception as e:
        # Catch-all for any unexpected exceptions
        logger.error(f"Unexpected error in trigger_processing: {e}", exc_info=True)
        print(f"[TRIGGER_ERROR] unexpected_exception: {e}", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Something Went Wrong",
            message="An unexpected error occurred. Please try again later.",
            status_code=500
        )


def _handle_trigger_processing() -> flask.Response:
    """Internal handler for trigger processing - separated for cleaner error handling."""
    from app.auth.feed_tokens import authenticate_feed_token
    
    guid = flask.request.args.get("guid")
    token_id = flask.request.args.get("feed_token")
    secret = flask.request.args.get("feed_secret")
    
    # Safe logging - never log secrets
    token_prefix = token_id[:6] if token_id and len(token_id) >= 6 else token_id
    token_suffix = token_id[-4:] if token_id and len(token_id) >= 4 else ""
    print(f"[TRIGGER_HIT] guid={guid} token={token_prefix}...{token_suffix}", file=sys.stderr, flush=True)
    
    # Validate required parameters
    if not guid or not token_id or not secret:
        print(f"[TRIGGER_RETURN] status=400 reason=missing_params", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Missing Parameters",
            message="Required parameters: guid, feed_token, feed_secret",
            status_code=400
        )
    
    # Authenticate the token
    try:
        auth_result = authenticate_feed_token(token_id, secret, f"/api/posts/{guid}/download")
    except Exception as e:
        logger.error(f"Token authentication failed for guid={guid}: {e}", exc_info=True)
        print(f"[TRIGGER_RETURN] status=401 reason=auth_exception error={e}", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Authentication Error",
            message="Failed to verify your access token. Please try getting a fresh link.",
            status_code=401
        )
    
    if not auth_result:
        print(f"[TRIGGER_RETURN] status=403 reason=invalid_token", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Invalid Token",
            message="The link has expired or is invalid. Please get a fresh link from your podcast app.",
            status_code=403
        )
    
    print(f"[TRIGGER_AUTH] guid={guid} feed_id={auth_result.feed_id} user_id={auth_result.user.id}", file=sys.stderr, flush=True)
    
    # Combined tokens (feed_id=None) cannot trigger processing
    if auth_result.feed_id is None:
        print(f"[TRIGGER_RETURN] status=403 reason=combined_token_no_trigger", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Cannot Trigger from Combined Feed",
            message="Combined feed tokens cannot trigger processing. Please use the per-show feed URL instead.",
            status_code=403
        )
    
    # Look up the post
    post = Post.query.filter_by(guid=guid).first()
    if not post:
        print(f"[TRIGGER_RETURN] status=404 reason=post_not_found", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Episode Not Found",
            message="This episode could not be found. It may have been removed.",
            status_code=404
        )
    
    # Verify the token's feed_id matches the post's feed_id
    if post.feed_id != auth_result.feed_id:
        print(f"[TRIGGER_RETURN] status=403 reason=feed_mismatch token_feed={auth_result.feed_id} post_feed={post.feed_id}", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Access Denied",
            message="This token is not authorized for this episode.",
            status_code=403
        )
    
    # Check if episode is eligible (whitelisted)
    if not post.whitelisted:
        print(f"[TRIGGER_RETURN] status=409 reason=not_whitelisted", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Episode Not Enabled",
            message="This episode is not enabled for processing. Enable it in the Podly web interface first.",
            status_code=409
        )
    
    # Get feed info for display
    feed = Feed.query.get(post.feed_id)
    feed_title = feed.title if feed else "Unknown Show"
    
    # Build download URL for when ready
    download_url = f"/api/posts/{post.guid}/download?feed_token={token_id}&feed_secret={secret}"
    
    # Record trigger page open event
    _record_user_event(post, auth_result.user, "TRIGGER_OPEN", "feed_scoped", "", "trigger")
    
    # Check if already processed
    if post.processed_audio_path and Path(post.processed_audio_path).exists():
        print(f"[TRIGGER_RETURN] status=200 reason=already_processed", file=sys.stderr, flush=True)
        return _render_trigger_page(
            title="Episode Ready",
            message=f"'{post.title}' is ready to play!",
            state="ready",
            post=post,
            feed_title=feed_title,
            download_url=download_url,
            token_id=token_id,
            secret=secret
        )
    
    # Check for existing pending/running job
    existing_job = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid,
        ProcessingJob.status.in_(["pending", "running"])
    ).first()
    
    if existing_job:
        print(f"[TRIGGER_JOB] guid={guid} action=existing job_id={existing_job.id} status={existing_job.status}", file=sys.stderr, flush=True)
        return _render_trigger_page(
            title="Processing In Progress",
            message=f"'{post.title}' is being processed.",
            state="processing",
            post=post,
            feed_title=feed_title,
            download_url=download_url,
            token_id=token_id,
            secret=secret,
            job=existing_job
        )
    
    # Check cooldown (10 minutes)
    _TRIGGER_COOLDOWN_SECONDS = 600
    last_job = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid
    ).order_by(ProcessingJob.created_at.desc()).first()
    
    if last_job and last_job.created_at:
        job_age = (datetime.now(timezone.utc) - last_job.created_at.replace(tzinfo=timezone.utc)).total_seconds()
        if job_age < _TRIGGER_COOLDOWN_SECONDS:
            remaining = int(_TRIGGER_COOLDOWN_SECONDS - job_age)
            print(f"[TRIGGER_RETURN] status=200 reason=cooldown remaining={remaining}s", file=sys.stderr, flush=True)
            return _render_trigger_page(
                title="Please Wait",
                message=f"Processing was recently attempted. Please wait {remaining // 60 + 1} minutes.",
                state="cooldown",
                post=post,
                feed_title=feed_title,
                cooldown_remaining=remaining
            )
    
    # Trigger processing
    try:
        user_id = auth_result.user.id
        print(f"[TRIGGER_JOB] guid={guid} action=create user_id={user_id}", file=sys.stderr, flush=True)
        result = get_jobs_manager().start_post_processing(
            post.guid,
            priority="interactive",
            triggered_by_user_id=user_id,
            trigger_source="trigger_link",
        )
        job_id = result.get("job_id")
        print(f"[TRIGGER_JOB] guid={guid} action=created job_id={job_id}", file=sys.stderr, flush=True)
        
        # Record process started event
        _record_user_event(post, auth_result.user, "PROCESS_STARTED", "feed_scoped", "TRIGGERED", "trigger")
        
        # Fetch the job we just created
        job = ProcessingJob.query.get(job_id) if job_id else None
        
        return _render_trigger_page(
            title="Processing Started",
            message=f"'{post.title}' has been queued for ad removal.",
            state="processing",
            post=post,
            feed_title=feed_title,
            download_url=download_url,
            token_id=token_id,
            secret=secret,
            job=job
        )
    except Exception as e:
        logger.error(f"Failed to trigger processing for {guid}: {e}", exc_info=True)
        print(f"[TRIGGER_JOB] guid={guid} action=error error={e}", file=sys.stderr, flush=True)
        return _render_trigger_error_page(
            title="Processing Error",
            message="Failed to start processing. Please try again in a few minutes.",
            status_code=500
        )


def _normalize_job(job: ProcessingJob, download_url: str | None = None) -> dict:
    """Normalize a ProcessingJob to a safe JSON-serializable dict with defaults.
    
    Handles NULL fields that can occur during early processing stages.
    """
    # Step name mapping for when step_name is NULL
    STEP_NAMES = {
        0: "Initializing",
        1: "Downloading",
        2: "Transcribing", 
        3: "Detecting Ads",
        4: "Processing Audio",
    }
    
    # Safe defaults for potentially NULL fields
    current_step = job.current_step if job.current_step is not None else 0
    total_steps = job.total_steps if job.total_steps and job.total_steps > 0 else 4
    step_name = job.step_name or STEP_NAMES.get(current_step, "Processing")
    
    # Calculate progress percentage with guards
    if job.progress_percentage is not None:
        progress = max(0, min(100, int(job.progress_percentage)))
    elif total_steps > 0:
        progress = min(100, int((current_step / total_steps) * 100))
    else:
        progress = 0
    
    # Determine state from job status
    if job.status == "running":
        state = "processing"
    elif job.status == "pending":
        state = "queued"
    elif job.status == "completed":
        state = "ready"
    elif job.status == "failed":
        state = "failed"
    else:
        state = "processing"  # Default for unknown status
    
    return {
        "state": state,
        "processed": job.status == "completed",
        "download_url": download_url,
        "message": f"Step {current_step}/{total_steps}: {step_name}",
        "job": {
            "id": job.id,
            "status": job.status or "unknown",
            "current_step": current_step,
            "total_steps": total_steps,
            "step_name": step_name,
            "progress_percentage": progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "error_message": getattr(job, 'error_message', None),
        }
    }


@post_bp.route("/api/trigger/status", methods=["GET", "OPTIONS"])
def trigger_status() -> flask.Response:
    """Get processing status for an episode (JSON endpoint for polling).
    
    Required query params:
    - guid: The episode GUID
    - feed_token: The feed-scoped token ID
    - feed_secret: The feed-scoped token secret
    
    Supports OPTIONS for CORS preflight from podcast app webviews.
    """
    # Handle CORS preflight
    if flask.request.method == "OPTIONS":
        response = flask.make_response()
        response.headers["Cache-Control"] = "no-store"
        return response
    guid = flask.request.args.get("guid")
    token_id = flask.request.args.get("feed_token")
    
    try:
        return _handle_trigger_status()
    except Exception as e:
        # Detailed logging for debugging - never log secrets
        import traceback
        token_prefix = token_id[:6] if token_id and len(token_id) >= 6 else token_id
        token_suffix = token_id[-4:] if token_id and len(token_id) >= 4 else ""
        logger.error(f"[TRIGGER_STATUS_500] guid={guid} token={token_prefix}...{token_suffix} error={e}")
        logger.error(f"[TRIGGER_STATUS_500] traceback:\n{traceback.format_exc()}")
        print(f"[TRIGGER_STATUS_500] guid={guid} token={token_prefix}...{token_suffix} error={e}", file=sys.stderr, flush=True)
        print(f"[TRIGGER_STATUS_500] traceback:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        
        # Return 200 with error state so UI keeps rendering
        response = flask.jsonify({
            "state": "error",
            "message": "Temporary error, retrying...",
            "processed": False,
            "download_url": None,
            "job": None
        })
        response.headers["Cache-Control"] = "no-store"
        return response


def _handle_trigger_status() -> flask.Response:
    """Internal handler for trigger status - separated for cleaner error handling."""
    from app.auth.feed_tokens import authenticate_feed_token
    
    guid = flask.request.args.get("guid")
    token_id = flask.request.args.get("feed_token")
    secret = flask.request.args.get("feed_secret")
    
    # Safe logging - never log secrets
    token_prefix = token_id[:6] if token_id and len(token_id) >= 6 else token_id
    token_suffix = token_id[-4:] if token_id and len(token_id) >= 4 else ""
    print(f"[TRIGGER_STATUS] guid={guid} token={token_prefix}...{token_suffix}", file=sys.stderr, flush=True)
    
    if not guid or not token_id or not secret:
        print(f"[TRIGGER_STATUS_RETURN] status=400 reason=missing_params", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "error", "message": "Missing required parameters"})
        response.headers["Cache-Control"] = "no-store"
        return response, 400
    
    # Authenticate the token
    try:
        auth_result = authenticate_feed_token(token_id, secret, f"/api/posts/{guid}/download")
    except Exception as auth_err:
        logger.error(f"Token auth exception for guid={guid}: {auth_err}", exc_info=True)
        print(f"[TRIGGER_STATUS_RETURN] status=401 reason=auth_exception", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "error", "message": "Authentication failed"})
        response.headers["Cache-Control"] = "no-store"
        return response, 401
    
    if not auth_result:
        print(f"[TRIGGER_STATUS_RETURN] status=401 reason=invalid_token", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "error", "message": "Invalid or expired token"})
        response.headers["Cache-Control"] = "no-store"
        return response, 401
    
    # Combined tokens cannot access status
    if auth_result.feed_id is None:
        print(f"[TRIGGER_STATUS_RETURN] status=403 reason=combined_token", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "error", "message": "Combined tokens not allowed"})
        response.headers["Cache-Control"] = "no-store"
        return response, 403
    
    # Look up the post
    post = Post.query.filter_by(guid=guid).first()
    if not post:
        print(f"[TRIGGER_STATUS_RETURN] status=404 reason=post_not_found", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "not_found", "message": "Episode not found"})
        response.headers["Cache-Control"] = "no-store"
        return response, 404
    
    # Verify feed match
    if post.feed_id != auth_result.feed_id:
        print(f"[TRIGGER_STATUS_RETURN] status=403 reason=feed_mismatch", file=sys.stderr, flush=True)
        response = flask.jsonify({"state": "error", "message": "Token not authorized for this episode"})
        response.headers["Cache-Control"] = "no-store"
        return response, 403
    
    # Build download URL
    download_url = f"/api/posts/{post.guid}/download?feed_token={token_id}&feed_secret={secret}"
    
    # Check if processed
    is_processed = post.processed_audio_path and Path(post.processed_audio_path).exists()
    
    if is_processed:
        response = flask.jsonify({
            "state": "ready",
            "processed": True,
            "download_url": download_url,
            "message": "Episode is ready to download",
            "job": None
        })
        response.headers["Cache-Control"] = "no-store"
        return response
    
    # Check for active job
    job = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid,
        ProcessingJob.status.in_(["pending", "running"])
    ).first()
    
    if job:
        # Use normalize_job for safe defaults on potentially NULL fields
        normalized = _normalize_job(job, download_url)
        response = flask.jsonify(normalized)
        response.headers["Cache-Control"] = "no-store"
        return response
    
    # Check for failed job
    last_job = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid
    ).order_by(ProcessingJob.created_at.desc()).first()
    
    if last_job and last_job.status == "failed":
        # Use normalize_job for consistent response structure
        normalized = _normalize_job(last_job, None)
        normalized["message"] = f"Processing failed: {last_job.error_message or 'Unknown error'}"
        response = flask.jsonify(normalized)
        response.headers["Cache-Control"] = "no-store"
        return response
    
    # Not processed, no active job
    response = flask.jsonify({
        "state": "not_started",
        "processed": False,
        "download_url": None,
        "message": "Episode has not been processed yet",
        "job": None
    })
    response.headers["Cache-Control"] = "no-store"
    return response


def _render_trigger_error_page(
    title: str,
    message: str,
    status_code: int = 400
) -> flask.Response:
    """Render a themed error page for trigger failures with proper HTTP status code."""
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Podly Unicorn</title>
    <link rel="icon" type="image/svg+xml" href="/images/logos/favicon.svg">
    <link rel="icon" type="image/png" sizes="96x96" href="/images/logos/favicon-96x96.png">
    <link rel="icon" type="image/x-icon" href="/images/logos/favicon.ico">
    <link rel="apple-touch-icon" href="/images/logos/apple-touch-icon.png">
    <meta name="theme-color" content="#7c3aed">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 480px;
            width: 100%;
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%);
            color: white;
            padding: 24px;
            text-align: center;
        }}
        .header h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
        .header .subtitle {{ opacity: 0.9; font-size: 0.9rem; }}
        .content {{ padding: 24px; text-align: center; }}
        .error-icon {{ font-size: 3rem; margin-bottom: 16px; color: #ef4444; }}
        .error-title {{ font-size: 1.25rem; font-weight: 600; color: #1f2937; margin-bottom: 8px; }}
        .error-message {{ color: #6b7280; margin-bottom: 24px; line-height: 1.5; }}
        .btn {{
            display: inline-block;
            padding: 12px 24px;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            text-align: center;
            transition: transform 0.1s, box-shadow 0.1s;
        }}
        .btn:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        .btn-primary {{ background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%); color: white; }}
        .footer {{ text-align: center; padding: 16px 24px 24px; color: #9ca3af; font-size: 0.8rem; }}
        .footer a {{ color: #7c3aed; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h1>Podly Unicorn</h1>
            <div class="subtitle">Ad-free podcast processing</div>
        </div>
        <div class="content">
            <div class="error-icon">&#9888;</div>
            <div class="error-title">{title}</div>
            <div class="error-message">{message}</div>
            <a href="/" class="btn btn-primary">Go to Podly</a>
        </div>
        <div class="footer">
            <a href="/">Podly Unicorn</a>
        </div>
    </div>
</body>
</html>'''
    
    response = flask.make_response(html, status_code)
    response.headers["Content-Type"] = "text/html"
    return response


def _render_trigger_page(
    title: str,
    message: str,
    state: str,
    post: Optional[Post] = None,
    feed_title: str = "",
    download_url: str = "",
    token_id: str = "",
    secret: str = "",
    job: Optional[ProcessingJob] = None,
    cooldown_remaining: int = 0
) -> flask.Response:
    """Serve the React app for the trigger page.
    
    The React TriggerPage component will handle:
    - Polling /api/trigger/status for updates
    - Displaying the canonical ProcessingProgressUI component
    - Reactive state updates without page refresh
    """
    import os
    from flask import current_app, send_from_directory
    
    static_folder = current_app.static_folder
    if static_folder and os.path.exists(os.path.join(static_folder, "index.html")):
        return send_from_directory(static_folder, "index.html")
    
    # Fallback to simple HTML if React app not built
    return _render_trigger_page_fallback(
        title, message, state, post, feed_title, 
        download_url, token_id, secret, job, cooldown_remaining
    )


def _render_trigger_page_fallback(
    title: str,
    message: str,
    state: str,
    post: Optional[Post] = None,
    feed_title: str = "",
    download_url: str = "",
    token_id: str = "",
    secret: str = "",
    job: Optional[ProcessingJob] = None,
    cooldown_remaining: int = 0
) -> flask.Response:
    """Fallback server-rendered trigger page when React app is not available."""
    
    # Build status endpoint URL for polling
    status_url = ""
    if post and token_id and secret:
        status_url = f"/api/trigger/status?guid={post.guid}&feed_token={token_id}&feed_secret={secret}"
    
    # Progress info
    progress_percent = 0
    step_name = "Queued"
    if job:
        progress_percent = int(job.progress_percentage or 0)
        step_name = job.step_name or f"Step {job.current_step}/{job.total_steps}"
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Podly Unicorn</title>
    <link rel="icon" type="image/svg+xml" href="/images/logos/favicon.svg">
    <link rel="icon" type="image/png" sizes="96x96" href="/images/logos/favicon-96x96.png">
    <link rel="icon" type="image/x-icon" href="/images/logos/favicon.ico">
    <link rel="apple-touch-icon" href="/images/logos/apple-touch-icon.png">
    <meta name="theme-color" content="#7c3aed">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}
        .card {{
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 480px;
            width: 100%;
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%);
            color: white;
            padding: 24px;
            text-align: center;
        }}
        .header h1 {{ font-size: 1.5rem; margin-bottom: 4px; }}
        .header .subtitle {{ opacity: 0.9; font-size: 0.9rem; }}
        .content {{ padding: 24px; }}
        .episode-info {{
            background: #f8f4ff;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .episode-title {{ font-weight: 600; color: #1f2937; margin-bottom: 4px; font-size: 1.1rem; }}
        .episode-show {{ color: #6b7280; font-size: 0.9rem; }}
        .status-message {{ text-align: center; color: #4b5563; margin-bottom: 20px; font-size: 1rem; }}
        .progress-container {{
            background: #e5e7eb;
            border-radius: 999px;
            height: 12px;
            overflow: hidden;
            margin-bottom: 12px;
        }}
        .progress-bar {{
            background: linear-gradient(90deg, #9333ea, #7c3aed);
            height: 100%;
            border-radius: 999px;
            transition: width 0.5s ease;
            width: {progress_percent}%;
        }}
        .progress-bar.indeterminate {{
            width: 30%;
            animation: indeterminate 1.5s infinite ease-in-out;
        }}
        @keyframes indeterminate {{
            0% {{ transform: translateX(-100%); }}
            100% {{ transform: translateX(400%); }}
        }}
        .step-name {{ text-align: center; color: #6b7280; font-size: 0.85rem; margin-bottom: 20px; }}
        .estimate {{ text-align: center; color: #9ca3af; font-size: 0.8rem; margin-bottom: 20px; }}
        .btn {{
            display: block;
            width: 100%;
            padding: 14px 24px;
            border: none;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            text-align: center;
            transition: transform 0.1s, box-shadow 0.1s;
        }}
        .btn:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        .btn-primary {{ background: linear-gradient(135deg, #9333ea 0%, #7c3aed 100%); color: white; }}
        .footer {{ text-align: center; padding: 16px 24px 24px; color: #9ca3af; font-size: 0.8rem; }}
        .footer a {{ color: #7c3aed; text-decoration: none; }}
        .error-icon {{ font-size: 3rem; margin-bottom: 12px; text-align: center; }}
        .success-icon {{ font-size: 3rem; margin-bottom: 12px; color: #10b981; text-align: center; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h1>Podly Unicorn</h1>
            <div class="subtitle">Ad-free podcast processing</div>
        </div>
        <div class="content">
            {"<div class='episode-info'><div class='episode-title'>" + (post.title if post else "") + "</div><div class='episode-show'>" + feed_title + "</div></div>" if post else ""}
            <div id="status-container">
                {"<div class='success-icon'>&#10003;</div>" if state == "ready" else ""}
                {"<div class='error-icon'>&#9888;</div>" if state == "error" else ""}
                <div class="status-message" id="status-message">{message}</div>
                {"<div class='progress-container'><div class='progress-bar " + ("indeterminate" if progress_percent == 0 else "") + "' id='progress-bar' style='width: " + str(progress_percent) + "%'></div></div>" if state == "processing" else ""}
                {"<div class='step-name' id='step-name'>" + step_name + "</div>" if state == "processing" else ""}
                {"<div class='estimate'>Usually takes 1-2 minutes</div>" if state == "processing" else ""}
                {"<a href='" + download_url + "' class='btn btn-primary' id='download-btn'>Download Ad-Free Episode</a>" if state == "ready" else ""}
            </div>
        </div>
        <div class="footer">
            {"This page starts ad removal for your episode.<br>Your download will be ready here when complete." if state == "processing" else "Return to your podcast app to listen."}<br>
            <a href="/">Podly Unicorn</a>
        </div>
    </div>
    {"<script>" + _get_trigger_polling_script(status_url, download_url) + "</script>" if state == "processing" and status_url else ""}
</body>
</html>'''
    
    response = flask.make_response(html)
    response.headers["Content-Type"] = "text/html"
    return response


def _get_trigger_polling_script(status_url: str, download_url: str) -> str:
    """Generate JavaScript for polling the status endpoint."""
    return f'''
        const statusUrl = "{status_url}";
        const downloadUrl = "{download_url}";
        
        async function checkStatus() {{
            try {{
                const response = await fetch(statusUrl + "&t=" + Date.now());
                const data = await response.json();
                
                const statusMessage = document.getElementById('status-message');
                const progressBar = document.getElementById('progress-bar');
                const stepName = document.getElementById('step-name');
                const statusContainer = document.getElementById('status-container');
                
                if (data.state === 'ready') {{
                    statusContainer.innerHTML = `
                        <div class="success-icon">&#10003;</div>
                        <div class="status-message">Episode is ready to play!</div>
                        <a href="${{downloadUrl}}" class="btn btn-primary">Download Ad-Free Episode</a>
                    `;
                    return;
                }} else if (data.state === 'failed') {{
                    statusContainer.innerHTML = `
                        <div class="error-icon">&#9888;</div>
                        <div class="status-message">${{data.message}}</div>
                    `;
                    return;
                }} else if (data.state === 'processing' || data.state === 'queued') {{
                    if (statusMessage) statusMessage.textContent = data.message;
                    if (data.job && progressBar) {{
                        const percent = data.job.progress_percentage || 0;
                        progressBar.style.width = percent + '%';
                        progressBar.classList.toggle('indeterminate', percent === 0);
                    }}
                    if (stepName && data.job) {{
                        stepName.textContent = data.job.step_name || 'Processing...';
                    }}
                }}
                setTimeout(checkStatus, 2000);
            }} catch (error) {{
                console.error('Status check failed:', error);
                setTimeout(checkStatus, 5000);
            }}
        }}
        setTimeout(checkStatus, 2000);
    '''
