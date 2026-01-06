import logging
import os
import re
import time
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
    """Track a download for the current user if authenticated."""
    try:
        current_user = getattr(g, "current_user", None)
        if not current_user:
            return  # No user to track
        download_source = "rss" if getattr(g, "feed_token", None) is not None else "web"
        
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


# Cooldown tracking for on-demand processing triggers
# Key: post_guid, Value: timestamp of last trigger
_on_demand_trigger_cooldowns: dict[str, float] = {}
_ON_DEMAND_COOLDOWN_SECONDS = 600  # 10 minutes between triggers for same GUID


@post_bp.route("/api/posts/<string:p_guid>/download", methods=["GET", "HEAD"])
def api_download_post(p_guid: str) -> flask.Response:
    """API endpoint to download processed audio files.
    
    On-demand processing flow for podcast apps (Overcast, Pocket Casts, Apple Podcasts):
    
    1. HEAD requests: Never trigger processing, return 204 No Content
    2. GET requests for unprocessed episodes:
       - If job already pending/running: Return 202 with Retry-After
       - If within cooldown window: Return 202 with Retry-After (no new job)
       - Otherwise: Start job, return 202 with Retry-After
    3. GET requests for processed episodes: Return audio file
    
    Key design decisions:
    - HEAD = true probe, never triggers (return 204)
    - GET with any Range CAN trigger (podcast apps use Range for real downloads)
    - Cooldown prevents trigger storms from aggressive clients
    - 202 only returned when job exists or was just started
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
    feed_token = getattr(g, "feed_token", None)
    range_header = flask.request.headers.get("Range")
    user_agent = flask.request.headers.get("User-Agent", "")
    request_method = flask.request.method
    
    # Check if episode is already processed and available
    is_processed = post.processed_audio_path and Path(post.processed_audio_path).exists()
    
    # --- DIAGNOSTIC LOGGING (always log for debugging) ---
    logger.info(
        "DOWNLOAD_REQUEST: post=%s feed_id=%s method=%s range=%s "
        "user_id=%s feed_token=%s ua=%s is_processed=%s",
        post.guid[:16],
        post.feed_id,
        request_method,
        range_header,
        current_user.id if current_user else None,
        "yes" if feed_token else "no",
        user_agent[:60] if user_agent else "none",
        is_processed,
    )
    
    if is_processed:
        # Episode is ready - serve it
        pass  # Fall through to file serving below
    else:
        # Episode not yet processed - determine response
        
        # --- TIER 1: HEAD = true probe, never trigger ---
        if request_method == "HEAD":
            logger.info(
                "DOWNLOAD_DECISION: post=%s decision=HEAD_PROBE response=204",
                post.guid[:16],
            )
            # 204 No Content - tells client "nothing here yet" without implying retry
            return flask.make_response(("", 204))
        
        # --- AUTHORIZATION CHECK ---
        # User must be authorized via session OR feed token
        # Podcast apps use feed token in URL since they don't send cookies
        is_authorized = False
        if current_user and post.feed_id:
            subscription = UserFeedSubscription.query.filter_by(
                user_id=current_user.id,
                feed_id=post.feed_id,
            ).first()
            if subscription:
                is_authorized = True
        
        if not is_authorized:
            logger.info(
                "DOWNLOAD_DECISION: post=%s decision=NOT_AUTHORIZED response=401 "
                "user_id=%s feed_token=%s",
                post.guid[:16],
                current_user.id if current_user else None,
                "yes" if feed_token else "no",
            )
            return flask.make_response(("Authentication required", 401))
        
        # --- CHECK FOR EXISTING JOB ---
        existing_job = ProcessingJob.query.filter(
            ProcessingJob.post_guid == post.guid,
            ProcessingJob.status.in_(["pending", "running"])
        ).first()
        
        if existing_job:
            logger.info(
                "DOWNLOAD_DECISION: post=%s decision=JOB_EXISTS job_id=%s status=%s response=202",
                post.guid[:16],
                existing_job.id,
                existing_job.status,
            )
            response = flask.make_response(("Processing in progress", 202))
            response.headers["Retry-After"] = "120"
            return response
        
        # --- TIER 2: GET triggers, but with cooldown ---
        # Check cooldown to prevent trigger storms
        now = time.time()
        last_trigger = _on_demand_trigger_cooldowns.get(post.guid, 0)
        cooldown_remaining = _ON_DEMAND_COOLDOWN_SECONDS - (now - last_trigger)
        
        if cooldown_remaining > 0:
            # Within cooldown window - don't trigger again
            logger.info(
                "DOWNLOAD_DECISION: post=%s decision=COOLDOWN_ACTIVE cooldown_remaining=%ds response=202",
                post.guid[:16],
                int(cooldown_remaining),
            )
            response = flask.make_response(("Processing recently requested", 202))
            response.headers["Retry-After"] = str(min(int(cooldown_remaining) + 10, 300))
            return response
        
        # --- TRIGGER PROCESSING ---
        # This is a GET from an authorized user, no existing job, cooldown expired
        logger.info(
            "DOWNLOAD_DECISION: post=%s decision=TRIGGER_PROCESSING user_id=%s response=202",
            post.guid[:16],
            current_user.id if current_user else None,
        )
        
        # Set cooldown BEFORE starting job to prevent race conditions
        _on_demand_trigger_cooldowns[post.guid] = now
        
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
            
            response = flask.make_response(("Processing started", 202))
            response.headers["Retry-After"] = "120"
            return response
        except Exception as e:
            logger.error(f"Failed to trigger on-demand processing for {p_guid}: {e}")
            # Clear cooldown on failure so retry can work
            _on_demand_trigger_cooldowns.pop(post.guid, None)
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
