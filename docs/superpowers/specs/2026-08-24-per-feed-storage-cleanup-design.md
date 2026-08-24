# Per-Feed Storage Cleanup Design

## Summary

Podly will support an administrator-controlled retention limit for each feed. A
feed can keep only its newest `X` successfully processed episodes, ordered by
podcast release date. Feeds without an override continue to use the existing
global age-based policy.

Cleanup will retain the episode and feed metadata needed to display and
reprocess an episode. It will remove local input/output audio and processing
data. The same maintenance service will also reclaim stale, abandoned job
artifacts that are not covered reliably by the current path-based cleanup.

The global age policy will be moved into a discoverable **Storage & Cleanup**
section with an explicit enabled state. The per-feed setting will be available
from **Podcasts → Show settings → Storage cleanup**. Both controls are
administrator-only when authentication is enabled.

This design changes application code and schema only. It does not inspect,
modify, or infer the state of any production database during development.

## Goals

- Let an administrator configure a feed to keep the newest `X` processed
  episodes.
- Keep episode metadata after cleanup so an old episode remains visible and can
  be processed again.
- Preserve the current global age policy for feeds without a count override.
- Make the global automatic-cleanup setting clear and discoverable.
- Enforce a saved per-feed policy immediately and during daily maintenance.
- Reclaim safe, stale job downloads and retry artifacts.
- Never delete files outside Podly's configured podcast-data roots.
- Avoid cleanup of an episode with pending or running processing work.
- Report useful cleanup totals in structured logs.

## Non-Goals

- Per-user retention policies. Processed media is shared by all subscribers to
  a feed.
- Byte quotas or percentage-based disk limits.
- Cloud/object-storage lifecycle management.
- Automatic changes to existing production settings during migration.
- A persistent cleanup-run history dashboard.

## Confirmed Product Decisions

- Retention is count-based per feed.
- Cleaned episodes remain in Podly.
- A feed without a count override inherits the global age policy.
- Only administrators can change shared cleanup settings.
- Saving a per-feed policy queues enforcement immediately.
- The retained set is ordered by podcast release date, not processing date.
- The work includes correction of global cleanup behavior and safe orphaned-job
  artifact cleanup.

## Data Model

Add one nullable column to `feed`:

```text
processed_episode_retention_count INTEGER NULL
```

Semantics:

- `NULL`: inherit the global age policy.
- Positive integer: keep the newest that many processed episodes for this feed.
- `0` and negative values are invalid. Disabling the override is represented by
  `NULL`, not a sentinel value.

The model change requires a focused Alembic migration based on the actual
current migration head. Upgrade adds the nullable column. Downgrade removes only
that column. Existing feeds receive `NULL`, so deployment does not silently
change their effective retention policy.

The existing nullable `app_settings.post_cleanup_retention_days` remains the
global setting:

- `NULL`: global age cleanup is disabled for feeds that inherit it.
- Positive integer: clean eligible processed episodes older than that many
  days.

The UI will no longer represent the disabled global policy as an unexplained
blank number input.

## Effective Policy

The cleanup service resolves exactly one episode-retention policy for each
feed:

1. If `processed_episode_retention_count` is positive, use count retention.
2. Otherwise, if global age cleanup is enabled, use age retention.
3. Otherwise, do not clean retained episode artifacts for that feed.

Orphaned job-attempt maintenance is independent of the episode-retention policy
and can still run when global age cleanup is disabled.

The daily maintenance job must remain scheduled when any feed uses count
retention, even if the global age policy is disabled. Prefer a single daily
storage-maintenance job that always runs and resolves current policies at run
time over enabling/disabling the scheduler solely from the global days value.

## Retained-Set Selection

### Per-Feed Count Policy

A processed episode counts toward the retained set when its processed-audio
artifact exists. Candidate episodes are ordered by:

1. `Post.release_date DESC`, with missing release dates last.
2. `Post.id DESC` as a deterministic tie-breaker.

The first `X` episodes are retained. Every remaining processed episode is a
cleanup candidate.

The selection and final deletion checks must use the feed ID and post ID. GUIDs
are not globally unique across feeds.

### Global Age Policy

For a feed inheriting the global policy, a processed episode is eligible when
its conservative processed timestamp is older than the cutoff. Timestamp
sources are:

- the latest successful `ProcessingJob.completed_at`, when present; and
- the processed file modification time, when the file exists.

When both exist, use the newer timestamp so recently recreated output is not
deleted because of an older job record. If neither source is trustworthy, skip
the episode and log the reason rather than guessing.

### Active Work

Both policies exclude posts with a pending or running processing job. The
cleanup operation rechecks active work immediately before changing files or
database records so a job that started after candidate selection is preserved.
Because legacy job identity is GUID-based, an active job sharing a GUID is
treated conservatively as a reason to skip cleanup.

### Missing-Artifact Reconciliation

Before policy selection, maintenance performs a reconciliation pass for posts
whose database audio path is set but whose artifact is missing. If the post has
no active work, this pass finishes the database side of cleanup: it clears stale
audio paths and removes the same processing-derived rows described below. This
is the durable retry path when file removal succeeded but a prior database
transaction failed. It also prevents a missing artifact from occupying one of a
feed's retained count slots indefinitely.

Reconciliation is independent of age/count eligibility because there is no
artifact left to retain. It keeps the post and audit data, is idempotent, and
uses the same shared-GUID job scoping rules as normal cleanup.

## Episode Cleanup Operation

Cleanup is idempotent and isolated per episode.

For an eligible post:

1. Recheck the effective policy and active-job state.
2. Resolve and validate all candidate paths against the configured podcast-data
   roots.
3. Remove the referenced unprocessed and processed audio files.
4. Remove only safe job-attempt directories associated with the episode; do not
   delete a GUID root blindly because different feeds can share a GUID.
5. In a database transaction, remove processing-derived records:
   transcript segments, identifications, model calls, processing jobs,
   processing statistics, refined-boundary data, and the processed-preset
   reference.
6. Clear `unprocessed_audio_path` and `processed_audio_path` on the post.

Processing-job reads and deletes require special scoping because legacy rows
are linked by GUID and `ProcessingJob.feed_id` is nullable:

- jobs with `feed_id == Post.feed_id` belong to the post's feed;
- a legacy job with `feed_id IS NULL` may be attributed only when the GUID maps
  to exactly one current post/feed;
- an ambiguous legacy job for a GUID shared across feeds is preserved and
  logged rather than guessed; and
- pending/running rows sharing the GUID remain a conservative skip signal.

The same rule applies when deriving the latest successful completion timestamp.
Before deleting jobs, collect their non-null `jobs_manager_run_id` values. After
deletion, recalculate the affected `JobsManagerRun` counters within the database
transaction so run history cannot retain stale totals.

The following remain:

- the `Post` row and its RSS metadata;
- release date, title, description, duration, and source download URL;
- whitelist state;
- feed and subscription records; and
- user download/audit history.

This leaves the episode visible and eligible for explicit reprocessing later.

Filesystem and database changes cannot be one atomic transaction. If file
removal fails, keep the corresponding database path and derived records so the
next run can retry. If filesystem removal succeeds but the database transaction
fails, the next maintenance run reconciles the now-missing artifact and retries
the database cleanup. One episode failure does not abort unrelated candidates.

## Orphaned Job-Artifact Maintenance

The current job input layout is conceptually:

```text
data/in/jobs/<post-guid>/<job-id>/<download-and-temporary-files>
```

The orphan sweep operates only under the resolved configured `data/in/jobs`
root. It examines job-attempt directories rather than assuming a GUID belongs
to exactly one feed.

An attempt is preserved when any of these apply:

- a pending or running job references the attempt;
- any post currently references a file inside it;
- any file in the attempt is newer than the 24-hour safety grace period; or
- resolving the path would leave the configured jobs root.

Otherwise, a stale attempt may be removed when its job is terminal or absent.
After attempt removal, empty GUID directories may be removed. The traversal
must not follow symlinks outside the jobs root. Missing paths are successful
no-ops.

This sweep runs during daily storage maintenance, after an immediate per-feed
cleanup where relevant, and when an administrator invokes server-wide cleanup.

## Coordination and Scheduling

All cleanup entry points call one storage-maintenance coordinator:

- daily scheduled maintenance;
- immediate feed enforcement after a policy save; and
- administrator-requested **Run cleanup now**.

The coordinator prevents overlapping runs in the application process and
coalesces duplicate immediate requests. The daily recurring schedule must not
be replaced accidentally when a one-shot run is queued. Each run resolves
settings from the database at execution time.

Immediately before deleting an episode, the coordinator recomputes its active
state and its eligibility under the current count rank or age cutoff. This
protects an artifact that was recreated or moved into the retained set after
the initial candidate query.

The existing `PODLY_DISABLE_SCHEDULER=1` behavior remains authoritative. When
the scheduler is disabled, saving a policy still succeeds but the API must not
claim that automatic enforcement is running; it returns a clear status that
manual or external execution is required.

## API Design

### Feed Policy

`POST /api/feeds/<feed_id>/cleanup-policy`

Administrator-only payload:

```json
{
  "retention_count": 5
}
```

Use `null` to restore global inheritance:

```json
{
  "retention_count": null
}
```

Validation rejects booleans, non-integers, zero, and negative values. The feed
must exist. A successful response returns HTTP 202 when immediate cleanup was
queued, or an explicit non-queued status when scheduling is disabled. It
includes:

- feed ID;
- configured count;
- effective policy type and value; and
- cleanup dispatch status.

`GET /feeds` includes the configured count and effective cleanup policy for
feeds visible to the caller. Sensitive maintenance details are not exposed to
non-admin users.

### Global Policy

The existing combined configuration API continues to persist
`post_cleanup_retention_days`. The frontend maps the explicit enabled toggle to
a positive value or `null`. Backend validation rejects enabled values below one.
Changing from disabled to enabled, or changing the day count, queues immediate
server-wide enforcement.

`PUT /api/config` continues to return HTTP 200 after the configuration is
durably saved, but its response becomes an explicit envelope:

```json
{
  "config": { "app": { "post_cleanup_retention_days": 14 } },
  "cleanup_dispatch": {
    "requested": true,
    "status": "queued"
  }
}
```

`cleanup_dispatch.status` is one of `queued`, `coalesced`,
`scheduler_disabled`, or `not_requested`. `requested` is true only when the
submitted payload changed the global retention value. The complete sanitized
configuration remains in `config`; the abbreviated object above is only an
example. The frontend updates its `ConfigUpdateResponse` type, continues to
refetch configuration after saving, and uses `cleanup_dispatch` for the toast.
Configuration success is not reported as failure merely because dispatch is
disabled; the UI clearly says the policy was saved but automatic enforcement
is unavailable.

### Manual Run

`POST /api/admin/storage-cleanup/run`

Administrator-only. It queues a server-wide maintenance pass and returns HTTP
202 with a clear dispatch status. Repeated requests while a run is active are
coalesced rather than creating overlapping deletion work.

Authorization is enforced by the backend even when the UI hides controls.

## Frontend Design

### Global Storage & Cleanup

Replace the buried generic cleanup number with a dedicated **Storage & Cleanup**
section on the Settings page. It contains:

- **Enable automatic cleanup** toggle;
- **Keep processed episodes for X days** positive integer input;
- explanation that per-feed episode limits override the global policy;
- explanation that orphaned abandoned job files are maintained separately; and
- **Run cleanup now** administrator action.

The disabled state is explicit. The UI does not use an empty field as the only
signal that cleanup is off. Saving or enabling confirms that maintenance was
queued, or reports that the scheduler is disabled.

### Feed Storage Cleanup

Add **Storage cleanup** to the existing Show settings dropdown for
administrators. Selecting it opens a `createPortal` modal attached to
`document.body`.

The modal offers:

- **Use global policy**, with the current global policy summarized; or
- **Keep latest X processed episodes**, with a positive integer input.

Saving calls the feed cleanup-policy API, closes the modal on success, reports
the selected policy and dispatch status, and invalidates feed and episode
queries. Errors keep the modal open and preserve the entered value.

Non-admin users do not see the menu item. The API remains the source of truth.

## Observability

Every maintenance run logs a structured summary containing:

- trigger (`scheduled`, `feed_policy_save`, or `manual_admin`);
- scope (server-wide or feed ID);
- policies evaluated;
- episode candidates, cleaned episodes, and active-job skips;
- referenced files and orphan attempt directories removed;
- bytes reclaimed when sizes are available;
- unsafe-path and grace-period skips; and
- per-item and total error counts.

Logs must not include credentials, feed access secrets, or unrelated user data.

## Testing Strategy

### Cleanup Service Tests

- Count retention keeps the newest `X` processed episodes by release date.
- Equal and missing release dates use deterministic ordering.
- Count retention is scoped by feed ID when GUIDs overlap.
- A per-feed count overrides global age retention.
- A `NULL` feed setting inherits global age retention.
- Disabled global age retention leaves unconfigured feed artifacts intact.
- Age retention uses the newer of completion time and file modification time.
- Missing timestamps are skipped safely.
- Missing-artifact reconciliation completes database cleanup after a simulated
  filesystem-success/database-failure sequence.
- Pending and running work is excluded and rechecked.
- Final eligibility is recomputed before deletion.
- Cleanup retains the post, RSS metadata, whitelist state, and download audit.
- Cleanup removes audio and processing-derived records and clears processing
  fields.
- A file-deletion error preserves retryable database state.
- Repeated cleanup is idempotent.
- Feed-scoped jobs are deleted without touching another feed that shares a
  GUID.
- Ambiguous legacy null-feed jobs are preserved and logged.
- Affected jobs-manager run counters are recalculated after job deletion.

### Orphan Sweep Tests

- Stale unreferenced terminal/absent attempt directories are removed.
- Current post paths, active jobs, and recent attempts are preserved.
- Multiple retry attempts under one GUID are handled independently.
- Shared GUIDs across feeds do not cause broad directory deletion.
- Empty parent directories are removed only after safe child cleanup.
- Symlink and path-escape attempts are rejected.
- Missing paths are harmless.

### API and Authorization Tests

- Admin can set, replace, and clear a feed count.
- Anonymous and non-admin callers receive the appropriate 401/403 responses.
- Invalid values return 400 without changing the saved policy.
- Missing feeds return 404.
- Responses include configured and effective policies and dispatch state.
- Manual server-wide cleanup is administrator-only and coalesces overlaps.
- Global settings changes dispatch immediate maintenance when appropriate.
- Global configuration responses distinguish queued, coalesced,
  scheduler-disabled, and not-requested dispatch states.

### Frontend Tests and Checks

- Global enabled/disabled mapping is explicit and persists the correct payload.
- Per-feed modal switches between inheritance and count modes correctly.
- Invalid counts cannot be submitted.
- Successful saves invalidate feed/episode state and surface dispatch status.
- Non-admin users do not receive cleanup controls.
- Frontend unit tests, TypeScript checks, and the production build pass.

### Migration Verification

- Upgrade from the actual previous revision adds the nullable feed column.
- Existing feed rows retain inherited behavior.
- Downgrade removes only the new column.
- Model metadata and migration schema agree.

## Rollout

The migration is additive. Deploying it does not automatically delete any
production artifact and does not invent a retention value for existing feeds.

After deployment:

1. An administrator reviews **Settings → Storage & Cleanup**.
2. The administrator explicitly enables or saves the global age policy if
   desired.
3. The administrator configures count overrides on high-volume feeds.
4. Saving a feed policy queues its immediate enforcement.
5. **Run cleanup now** can queue a full policy pass and orphan sweep.
6. Operators verify structured cleanup summaries and reclaimed-byte totals in
   application logs before relying on subsequent daily runs.

Production database inspection or direct cleanup is outside the scope of the
code implementation unless separately and explicitly requested.
