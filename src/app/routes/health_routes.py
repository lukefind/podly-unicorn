import logging

from flask import Blueprint, jsonify

from app.refresh_health import refresh_health

health_bp = Blueprint("health", __name__)
logger = logging.getLogger("global_logger")


@health_bp.get("/health")
def health():
    snapshot = refresh_health.snapshot()
    if snapshot["status"] == "stale":
        if refresh_health.mark_stale_logged():
            logger.error(
                "Background feed refresh is stale at feed %s",
                snapshot["current_feed_id"],
            )
        return jsonify(snapshot), 503
    return jsonify(snapshot), 200
