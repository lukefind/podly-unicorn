import logging
from datetime import datetime, timedelta

import flask
from flask import Blueprint, g, request
from flask.typing import ResponseReturnValue
from sqlalchemy import case, desc, func

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.jobs_manager_run_service import (
    get_active_run,
    recalculate_run_counts,
    serialize_run,
)
from app.models import Feed, Post, ProcessingJob, User

logger = logging.getLogger("global_logger")


jobs_bp = Blueprint("jobs", __name__)


def _require_admin_analytics() -> ResponseReturnValue | None:
    settings = flask.current_app.config.get("AUTH_SETTINGS")
    if not settings or not getattr(settings, "require_auth", False):
        return None

    current_user = getattr(g, "current_user", None)
    if current_user is None:
        return flask.jsonify({"error": "Authentication required"}), 401

    user = User.query.get(current_user.id)
    if not user or user.role != "admin":
        return flask.jsonify({"error": "Admin privileges required"}), 403
    return None


@jobs_bp.route("/api/jobs/active", methods=["GET"])
def api_list_active_jobs() -> ResponseReturnValue:
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    result = get_jobs_manager().list_active_jobs(limit=limit)
    return flask.jsonify(result)


@jobs_bp.route("/api/jobs/all", methods=["GET"])
def api_list_all_jobs() -> ResponseReturnValue:
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    result = get_jobs_manager().list_all_jobs_detailed(limit=limit)
    return flask.jsonify(result)


@jobs_bp.route("/api/job-manager/status", methods=["GET"])
def api_job_manager_status() -> ResponseReturnValue:
    run = get_active_run(db.session)
    if run:
        recalculate_run_counts(db.session)

    # Persist any aggregate updates performed above
    db.session.commit()

    return flask.jsonify({"run": serialize_run(run) if run else None})


@jobs_bp.route("/api/jobs/clear-history", methods=["POST"])
def api_clear_job_history() -> ResponseReturnValue:
    """Clear completed, failed, cancelled, and skipped jobs from history."""
    from app.models import ProcessingJob

    error_response = _require_admin_analytics()
    if error_response is not None:
        return error_response
    
    try:
        # Delete jobs that are not active (pending/running)
        deleted = ProcessingJob.query.filter(
            ProcessingJob.status.in_(["completed", "failed", "cancelled", "skipped"])
        ).delete(synchronize_session=False)
        
        db.session.commit()
        
        return flask.jsonify({
            "status": "success",
            "deleted_count": deleted,
            "message": f"Cleared {deleted} jobs from history"
        })
    except Exception as e:
        logger.error(f"Failed to clear job history: {e}")
        db.session.rollback()
        return flask.jsonify({
            "status": "error",
            "message": f"Failed to clear history: {str(e)}"
        }), 500


@jobs_bp.route("/api/jobs/<string:job_id>/cancel", methods=["POST"])
def api_cancel_job(job_id: str) -> ResponseReturnValue:
    try:
        result = get_jobs_manager().cancel_job(job_id)
        status_code = (
            200
            if result.get("status") == "cancelled"
            else (404 if result.get("error_code") == "NOT_FOUND" else 400)
        )

        db.session.expire_all()

        return flask.jsonify(result), status_code
    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "error_code": "CANCEL_FAILED",
                    "message": f"Failed to cancel job: {str(e)}",
                }
            ),
            500,
        )


@jobs_bp.route("/api/jobs/dashboard", methods=["GET"])
def api_jobs_dashboard() -> ResponseReturnValue:
    """Aggregate jobs metrics for the dashboard.

    Query params:
    - days: Number of days to look back (default 30, max 365)
    """
    error_response = _require_admin_analytics()
    if error_response is not None:
        return error_response

    try:
        days = min(int(request.args.get("days", "30")), 365)
    except ValueError:
        days = 30

    cutoff = datetime.utcnow() - timedelta(days=days)

    # --- Overall counts ---
    total_all_time = ProcessingJob.query.count()
    total_period = ProcessingJob.query.filter(ProcessingJob.created_at >= cutoff).count()

    status_counts = (
        db.session.query(ProcessingJob.status, func.count(ProcessingJob.id))
        .filter(ProcessingJob.created_at >= cutoff)
        .group_by(ProcessingJob.status)
        .all()
    )
    by_status = {status: count for status, count in status_counts}

    # --- Daily job counts (for chart) ---
    daily_rows = (
        db.session.query(
            func.date(ProcessingJob.created_at).label("day"),
            ProcessingJob.status,
            func.count(ProcessingJob.id),
        )
        .filter(ProcessingJob.created_at >= cutoff)
        .group_by(func.date(ProcessingJob.created_at), ProcessingJob.status)
        .order_by(func.date(ProcessingJob.created_at))
        .all()
    )
    daily: dict = {}
    for day, status, count in daily_rows:
        day_str = str(day)
        if day_str not in daily:
            daily[day_str] = {"date": day_str, "total": 0}
        daily[day_str][status] = count
        daily[day_str]["total"] += count
    daily_list = list(daily.values())

    # --- Jobs per user ---
    username_label = case(
        (ProcessingJob.triggered_by_user_id.is_(None), "System"),
        (User.username.is_(None), "Deleted user"),
        else_=User.username,
    )
    user_rows = (
        db.session.query(
            func.coalesce(ProcessingJob.triggered_by_user_id, 0).label("user_id"),
            username_label.label("username"),
            func.count(ProcessingJob.id).label("job_count"),
            func.sum(
                case((ProcessingJob.status == "completed", 1), else_=0)
            ).label("completed"),
            func.sum(
                case((ProcessingJob.status == "failed", 1), else_=0)
            ).label("failed"),
        )
        .outerjoin(User, ProcessingJob.triggered_by_user_id == User.id)
        .filter(ProcessingJob.created_at >= cutoff)
        .group_by(
            func.coalesce(ProcessingJob.triggered_by_user_id, 0),
            username_label,
        )
        .order_by(desc("job_count"))
        .all()
    )
    by_user = [
        {
            "user_id": uid,
            "username": uname,
            "total": total,
            "completed": int(comp or 0),
            "failed": int(fail or 0),
        }
        for uid, uname, total, comp, fail in user_rows
    ]

    # --- Jobs per podcast (feed) ---
    feed_rows = (
        db.session.query(
            ProcessingJob.feed_id,
            ProcessingJob.feed_title,
            func.max(Feed.image_url).label("image_url"),
            func.count(ProcessingJob.id).label("job_count"),
            func.sum(
                case((ProcessingJob.status == "completed", 1), else_=0)
            ).label("completed"),
        )
        .outerjoin(Feed, Feed.id == ProcessingJob.feed_id)
        .filter(ProcessingJob.created_at >= cutoff)
        .filter(
            (ProcessingJob.feed_id.isnot(None))
            | (ProcessingJob.feed_title.isnot(None))
        )
        .group_by(ProcessingJob.feed_id, ProcessingJob.feed_title)
        .order_by(desc("job_count"))
        .limit(20)
        .all()
    )
    by_feed = [
        {
            "feed_id": fid,
            "title": ftitle or "Unknown feed",
            "image_url": fimg,
            "total": total,
            "completed": int(comp or 0),
        }
        for fid, ftitle, fimg, total, comp in feed_rows
    ]

    # --- Processing performance ---
    completed_jobs = (
        ProcessingJob.query.filter(
            ProcessingJob.status == "completed",
            ProcessingJob.started_at.isnot(None),
            ProcessingJob.completed_at.isnot(None),
            ProcessingJob.created_at >= cutoff,
        )
        .order_by(ProcessingJob.completed_at.desc())
        .all()
    )
    durations = [
        (j.completed_at - j.started_at).total_seconds()
        for j in completed_jobs
        if j.completed_at and j.started_at
    ]
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0
    min_duration = round(min(durations), 1) if durations else 0
    max_duration = round(max(durations), 1) if durations else 0

    # --- Ad removal stats for the period ---
    total_ads_removed = sum(j.total_ad_segments_removed or 0 for j in completed_jobs)
    total_time_removed = round(
        sum(j.total_duration_removed_seconds or 0 for j in completed_jobs), 1
    )
    percentage_values = [
        float(j.percentage_removed)
        for j in completed_jobs
        if j.percentage_removed is not None
    ]
    avg_pct_removed = (
        round(sum(percentage_values) / len(percentage_values), 1)
        if percentage_values
        else 0
    )

    # --- Trigger source breakdown ---
    trigger_rows = (
        db.session.query(
            ProcessingJob.trigger_source, func.count(ProcessingJob.id)
        )
        .filter(ProcessingJob.created_at >= cutoff)
        .group_by(ProcessingJob.trigger_source)
        .all()
    )
    by_trigger = {(src or "unknown"): cnt for src, cnt in trigger_rows}

    # --- Recent completed jobs with stats ---
    recent_completed = (
        db.session.query(ProcessingJob, User)
        .outerjoin(User, ProcessingJob.triggered_by_user_id == User.id)
        .filter(
            ProcessingJob.status == "completed",
            ProcessingJob.created_at >= cutoff,
        )
        .order_by(ProcessingJob.completed_at.desc())
        .limit(20)
        .all()
    )
    recent_list = []
    for job, user in recent_completed:
        duration_secs = None
        if job.started_at and job.completed_at:
            duration_secs = round((job.completed_at - job.started_at).total_seconds(), 1)
        recent_list.append({
            "job_id": job.id,
            "post_guid": job.post_guid,
            "post_title": job.post_title,
            "feed_title": job.feed_title,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "duration_seconds": duration_secs,
            "triggered_by": user.username if user else None,
            "trigger_source": job.trigger_source,
            "ads_removed": job.total_ad_segments_removed,
            "time_removed_seconds": (
                round(job.total_duration_removed_seconds, 1)
                if job.total_duration_removed_seconds is not None else None
            ),
            "percentage_removed": (
                round(job.percentage_removed, 1)
                if job.percentage_removed is not None else None
            ),
        })

    return flask.jsonify({
        "period_days": days,
        "overview": {
            "total_all_time": total_all_time,
            "total_period": total_period,
            "by_status": by_status,
            "by_trigger_source": by_trigger,
        },
        "daily": daily_list,
        "by_user": by_user,
        "by_feed": by_feed,
        "performance": {
            "completed_count": len(durations),
            "avg_duration_seconds": avg_duration,
            "min_duration_seconds": min_duration,
            "max_duration_seconds": max_duration,
            "total_ads_removed": total_ads_removed,
            "total_time_removed_seconds": total_time_removed,
            "avg_percentage_removed": avg_pct_removed,
        },
        "recent_completed": recent_list,
    })


@jobs_bp.route("/api/jobs/history", methods=["GET"])
def api_job_history() -> ResponseReturnValue:
    """Get detailed job history with filtering options.
    
    Query params:
    - limit: Max results (default 50, max 200)
    - status: Filter by status (completed, failed, cancelled, etc.)
    - trigger_source: Filter by trigger source (manual_ui, auto_feed_refresh, etc.)
    - user_id: Filter by user who triggered (admin only)
    """
    try:
        limit = min(int(request.args.get("limit", "50")), 200)
    except ValueError:
        limit = 50
    
    status_filter = request.args.get("status")
    trigger_filter = request.args.get("trigger_source")
    user_filter = request.args.get("user_id")
    
    query = ProcessingJob.query
    
    if status_filter:
        query = query.filter(ProcessingJob.status == status_filter)
    if trigger_filter:
        query = query.filter(ProcessingJob.trigger_source == trigger_filter)
    if user_filter:
        try:
            query = query.filter(ProcessingJob.triggered_by_user_id == int(user_filter))
        except ValueError:
            pass
    
    jobs = query.order_by(desc(ProcessingJob.created_at)).limit(limit).all()
    
    # Build response with user and post info
    result = []
    for job in jobs:
        post = Post.query.filter_by(guid=job.post_guid).first()
        user = User.query.get(job.triggered_by_user_id) if job.triggered_by_user_id else None
        
        result.append({
            "id": job.id,
            "post_guid": job.post_guid,
            "post_title": post.title if post else job.post_title,
            "feed_title": post.feed.title if post and post.feed else job.feed_title,
            "status": job.status,
            "trigger_source": job.trigger_source,
            "triggered_by_user_id": job.triggered_by_user_id,
            "triggered_by_username": user.username if user else None,
            "current_step": job.current_step,
            "step_name": job.step_name,
            "total_steps": job.total_steps,
            "progress_percentage": job.progress_percentage,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        })
    
    # Get summary stats
    total_jobs = ProcessingJob.query.count()
    completed_count = ProcessingJob.query.filter_by(status="completed").count()
    failed_count = ProcessingJob.query.filter_by(status="failed").count()
    
    # Trigger source breakdown
    trigger_stats = {}
    for source in ["manual_ui", "manual_reprocess", "auto_feed_refresh", "on_demand_rss"]:
        trigger_stats[source] = ProcessingJob.query.filter_by(trigger_source=source).count()
    trigger_stats["unknown"] = ProcessingJob.query.filter(
        (ProcessingJob.trigger_source.is_(None)) | (ProcessingJob.trigger_source == "")
    ).count()
    
    return flask.jsonify({
        "jobs": result,
        "summary": {
            "total": total_jobs,
            "completed": completed_count,
            "failed": failed_count,
            "by_trigger_source": trigger_stats,
        }
    })
