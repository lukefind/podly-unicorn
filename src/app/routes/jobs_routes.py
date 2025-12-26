import logging

import flask
from flask import Blueprint, g, request
from flask.typing import ResponseReturnValue
from sqlalchemy import desc

from app.extensions import db
from app.jobs_manager import get_jobs_manager
from app.jobs_manager_run_service import (
    get_active_run,
    recalculate_run_counts,
    serialize_run,
)
from app.models import Post, ProcessingJob, User

logger = logging.getLogger("global_logger")


jobs_bp = Blueprint("jobs", __name__)


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
            "post_title": post.title if post else None,
            "feed_title": post.feed.title if post and post.feed else None,
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
