import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime

import flask
from flask import Blueprint, g, request, send_file
from flask.typing import ResponseReturnValue

from app.extensions import db
from app.models import Identification, Post, TranscriptSegment

logger = logging.getLogger("global_logger")

admin_bp = Blueprint("admin", __name__)
TRANSCRIPT_EXPORT_FORMATS = {"json", "txt", "srt"}


def _require_admin() -> bool:
    """Check if the current user is an admin. Returns True if authorized."""
    user = getattr(g, "current_user", None)
    if user is None:
        return True  # No auth required (open instance)
    return getattr(user, "role", None) == "admin"


# =========================================================================
# Transcript Export
# =========================================================================

@admin_bp.route("/api/posts/<string:p_guid>/transcript/export", methods=["GET"])
def api_export_transcript(p_guid: str) -> ResponseReturnValue:
    """Export transcript for a single episode.

    Query params:
    - format: json (default), txt, srt
    """
    post = Post.query.filter_by(guid=p_guid).first()
    if not post:
        return flask.jsonify({"error": "Post not found"}), 404

    transcript = _build_transcript_export(post)
    if transcript is None:
        return flask.jsonify({"error": "No transcript available for this episode"}), 404

    fmt = request.args.get("format", "json").lower()
    content, mimetype, suffix = _render_transcript_export(transcript, fmt)
    buf = io.BytesIO(content)
    return send_file(
        buf,
        mimetype=mimetype,
        as_attachment=True,
        download_name=f"{_safe_export_title(post.title)}.{suffix}",
    )


@admin_bp.route("/api/transcripts/export-bulk", methods=["POST"])
def api_export_transcripts_bulk() -> ResponseReturnValue:
    """Export transcripts for multiple episodes or an entire feed.

    JSON body:
    - post_guids: list of post GUIDs (optional)
    - feed_id: export all episodes from a feed (optional)
    - format: json (default), txt
    """
    if not _require_admin():
        return flask.jsonify({"error": "Admin access required"}), 403

    body = request.get_json(silent=True) or {}
    post_guids = body.get("post_guids", [])
    feed_id = body.get("feed_id")
    fmt = body.get("format", "json").lower()
    if fmt not in TRANSCRIPT_EXPORT_FORMATS:
        return flask.jsonify({"error": "Unsupported export format"}), 400

    if feed_id and not post_guids:
        posts = Post.query.filter_by(feed_id=feed_id).all()
        post_guids = [p.guid for p in posts]
    elif not post_guids:
        post_guids = [post.guid for post in Post.query.order_by(Post.id.asc()).all()]

    if not post_guids:
        return flask.jsonify({"error": "No episodes specified"}), 400

    results = []
    for guid in post_guids:
        post = Post.query.filter_by(guid=guid).first()
        if not post:
            continue
        transcript = _build_transcript_export(post)
        if transcript:
            results.append(transcript)

    if not results:
        return flask.jsonify({"error": "No transcripts found for the specified episodes"}), 404

    exported_at = datetime.utcnow().isoformat()
    archive_buffer = io.BytesIO()
    manifest = {
        "exported_at": exported_at,
        "episode_count": len(results),
        "format": fmt,
        "episodes": [],
    }
    with zipfile.ZipFile(
        archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        for index, transcript in enumerate(results, start=1):
            content, _, suffix = _render_transcript_export(transcript, fmt)
            safe_name = _safe_export_title(transcript["post_title"])
            archive_name = f"{index:03d}_{safe_name}.{suffix}"
            archive.writestr(archive_name, content)
            manifest["episodes"].append(
                {
                    "post_guid": transcript["post_guid"],
                    "post_title": transcript["post_title"],
                    "feed_title": transcript["feed_title"],
                    "file_name": archive_name,
                }
            )
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))

    archive_buffer.seek(0)
    return send_file(
        archive_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"transcripts_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip",
    )


# =========================================================================
# Database Backup & Restore
# =========================================================================

def _get_db_path() -> str:
    """Resolve the SQLite database path from the app config."""
    uri = flask.current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "", 1)
    return os.path.join(
        flask.current_app.instance_path, "sqlite3.db"
    )


@admin_bp.route("/api/admin/backup", methods=["POST"])
def api_backup_database() -> ResponseReturnValue:
    """Download a backup of the SQLite database."""
    if not _require_admin():
        return flask.jsonify({"error": "Admin access required"}), 403

    db_path = _get_db_path()
    if not os.path.exists(db_path):
        return flask.jsonify({"error": f"Database file not found at {db_path}"}), 500

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(
        db_path,
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name=f"podly_backup_{timestamp}.db",
    )


@admin_bp.route("/api/admin/restore", methods=["POST"])
def api_restore_database() -> ResponseReturnValue:
    """Restore the SQLite database from an uploaded file.

    Expects multipart form with a 'file' field containing the .db file.
    Creates a backup of the current database before overwriting.
    """
    if not _require_admin():
        return flask.jsonify({"error": "Admin access required"}), 403

    if "file" not in request.files:
        return flask.jsonify({"error": "No file provided"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return flask.jsonify({"error": "No file selected"}), 400

    db_path = _get_db_path()

    # Save the upload to a temp file and validate it's a valid SQLite DB
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    try:
        uploaded.save(tmp.name)
        tmp.close()

        # Basic validation: check SQLite header magic
        with open(tmp.name, "rb") as f:
            header = f.read(16)
        if not header.startswith(b"SQLite format 3"):
            os.unlink(tmp.name)
            return flask.jsonify({"error": "Uploaded file is not a valid SQLite database"}), 400

        # Create pre-restore backup
        backup_path = db_path + f".pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        if os.path.exists(db_path):
            shutil.copy2(db_path, backup_path)
            logger.info("Pre-restore backup created at %s", backup_path)

        # Close all DB connections before replacing
        db.session.remove()
        db.engine.dispose()

        # Replace the database
        shutil.copy2(tmp.name, db_path)
        os.unlink(tmp.name)

        logger.info("Database restored from uploaded file")
        return flask.jsonify({
            "status": "success",
            "message": "Database restored successfully. Pre-restore backup saved.",
            "backup_path": backup_path,
        })
    except Exception as e:
        logger.error("Database restore failed: %s", e, exc_info=True)
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
        return flask.jsonify({"error": f"Restore failed: {str(e)}"}), 500


# =========================================================================
# Helpers
# =========================================================================

def _fmt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS.ms"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


def _srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _safe_export_title(title: str | None) -> str:
    base = title or "episode"
    safe = "".join(c if c.isalnum() or c in " -_" else "" for c in base).strip()
    return (safe or "episode")[:80]


def _build_transcript_export(post: Post) -> dict | None:
    segments = (
        TranscriptSegment.query.filter_by(post_id=post.id)
        .order_by(TranscriptSegment.sequence_num)
        .all()
    )
    if not segments:
        return None

    identifications = (
        Identification.query.join(TranscriptSegment)
        .filter(TranscriptSegment.post_id == post.id)
        .all()
    )
    ad_segment_ids = {
        identification.transcript_segment_id
        for identification in identifications
        if identification.label == "ad"
    }

    return {
        "post_guid": post.guid,
        "post_title": post.title,
        "feed_title": post.feed.title if post.feed else None,
        "exported_at": datetime.utcnow().isoformat(),
        "segments": [
            {
                "sequence_num": segment.sequence_num,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "text": segment.text,
                "is_ad": segment.id in ad_segment_ids,
            }
            for segment in segments
        ],
    }


def _render_transcript_export(transcript: dict, fmt: str) -> tuple[bytes, str, str]:
    if fmt not in TRANSCRIPT_EXPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")

    if fmt == "txt":
        lines = []
        for segment in transcript["segments"]:
            label = "[AD] " if segment["is_ad"] else ""
            lines.append(f"[{_fmt_time(segment['start_time'])}] {label}{segment['text']}")
        return "\n".join(lines).encode("utf-8"), "text/plain", "txt"

    if fmt == "srt":
        lines = []
        for index, segment in enumerate(transcript["segments"], start=1):
            lines.append(str(index))
            lines.append(
                f"{_srt_time(segment['start_time'])} --> {_srt_time(segment['end_time'])}"
            )
            label = "[AD] " if segment["is_ad"] else ""
            lines.append(f"{label}{segment['text']}")
            lines.append("")
        return "\n".join(lines).encode("utf-8"), "application/x-subrip", "srt"

    return json.dumps(transcript, indent=2).encode("utf-8"), "application/json", "json"
