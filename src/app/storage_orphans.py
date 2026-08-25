"""Contained maintenance for stale per-job input attempt directories."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.extensions import db
from app.models import Post, ProcessingJob
from shared.processing_paths import get_in_root, get_srv_root

ORPHAN_GRACE = timedelta(hours=24)


@dataclass
class OrphanCleanupResult:
    """Counters returned to the storage-cleanup coordinator."""

    attempt_delete_attempts: int = 0
    attempts_removed: int = 0
    reclaimed_bytes: int = 0
    active_skips: int = 0
    ambiguous_skips: int = 0
    unsafe_skips: int = 0
    grace_skips: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _skipped_attempts: set[str] = field(default_factory=set, init=False, repr=False)


@dataclass(frozen=True)
class _EntrySnapshot:
    name: str
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int
    children: tuple[_EntrySnapshot, ...] = ()


class _UnsafeAttempt(Exception):
    """The attempt contains an entry that cannot be removed safely."""


class _RemovalFailure(Exception):
    """Descriptor-relative removal failed after reclaiming zero or more bytes."""

    def __init__(
        self,
        message: str,
        reclaimed_bytes: int = 0,
        *,
        unsafe: bool = False,
    ) -> None:
        super().__init__(message)
        self.reclaimed_bytes = reclaimed_bytes
        self.unsafe = unsafe


def _directory_flags() -> int:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    return flags


def _same_entry(current: os.stat_result, snapshot: _EntrySnapshot) -> bool:
    same_identity = (
        current.st_dev == snapshot.device
        and current.st_ino == snapshot.inode
        and stat.S_IFMT(current.st_mode) == stat.S_IFMT(snapshot.mode)
    )
    if not same_identity or not stat.S_ISREG(snapshot.mode):
        return same_identity
    return (
        current.st_size == snapshot.size
        and current.st_mtime_ns == snapshot.modified_ns
        and current.st_ctime_ns == snapshot.changed_ns
    )


def _same_directory(current: os.stat_result, expected: os.stat_result) -> bool:
    return (
        current.st_dev == expected.st_dev
        and current.st_ino == expected.st_ino
        and stat.S_ISDIR(current.st_mode)
    )


def _snapshot_directory(directory_fd: int) -> tuple[_EntrySnapshot, ...]:
    snapshots: list[_EntrySnapshot] = []
    for name in sorted(os.listdir(directory_fd)):
        try:
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise _UnsafeAttempt(f"unable to inspect entry {name}: {exc}") from exc
        if stat.S_ISREG(entry_stat.st_mode):
            snapshots.append(
                _EntrySnapshot(
                    name=name,
                    device=entry_stat.st_dev,
                    inode=entry_stat.st_ino,
                    mode=entry_stat.st_mode,
                    size=entry_stat.st_size,
                    modified_ns=entry_stat.st_mtime_ns,
                    changed_ns=entry_stat.st_ctime_ns,
                )
            )
            continue
        if not stat.S_ISDIR(entry_stat.st_mode):
            raise _UnsafeAttempt(f"unsupported entry {name}")
        try:
            child_fd = os.open(name, _directory_flags(), dir_fd=directory_fd)
        except OSError as exc:
            raise _UnsafeAttempt(f"unable to open directory {name}: {exc}") from exc
        try:
            if not _same_directory(os.fstat(child_fd), entry_stat):
                raise _UnsafeAttempt(f"directory changed while opening {name}")
            children = _snapshot_directory(child_fd)
        finally:
            os.close(child_fd)
        snapshots.append(
            _EntrySnapshot(
                name=name,
                device=entry_stat.st_dev,
                inode=entry_stat.st_ino,
                mode=entry_stat.st_mode,
                size=0,
                modified_ns=entry_stat.st_mtime_ns,
                changed_ns=entry_stat.st_ctime_ns,
                children=children,
            )
        )
    return tuple(snapshots)


def _latest_modified_ns(
    directory_stat: os.stat_result, snapshots: tuple[_EntrySnapshot, ...]
) -> int:
    latest = directory_stat.st_mtime_ns
    for snapshot in snapshots:
        latest = max(latest, snapshot.modified_ns)
        if snapshot.children:
            latest = max(
                latest,
                max(
                    child.modified_ns for child in _flatten_snapshots(snapshot.children)
                ),
            )
    return latest


def _flatten_snapshots(
    snapshots: tuple[_EntrySnapshot, ...],
) -> tuple[_EntrySnapshot, ...]:
    flattened: list[_EntrySnapshot] = []
    for snapshot in snapshots:
        flattened.append(snapshot)
        flattened.extend(_flatten_snapshots(snapshot.children))
    return tuple(flattened)


def _remove_snapshot(directory_fd: int, snapshots: tuple[_EntrySnapshot, ...]) -> int:
    expected_names = {snapshot.name for snapshot in snapshots}
    try:
        current_names = set(os.listdir(directory_fd))
    except OSError as exc:
        raise _RemovalFailure(f"unable to re-list directory: {exc}") from exc
    if current_names != expected_names:
        raise _RemovalFailure(
            "directory contents changed during cleanup", unsafe=True
        )

    reclaimed = 0
    for snapshot in snapshots:
        try:
            current = os.stat(snapshot.name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise _RemovalFailure(
                f"unable to revalidate {snapshot.name}: {exc}", reclaimed
            ) from exc
        if not _same_entry(current, snapshot):
            raise _RemovalFailure(
                f"entry changed during cleanup: {snapshot.name}",
                reclaimed,
                unsafe=True,
            )
        if stat.S_ISREG(snapshot.mode):
            try:
                os.unlink(snapshot.name, dir_fd=directory_fd)
            except OSError as exc:
                raise _RemovalFailure(
                    f"unable to remove file {snapshot.name}: {exc}", reclaimed
                ) from exc
            reclaimed += snapshot.size
            continue
        try:
            child_fd = os.open(snapshot.name, _directory_flags(), dir_fd=directory_fd)
        except OSError as exc:
            raise _RemovalFailure(
                f"unable to reopen directory {snapshot.name}: {exc}", reclaimed
            ) from exc
        try:
            if not _same_entry(os.fstat(child_fd), snapshot):
                raise _RemovalFailure(
                    f"directory changed while opening {snapshot.name}",
                    reclaimed,
                    unsafe=True,
                )
            reclaimed += _remove_snapshot(child_fd, snapshot.children)
        except _RemovalFailure as exc:
            raise _RemovalFailure(
                str(exc),
                reclaimed + exc.reclaimed_bytes,
                unsafe=exc.unsafe,
            ) from exc
        finally:
            os.close(child_fd)
        try:
            current = os.stat(snapshot.name, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_entry(current, snapshot):
                raise _RemovalFailure(
                    f"directory changed during cleanup: {snapshot.name}",
                    reclaimed,
                    unsafe=True,
                )
            os.rmdir(snapshot.name, dir_fd=directory_fd)
        except _RemovalFailure:
            raise
        except OSError as exc:
            raise _RemovalFailure(
                f"unable to remove directory {snapshot.name}: {exc}", reclaimed
            ) from exc
    return reclaimed


def _record_skipped_attempt(result: OrphanCleanupResult, attempt_key: str) -> None:
    if attempt_key in result._skipped_attempts:
        return
    result._skipped_attempts.add(attempt_key)
    result.skipped_count += 1


def _record_unsafe(
    result: OrphanCleanupResult,
    message: str,
    *,
    attempt_key: Optional[str] = None,
) -> None:
    result.unsafe_skips += 1
    result.warnings.append(message)
    if attempt_key is not None:
        _record_skipped_attempt(result, attempt_key)


def _job_latest_modified_ns(job: Optional[ProcessingJob]) -> int:
    if job is None:
        return 0
    timestamps = (
        timestamp
        for timestamp in (job.created_at, job.started_at, job.completed_at)
        if timestamp is not None
    )
    return max(
        (int(timestamp.timestamp() * 1e9) for timestamp in timestamps), default=0
    )


def _posts_referencing_attempt(attempt_path: Path) -> list[Post]:
    references: list[Post] = []
    attempt_absolute = Path(os.path.abspath(attempt_path))
    for post in Post.query.filter(Post.unprocessed_audio_path.isnot(None)).all():
        pointer = Path(os.path.abspath(post.unprocessed_audio_path))
        try:
            relative = pointer.relative_to(attempt_absolute)
        except ValueError:
            continue
        if relative.parts:
            references.append(post)
    return references


def _valid_contained_regular_file(path_text: Optional[str], root: Path) -> bool:
    if not path_text:
        return False
    root_absolute = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(path_text))
    try:
        relative = candidate.relative_to(root_absolute)
        root_stat = os.lstat(root_absolute)
    except (ValueError, OSError):
        return False
    if not stat.S_ISDIR(root_stat.st_mode) or not relative.parts:
        return False
    current = root_absolute
    for index, component in enumerate(relative.parts):
        current = current / component
        try:
            current_stat = os.lstat(current)
        except OSError:
            return False
        if index < len(relative.parts) - 1:
            if not stat.S_ISDIR(current_stat.st_mode):
                return False
        elif not stat.S_ISREG(current_stat.st_mode):
            return False
    return True


def _guid_scope(guid: str, feed_id: Optional[int]) -> tuple[str, set[int]]:
    post_feed_ids = {
        row[0]
        for row in Post.query.filter(Post.guid == guid)
        .with_entities(Post.feed_id)
        .all()
    }
    job_feed_ids = {
        row[0]
        for row in ProcessingJob.query.filter(
            ProcessingJob.post_guid == guid,
            ProcessingJob.feed_id.isnot(None),
        )
        .with_entities(ProcessingJob.feed_id)
        .all()
    }
    attributable_feed_ids = post_feed_ids | job_feed_ids
    if len(post_feed_ids) > 1 or len(attributable_feed_ids) > 1:
        return "ambiguous", attributable_feed_ids
    if feed_id is None:
        return "allowed", attributable_feed_ids
    if not attributable_feed_ids:
        return "ambiguous", attributable_feed_ids
    if attributable_feed_ids == {feed_id}:
        return "allowed", attributable_feed_ids
    return "out_of_scope", attributable_feed_ids


def _attempt_directory_state(jobs_root: Path, guid: str, job_id: str) -> str:
    """Return missing, directory, or unsafe without following path components."""
    try:
        root_stat = os.lstat(jobs_root)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unsafe"
    if not stat.S_ISDIR(root_stat.st_mode):
        return "unsafe"
    try:
        root_fd = os.open(os.fspath(jobs_root), _directory_flags())
    except OSError:
        return "unsafe"
    try:
        if not _same_directory(os.fstat(root_fd), root_stat):
            return "unsafe"
        try:
            guid_stat = os.stat(guid, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "missing"
        except OSError:
            return "unsafe"
        if not stat.S_ISDIR(guid_stat.st_mode):
            return "unsafe"
        try:
            guid_fd = os.open(guid, _directory_flags(), dir_fd=root_fd)
        except OSError:
            return "unsafe"
        try:
            if not _same_directory(os.fstat(guid_fd), guid_stat):
                return "unsafe"
            try:
                attempt_stat = os.stat(job_id, dir_fd=guid_fd, follow_symlinks=False)
            except FileNotFoundError:
                return "missing"
            except OSError:
                return "unsafe"
            return "directory" if stat.S_ISDIR(attempt_stat.st_mode) else "unsafe"
        finally:
            os.close(guid_fd)
    finally:
        os.close(root_fd)


def _reconcile_missing_attempt_references(
    result: OrphanCleanupResult,
    jobs_root: Path,
    feed_id: Optional[int],
    cutoff_ns: int,
) -> None:
    for post in Post.query.filter(Post.unprocessed_audio_path.isnot(None)).all():
        pointer = Path(os.path.abspath(post.unprocessed_audio_path))
        try:
            relative = pointer.relative_to(jobs_root)
        except ValueError:
            continue
        if len(relative.parts) < 3:
            result.ambiguous_skips += 1
            result.warnings.append(
                f"ambiguous attempt reference preserved for post {post.id}"
            )
            continue
        guid, job_id = relative.parts[:2]
        attempt_key = f"{guid}/{job_id}"
        attempt_path = jobs_root / guid / job_id
        state = _attempt_directory_state(jobs_root, guid, job_id)
        if state == "directory":
            continue
        if state == "unsafe":
            _record_unsafe(
                result,
                f"unsafe missing-attempt reference for post {post.id}",
                attempt_key=attempt_key,
            )
            continue
        if post.guid != guid:
            result.ambiguous_skips += 1
            _record_skipped_attempt(result, attempt_key)
            result.warnings.append(
                f"ambiguous attempt reference preserved for post {post.id}"
            )
            continue
        scope, _ = _guid_scope(guid, feed_id)
        if scope == "ambiguous":
            result.ambiguous_skips += 1
            _record_skipped_attempt(result, attempt_key)
            result.warnings.append(
                f"ambiguous GUID mapping preserved for post {post.id}"
            )
            continue
        if scope == "out_of_scope":
            continue
        if (
            ProcessingJob.query.filter(
                ProcessingJob.post_guid == guid,
                ProcessingJob.status.in_(["pending", "running"]),
            ).first()
            is not None
        ):
            result.active_skips += 1
            _record_skipped_attempt(result, attempt_key)
            continue
        job = ProcessingJob.query.filter_by(id=job_id).first()
        if job is not None:
            if job.post_guid != guid:
                continue
            if job.status not in ("failed", "cancelled"):
                continue
            if _job_latest_modified_ns(job) >= cutoff_ns:
                result.grace_skips += 1
                _record_skipped_attempt(result, attempt_key)
                continue
        references = _posts_referencing_attempt(attempt_path)
        if len(references) != 1 or references[0].id != post.id:
            result.ambiguous_skips += 1
            _record_skipped_attempt(result, attempt_key)
            result.warnings.append(
                f"ambiguous attempt reference preserved for post {post.id}"
            )
            continue
        if _valid_contained_regular_file(post.processed_audio_path, get_srv_root()):
            continue
        try:
            post.unprocessed_audio_path = None
            db.session.commit()
        except Exception as exc:  # pylint: disable=broad-except
            db.session.rollback()
            result.failed_count += 1
            result.errors.append(
                f"database reconciliation failed for post {post.id}; retry required: {exc}"
            )


def _clear_removed_references(
    result: OrphanCleanupResult,
    references: list[Post],
    attempt_path: Path,
    label: str,
) -> None:
    if not references:
        return
    try:
        for post in references:
            db.session.refresh(post, ["unprocessed_audio_path"])
            if post.unprocessed_audio_path is None:
                continue
            pointer = Path(os.path.abspath(post.unprocessed_audio_path))
            try:
                pointer.relative_to(attempt_path)
            except ValueError:
                continue
            post.unprocessed_audio_path = None
        db.session.commit()
    except Exception as exc:  # pylint: disable=broad-except
        db.session.rollback()
        result.failed_count += 1
        result.errors.append(
            f"database reconciliation failed for removed attempt {label}; "
            f"retry required: {exc}"
        )


def _remove_bound_attempt(
    result: OrphanCleanupResult,
    root_fd: int,
    guid_fd: int,
    attempt_fd: int,
    guid: str,
    job_id: str,
    guid_stat: os.stat_result,
    attempt_stat: os.stat_result,
    snapshots: tuple[_EntrySnapshot, ...],
) -> bool:
    label = f"{guid}/{job_id}"
    result.attempt_delete_attempts += 1
    try:
        current_guid = os.stat(guid, dir_fd=root_fd, follow_symlinks=False)
        current_attempt = os.stat(job_id, dir_fd=guid_fd, follow_symlinks=False)
    except OSError as exc:
        _record_unsafe(
            result,
            f"attempt parent changed for {label}: {exc}",
            attempt_key=label,
        )
        return False
    if not _same_directory(current_guid, guid_stat) or not _same_directory(
        current_attempt, attempt_stat
    ):
        _record_unsafe(result, f"attempt parent changed for {label}", attempt_key=label)
        return False
    reclaimed = 0
    try:
        reclaimed = _remove_snapshot(attempt_fd, snapshots)
        current_attempt = os.stat(job_id, dir_fd=guid_fd, follow_symlinks=False)
        if not _same_directory(current_attempt, attempt_stat):
            raise _RemovalFailure(
                "attempt directory changed during cleanup", reclaimed, unsafe=True
            )
        os.rmdir(job_id, dir_fd=guid_fd)
    except _RemovalFailure as exc:
        result.reclaimed_bytes += exc.reclaimed_bytes
        result.failed_count += 1
        result.errors.append(f"unable to remove attempt {label}: {exc}")
        if exc.unsafe:
            _record_unsafe(
                result,
                f"unsafe attempt changed during removal {label}: {exc}",
                attempt_key=label,
            )
        return False
    except OSError as exc:
        result.reclaimed_bytes += reclaimed
        result.failed_count += 1
        result.errors.append(f"unable to remove attempt {label}: {exc}")
        return False
    result.reclaimed_bytes += reclaimed
    result.attempts_removed += 1
    return True


def _sweep_attempt(
    result: OrphanCleanupResult,
    jobs_root: Path,
    root_fd: int,
    guid_fd: int,
    guid: str,
    job_id: str,
    guid_stat: os.stat_result,
    guid_scope: str,
    feed_id: Optional[int],
    active_guid: Optional[ProcessingJob],
    cutoff_ns: int,
) -> None:
    label = f"{guid}/{job_id}"
    try:
        attempt_stat = os.stat(job_id, dir_fd=guid_fd, follow_symlinks=False)
    except OSError as exc:
        _record_unsafe(
            result, f"unsafe attempt entry {label}: {exc}", attempt_key=label
        )
        return
    if not stat.S_ISDIR(attempt_stat.st_mode):
        _record_unsafe(
            result,
            f"unknown entry in GUID directory {guid}: {job_id}",
            attempt_key=label,
        )
        return
    if active_guid is not None:
        result.active_skips += 1
        _record_skipped_attempt(result, label)
        return
    if guid_scope == "ambiguous":
        result.ambiguous_skips += 1
        _record_skipped_attempt(result, label)
        result.warnings.append(f"ambiguous GUID mapping preserved for {label}")
        return
    if guid_scope == "out_of_scope":
        return
    job = ProcessingJob.query.filter_by(id=job_id).first()
    if job is not None and job.post_guid != guid:
        result.ambiguous_skips += 1
        _record_skipped_attempt(result, label)
        result.warnings.append(f"mismatched attempt/job mapping preserved: {label}")
        return
    if job is not None and job.status not in ("failed", "cancelled"):
        return
    attempt_path = jobs_root / guid / job_id
    references = _posts_referencing_attempt(attempt_path)
    if len(references) > 1 or any(post.guid != guid for post in references):
        result.ambiguous_skips += 1
        _record_skipped_attempt(result, label)
        result.warnings.append(f"ambiguous attempt reference preserved for {label}")
        return
    if references and any(
        _valid_contained_regular_file(post.processed_audio_path, get_srv_root())
        for post in references
    ):
        return
    try:
        attempt_fd = os.open(job_id, _directory_flags(), dir_fd=guid_fd)
    except OSError as exc:
        _record_unsafe(
            result, f"unsafe attempt directory {label}: {exc}", attempt_key=label
        )
        return
    try:
        if not _same_directory(os.fstat(attempt_fd), attempt_stat):
            _record_unsafe(
                result, f"attempt changed while opening {label}", attempt_key=label
            )
            return
        try:
            snapshots = _snapshot_directory(attempt_fd)
        except _UnsafeAttempt as exc:
            _record_unsafe(result, f"unsafe attempt {label}: {exc}", attempt_key=label)
            return
        if (
            max(
                _latest_modified_ns(attempt_stat, snapshots),
                _job_latest_modified_ns(job),
            )
            >= cutoff_ns
        ):
            result.grace_skips += 1
            _record_skipped_attempt(result, label)
            return
        if (
            ProcessingJob.query.filter(
                ProcessingJob.post_guid == guid,
                ProcessingJob.status.in_(["pending", "running"]),
            ).first()
            is not None
        ):
            result.active_skips += 1
            _record_skipped_attempt(result, label)
            return
        current_scope, _ = _guid_scope(guid, feed_id)
        if current_scope == "ambiguous":
            result.ambiguous_skips += 1
            _record_skipped_attempt(result, label)
            result.warnings.append(f"ambiguous GUID mapping preserved for {label}")
            return
        if current_scope == "out_of_scope":
            return
        current_job = ProcessingJob.query.filter_by(id=job_id).first()
        if current_job is not None and (
            current_job.post_guid != guid
            or current_job.status not in ("failed", "cancelled")
        ):
            result.ambiguous_skips += current_job.post_guid != guid
            if current_job.post_guid != guid:
                _record_skipped_attempt(result, label)
                result.warnings.append(
                    f"mismatched attempt/job mapping preserved: {label}"
                )
            return
        current_references = _posts_referencing_attempt(attempt_path)
        if len(current_references) > 1 or any(
            post.guid != guid for post in current_references
        ):
            result.ambiguous_skips += 1
            _record_skipped_attempt(result, label)
            result.warnings.append(f"ambiguous attempt reference preserved for {label}")
            return
        if current_references and any(
            _valid_contained_regular_file(post.processed_audio_path, get_srv_root())
            for post in current_references
        ):
            return
        if _remove_bound_attempt(
            result,
            root_fd,
            guid_fd,
            attempt_fd,
            guid,
            job_id,
            guid_stat,
            attempt_stat,
            snapshots,
        ):
            _clear_removed_references(result, current_references, attempt_path, label)
    finally:
        os.close(attempt_fd)


def _sweep_guid(
    result: OrphanCleanupResult,
    jobs_root: Path,
    root_fd: int,
    guid: str,
    feed_id: Optional[int],
    cutoff_ns: int,
) -> None:
    try:
        guid_stat = os.stat(guid, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        _record_unsafe(result, f"unsafe jobs entry {guid}: {exc}")
        return
    if not stat.S_ISDIR(guid_stat.st_mode):
        _record_unsafe(result, f"unknown entry in jobs root: {guid}")
        return
    try:
        guid_fd = os.open(guid, _directory_flags(), dir_fd=root_fd)
    except OSError as exc:
        _record_unsafe(result, f"unsafe GUID directory {guid}: {exc}")
        return
    try:
        if not _same_directory(os.fstat(guid_fd), guid_stat):
            _record_unsafe(result, f"GUID directory changed while opening {guid}")
            return
        try:
            attempt_names = sorted(os.listdir(guid_fd))
        except OSError as exc:
            _record_unsafe(result, f"unsafe GUID directory {guid}: {exc}")
            return
        active_guid = ProcessingJob.query.filter(
            ProcessingJob.post_guid == guid,
            ProcessingJob.status.in_(["pending", "running"]),
        ).first()
        guid_scope, _ = _guid_scope(guid, feed_id)
        for job_id in attempt_names:
            _sweep_attempt(
                result,
                jobs_root,
                root_fd,
                guid_fd,
                guid,
                job_id,
                guid_stat,
                guid_scope,
                feed_id,
                active_guid,
                cutoff_ns,
            )
        try:
            is_empty = not os.listdir(guid_fd)
        except OSError as exc:
            result.warnings.append(f"unable to inspect GUID directory {guid}: {exc}")
            return
        if is_empty and guid_scope == "ambiguous":
            result.warnings.append(
                f"ambiguous GUID mapping preserved for empty parent {guid}"
            )
        if is_empty and active_guid is None and guid_scope == "allowed":
            try:
                current = os.stat(guid, dir_fd=root_fd, follow_symlinks=False)
                if _same_directory(current, guid_stat):
                    os.rmdir(guid, dir_fd=root_fd)
            except OSError as exc:
                result.warnings.append(
                    f"unable to remove empty GUID directory {guid}: {exc}"
                )
    finally:
        os.close(guid_fd)


def sweep_stale_processing_attempts(
    *,
    feed_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> OrphanCleanupResult:
    """Remove stale jobless attempts from the exact configured attempt layout."""
    result = OrphanCleanupResult()
    jobs_root = Path(os.path.abspath(get_in_root() / "jobs"))
    cutoff_ns = int(((now or datetime.utcnow()) - ORPHAN_GRACE).timestamp() * 1e9)
    _reconcile_missing_attempt_references(result, jobs_root, feed_id, cutoff_ns)
    try:
        root_stat = os.lstat(jobs_root)
    except FileNotFoundError:
        return result
    except OSError as exc:
        _record_unsafe(result, f"unsafe jobs root: {exc}")
        return result
    if not stat.S_ISDIR(root_stat.st_mode):
        _record_unsafe(result, "unsafe jobs root")
        return result
    try:
        root_fd = os.open(os.fspath(jobs_root), _directory_flags())
    except OSError as exc:
        _record_unsafe(result, f"unsafe jobs root: {exc}")
        return result

    try:
        if not _same_directory(os.fstat(root_fd), root_stat):
            _record_unsafe(result, "jobs root changed while opening")
            return result
        for guid in sorted(os.listdir(root_fd)):
            _sweep_guid(result, jobs_root, root_fd, guid, feed_id, cutoff_ns)
    finally:
        os.close(root_fd)
    return result
