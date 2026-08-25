"""Safe reconciliation of episode processing artifacts.

The coordinator deliberately preserves feed and episode metadata.  It only
reconciles filesystem artifacts and processing-derived database state.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import or_

from app.extensions import db
from app.jobs_manager_run_service import recalculate_affected_run_counts
from app.models import (
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    ProcessingStatistics,
    TranscriptSegment,
)
from shared.processing_paths import get_in_root, get_srv_root

logger = logging.getLogger("global_logger")
MAX_RETENTION_COUNT = 2_147_483_647


@dataclass
class StorageCleanupResult:
    """JSON-serializable outcome of one storage-cleanup coordinator run."""

    trigger: str
    scope: dict[str, Optional[int]]
    evaluated_policies: list[dict[str, Any]] = field(default_factory=list)
    requested_count: int = 0
    selected_count: int = 0
    cleaned_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    files_removed: int = 0
    file_delete_attempts: int = 0
    attempts_removed: int = 0
    attempt_delete_attempts: int = 0
    reclaimed_bytes: int = 0
    active_skips: int = 0
    ambiguous_skips: int = 0
    unsafe_skips: int = 0
    grace_skips: int = 0
    candidate_post_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            {
                "policies": payload["evaluated_policies"],
                "candidates": payload["selected_count"],
                "episodes_cleaned": payload["cleaned_count"],
            }
        )
        return payload


def is_valid_retention_count(value: object) -> bool:
    """Return whether a stored value is a supported positive count policy."""
    return type(value) is int and 0 < value <= MAX_RETENTION_COUNT


def _global_age_cutoff(value: object) -> Optional[datetime]:
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.utcnow() - timedelta(days=value)
    except OverflowError:
        return None


def _release_sort_key(post: Post) -> tuple[bool, datetime, int]:
    return (
        post.release_date is not None,
        post.release_date or datetime.min,
        post.id,
    )


def _contained_file(path_text: str, root: Path) -> tuple[Optional[Path], str]:
    root_absolute = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path_text))
    if root_absolute.is_symlink() or not root_absolute.is_dir():
        return None, "unsafe"
    try:
        relative = candidate.relative_to(root_absolute)
    except ValueError:
        return None, "unsafe"
    current = root_absolute
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return None, "unsafe"

    root_resolved = root_absolute.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, "unsafe"
    if candidate.is_symlink():
        return None, "unsafe"
    if not candidate.exists():
        return resolved, "missing"
    if not candidate.is_file():
        return None, "unsafe"
    return resolved, "file"


def _latest_successful_completion(post: Post) -> Optional[datetime]:
    unique_guid = Post.query.filter(Post.guid == post.guid).count() == 1
    attribution = ProcessingJob.feed_id == post.feed_id
    if unique_guid:
        attribution = or_(attribution, ProcessingJob.feed_id.is_(None))
    query = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid,
        ProcessingJob.status == "completed",
        ProcessingJob.completed_at.isnot(None),
        attribution,
    )
    return max((job.completed_at for job in query.all()), default=None)


def _other_post_references_path(post: Post, path: Path) -> bool:
    """Return whether another episode points at the same normalized file."""
    normalized = os.path.normcase(os.path.abspath(path))
    rows = (
        db.session.query(Post.processed_audio_path, Post.unprocessed_audio_path)
        .filter(Post.id != post.id)
        .filter(
            or_(
                Post.processed_audio_path.isnot(None),
                Post.unprocessed_audio_path.isnot(None),
            )
        )
        .all()
    )
    return any(
        os.path.normcase(os.path.abspath(pointer)) == normalized
        for row in rows
        for pointer in row
        if pointer
    )


def _unlink_contained_file(
    path_text: str, root: Path
) -> tuple[str, int, Optional[OSError]]:
    """Unlink below root using no-follow directory descriptors."""
    root_absolute = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path_text))
    try:
        relative = candidate.relative_to(root_absolute)
    except ValueError:
        return "unsafe", 0, None
    if not relative.parts:
        return "unsafe", 0, None

    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        parent_fd = os.open(os.fspath(root_absolute), directory_flags)
    except OSError as exc:
        return "unsafe", 0, exc

    try:
        for component in relative.parts[:-1]:
            try:
                next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            except FileNotFoundError:
                return "missing", 0, None
            except OSError as exc:
                return "unsafe", 0, exc
            os.close(parent_fd)
            parent_fd = next_fd

        filename = relative.parts[-1]
        try:
            file_stat = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing", 0, None
        except OSError as exc:
            return "failed", 0, exc
        if not stat.S_ISREG(file_stat.st_mode):
            return "unsafe", 0, None
        try:
            os.unlink(filename, dir_fd=parent_fd)
        except FileNotFoundError:
            return "missing", 0, None
        except OSError as exc:
            return "failed", 0, exc
        return "removed", file_stat.st_size, None
    finally:
        os.close(parent_fd)


def _remove_audio_file(
    post: Post,
    attribute: str,
    root: Path,
    result: StorageCleanupResult,
) -> bool:
    path_text = getattr(post, attribute)
    if not path_text:
        return True
    path, state = _contained_file(path_text, root)
    if state == "unsafe" or path is None:
        result.unsafe_skips += 1
        result.warnings.append(f"unsafe {attribute} for post {post.id}")
        return False
    if state == "missing":
        setattr(post, attribute, None)
        return True
    if _other_post_references_path(post, path):
        setattr(post, attribute, None)
        result.warnings.append(f"preserved shared {attribute} for post {post.id}")
        return True
    result.file_delete_attempts += 1
    unlink_state, size, error = _unlink_contained_file(path_text, root)
    if unlink_state == "missing":
        setattr(post, attribute, None)
        return True
    if unlink_state == "unsafe":
        result.unsafe_skips += 1
        result.warnings.append(
            f"unsafe {attribute} for post {post.id}" + (f": {error}" if error else "")
        )
        return False
    if unlink_state == "failed":
        result.errors.append(
            f"unable to remove {attribute} for post {post.id}: {error}"
        )
        return False
    setattr(post, attribute, None)
    result.files_removed += 1
    result.reclaimed_bytes += size
    return True


def _delete_derived_records(post: Post, result: StorageCleanupResult) -> None:
    segment_ids = [
        row[0]
        for row in db.session.query(TranscriptSegment.id)
        .filter(TranscriptSegment.post_id == post.id)
        .all()
    ]
    model_call_ids = [
        row[0]
        for row in db.session.query(ModelCall.id)
        .filter(ModelCall.post_id == post.id)
        .all()
    ]
    if segment_ids:
        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(segment_ids)
        ).delete(synchronize_session=False)
    if model_call_ids:
        db.session.query(Identification).filter(
            Identification.model_call_id.in_(model_call_ids)
        ).delete(synchronize_session=False)
    db.session.query(TranscriptSegment).filter(
        TranscriptSegment.post_id == post.id
    ).delete(synchronize_session=False)
    db.session.query(ModelCall).filter(ModelCall.post_id == post.id).delete(
        synchronize_session=False
    )
    db.session.query(ProcessingStatistics).filter(
        ProcessingStatistics.post_id == post.id
    ).delete(synchronize_session=False)

    unique_guid = Post.query.filter(Post.guid == post.guid).count() == 1
    if not unique_guid:
        ambiguous_count = ProcessingJob.query.filter(
            ProcessingJob.post_guid == post.guid,
            ProcessingJob.feed_id.is_(None),
            ~ProcessingJob.status.in_(["pending", "running"]),
        ).count()
        if ambiguous_count:
            result.ambiguous_skips += ambiguous_count
            result.warnings.append(
                f"preserved {ambiguous_count} ambiguous legacy jobs for post {post.id}"
            )
    job_query = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid,
        ~ProcessingJob.status.in_(["pending", "running"]),
    ).filter(
        (ProcessingJob.feed_id == post.feed_id)
        | (ProcessingJob.feed_id.is_(None) if unique_guid else False)
    )
    affected_run_ids = {
        run_id
        for (run_id,) in job_query.with_entities(
            ProcessingJob.jobs_manager_run_id
        ).distinct()
        if run_id
    }
    job_query.delete(synchronize_session=False)
    db.session.flush()
    recalculate_affected_run_counts(db.session, affected_run_ids)
    post.refined_ad_boundaries = None
    post.refined_ad_boundaries_updated_at = None
    post.processed_with_preset_id = None


def _record_active_skip(post: Post, result: StorageCleanupResult) -> bool:
    """Record the single skip outcome when any job sharing the GUID is active."""
    active = ProcessingJob.query.filter(
        ProcessingJob.post_guid == post.guid,
        ProcessingJob.status.in_(["pending", "running"]),
    ).first()
    if not active:
        return False
    result.active_skips += 1
    result.skipped_count += 1
    return True


def _current_policy_allows_cleanup(
    post: Post,
    result: StorageCleanupResult,
    global_retention_days: Optional[int],
) -> bool:
    """Re-evaluate the feed override immediately before destructive work."""
    feed = db.session.get(Feed, post.feed_id)
    if feed is None:
        return False
    db.session.refresh(feed, ["processed_episode_retention_count"])
    current_count = feed.processed_episode_retention_count
    if is_valid_retention_count(current_count):
        ranked = sorted(
            Post.query.filter(
                Post.feed_id == post.feed_id,
                Post.processed_audio_path.isnot(None),
                Post.processed_audio_path != "",
            ).all(),
            key=_release_sort_key,
            reverse=True,
        )
        valid_ranked = [
            item
            for item in ranked
            if _contained_file(item.processed_audio_path, get_srv_root())[1] == "file"
        ]
        retained_ids = {item.id for item in valid_ranked[:current_count]}
        return post.id not in retained_ids
    if current_count is not None:
        return False

    original_policy = next(
        (
            policy.get("policy")
            for policy in result.evaluated_policies
            if policy.get("feed_id") == post.feed_id
        ),
        None,
    )
    if original_policy == "age":
        return True
    cutoff = _global_age_cutoff(global_retention_days)
    if cutoff is None:
        return False
    path, state = _contained_file(post.processed_audio_path, get_srv_root())
    if state == "unsafe":
        return False
    timestamps = [
        timestamp
        for timestamp in (
            _latest_successful_completion(post),
            (
                datetime.utcfromtimestamp(path.stat().st_mtime)
                if path is not None and state == "file"
                else None
            ),
        )
        if timestamp is not None
    ]
    return bool(timestamps) and max(timestamps) < cutoff


def _cleanup_selected_post(
    post: Post,
    result: StorageCleanupResult,
    global_retention_days: Optional[int],
) -> None:
    if _record_active_skip(post, result):
        return
    if not _current_policy_allows_cleanup(post, result, global_retention_days):
        result.skipped_count += 1
        result.warnings.append(f"policy changed before cleanup for post {post.id}")
        return
    for attribute, root in (
        ("processed_audio_path", get_srv_root()),
        ("unprocessed_audio_path", get_in_root()),
    ):
        path_text = getattr(post, attribute)
        if path_text and _contained_file(path_text, root)[1] == "unsafe":
            result.unsafe_skips += 1
            result.skipped_count += 1
            result.warnings.append(f"unsafe {attribute} for post {post.id}")
            return
    input_removed = _remove_audio_file(
        post, "unprocessed_audio_path", get_in_root(), result
    )
    if not input_removed:
        result.failed_count += 1
        return
    output_removed = _remove_audio_file(
        post, "processed_audio_path", get_srv_root(), result
    )
    if not output_removed:
        result.failed_count += 1
        return
    _delete_derived_records(post, result)
    result.cleaned_count += 1


def _cleanup_candidate_and_commit(
    post: Post,
    result: StorageCleanupResult,
    global_retention_days: Optional[int],
) -> None:
    """Isolate one candidate's database mutation from unrelated candidates."""
    post_id = post.id
    cleaned_before = result.cleaned_count
    failed_before = result.failed_count
    skipped_before = result.skipped_count
    active_before = result.active_skips
    ambiguous_before = result.ambiguous_skips
    unsafe_before = result.unsafe_skips
    grace_before = result.grace_skips
    try:
        _cleanup_selected_post(post, result, global_retention_days)
        if (
            result.cleaned_count == cleaned_before
            and result.failed_count == failed_before
        ):
            return
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        result.cleaned_count = cleaned_before
        result.failed_count = failed_before + 1
        result.skipped_count = skipped_before
        result.active_skips = active_before
        result.ambiguous_skips = ambiguous_before
        result.unsafe_skips = unsafe_before
        result.grace_skips = grace_before
        result.errors.append(
            "database cleanup failed for post "
            f"{post_id}; retry required after partial filesystem cleanup: {exc}"
        )


def _reconcile_missing_input(post: Post, result: StorageCleanupResult) -> None:
    """Clear only a confirmed-missing input while valid output is retained."""
    if not post.unprocessed_audio_path:
        return
    if _record_active_skip(post, result):
        return
    path, state = _contained_file(post.unprocessed_audio_path, get_in_root())
    if state == "missing" and path is not None:
        post.unprocessed_audio_path = None
    elif state == "unsafe":
        result.unsafe_skips += 1
        result.skipped_count += 1
        result.warnings.append(f"unsafe unprocessed_audio_path for post {post.id}")


def _reconcile_missing_output_preserving_state(
    post: Post, result: StorageCleanupResult
) -> None:
    if not post.processed_audio_path:
        return
    if _record_active_skip(post, result):
        return
    path, state = _contained_file(post.processed_audio_path, get_srv_root())
    if state == "missing" and path is not None:
        post.processed_audio_path = None
        result.warnings.append(
            f"missing processed output reconciled for post {post.id}"
        )
    elif state == "unsafe":
        result.unsafe_skips += 1
        result.skipped_count += 1
        result.warnings.append(f"unsafe processed_audio_path for post {post.id}")


def _run_isolated_post_operation(
    post: Post,
    result: StorageCleanupResult,
    operation: Callable[[], None],
    failure_label: str,
) -> None:
    """Roll back one post's failed evaluation without aborting the coordinator."""
    post_id = post.id
    counters_before = {
        field_name: getattr(result, field_name)
        for field_name in (
            "requested_count",
            "selected_count",
            "cleaned_count",
            "skipped_count",
            "failed_count",
            "active_skips",
            "ambiguous_skips",
            "unsafe_skips",
            "grace_skips",
        )
    }
    candidate_count = len(result.candidate_post_ids)
    warning_count = len(result.warnings)
    error_count = len(result.errors)
    try:
        operation()
        session = db.session()
        if session.new or session.dirty or session.deleted:
            db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        for field_name, value in counters_before.items():
            setattr(result, field_name, value)
        result.failed_count += 1
        del result.candidate_post_ids[candidate_count:]
        del result.warnings[warning_count:]
        del result.errors[error_count:]
        result.errors.append(
            f"{failure_label} failed for post {post_id}; retry required: {exc}"
        )


def _process_age_post(
    post: Post,
    age_cutoff: datetime,
    global_retention_days: Optional[int],
    srv_root: Path,
    result: StorageCleanupResult,
) -> None:
    path, state = _contained_file(post.processed_audio_path, srv_root)
    if state == "unsafe":
        result.unsafe_skips += 1
        result.skipped_count += 1
        result.warnings.append(f"unsafe processed_audio_path for post {post.id}")
        return
    if state == "missing" and _record_active_skip(post, result):
        return
    timestamps = [
        stamp
        for stamp in (
            _latest_successful_completion(post),
            (
                datetime.utcfromtimestamp(path.stat().st_mtime)
                if path is not None and state == "file"
                else None
            ),
        )
        if stamp is not None
    ]
    if not timestamps:
        result.skipped_count += 1
        result.warnings.append(f"no trustworthy processed timestamp for post {post.id}")
        if state == "missing":
            _reconcile_missing_output_preserving_state(post, result)
        return
    if state == "missing" and max(timestamps) >= age_cutoff:
        _reconcile_missing_output_preserving_state(post, result)
        return
    if state == "file" and max(timestamps) >= age_cutoff:
        _reconcile_missing_input(post, result)
        return
    if path is None:
        return
    result.requested_count += 1
    result.selected_count += 1
    result.candidate_post_ids.append(post.id)
    _cleanup_candidate_and_commit(post, result, global_retention_days)


def run_storage_cleanup(
    global_retention_days: Optional[int],
    *,
    feed_id: Optional[int] = None,
    trigger: str = "manual",
) -> StorageCleanupResult:
    """Reconcile retained episode artifacts for the requested scope."""
    result = StorageCleanupResult(trigger=trigger, scope={"feed_id": feed_id})
    srv_root = get_srv_root()
    age_cutoff = _global_age_cutoff(global_retention_days)
    feeds_query = Feed.query
    if feed_id is not None:
        feeds_query = feeds_query.filter(Feed.id == feed_id)

    for feed in feeds_query.order_by(Feed.id).all():
        count = feed.processed_episode_retention_count
        if is_valid_retention_count(count):
            result.evaluated_policies.append(
                {"feed_id": feed.id, "policy": "count", "retention_count": count}
            )
            ranked = sorted(
                [post for post in feed.posts if post.processed_audio_path],
                key=_release_sort_key,
                reverse=True,
            )
            states = {
                post.id: _contained_file(post.processed_audio_path, srv_root)
                for post in ranked
            }
            for post in ranked:
                if states[post.id][1] == "unsafe":
                    result.unsafe_skips += 1
                    result.skipped_count += 1
                    result.warnings.append(
                        f"unsafe processed_audio_path for post {post.id}"
                    )
            provisional_retained = {post.id for post in ranked[:count]}
            missing_provisional_candidates = [
                post for post in ranked[count:] if states[post.id][1] == "missing"
            ]
            valid_ranked = [post for post in ranked if states[post.id][1] == "file"]
            selected_ids = {
                post.id
                for post in missing_provisional_candidates + valid_ranked[count:]
            }
            selected = [post for post in ranked if post.id in selected_ids]
            for post in valid_ranked[:count]:
                _run_isolated_post_operation(
                    post,
                    result,
                    lambda post=post: _reconcile_missing_input(post, result),
                    "count reconciliation",
                )
            result.requested_count += len(selected)
            result.selected_count += len(selected)
            result.candidate_post_ids.extend(post.id for post in selected)

            for post in ranked:
                _, state = states[post.id]
                if state == "missing" and post.id in provisional_retained:
                    _run_isolated_post_operation(
                        post,
                        result,
                        lambda post=post: _reconcile_missing_output_preserving_state(
                            post, result
                        ),
                        "count reconciliation",
                    )

            for post in selected:
                _cleanup_candidate_and_commit(post, result, global_retention_days)
            continue

        if count is not None or age_cutoff is None:
            result.evaluated_policies.append({"feed_id": feed.id, "policy": "disabled"})
            if count is not None:
                result.warnings.append(
                    f"invalid count retention policy ignored for feed {feed.id}"
                )
            for post in [item for item in feed.posts if item.processed_audio_path]:
                path, state = _contained_file(post.processed_audio_path, srv_root)
                if state == "missing":
                    _run_isolated_post_operation(
                        post,
                        result,
                        lambda post=post: _reconcile_missing_output_preserving_state(
                            post, result
                        ),
                        "disabled-policy reconciliation",
                    )
                elif state == "file" and path is not None:
                    _run_isolated_post_operation(
                        post,
                        result,
                        lambda post=post: _reconcile_missing_input(post, result),
                        "disabled-policy reconciliation",
                    )
                elif state == "unsafe":
                    result.unsafe_skips += 1
                    result.skipped_count += 1
                    result.warnings.append(
                        f"unsafe processed_audio_path for post {post.id}"
                    )
            continue
        result.evaluated_policies.append(
            {
                "feed_id": feed.id,
                "policy": "age",
                "retention_days": global_retention_days,
            }
        )
        for post in [item for item in feed.posts if item.processed_audio_path]:
            _run_isolated_post_operation(
                post,
                result,
                lambda post=post: _process_age_post(
                    post,
                    age_cutoff,
                    global_retention_days,
                    srv_root,
                    result,
                ),
                "age evaluation",
            )

    session = db.session()
    if session.new or session.dirty or session.deleted:
        try:
            db.session.commit()
        except Exception as exc:  # pylint: disable=broad-except
            db.session.rollback()
            result.failed_count += 1
            result.errors.append(
                "database reconciliation failed; retry required after partial "
                f"filesystem cleanup: {exc}"
            )
    logger.info(
        "storage_cleanup_summary %s", json.dumps(result.to_dict(), sort_keys=True)
    )
    return result
