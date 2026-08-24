# Per-Feed Storage Cleanup Implementation Plan
> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let administrators keep only the newest configured number of processed episodes for an individual feed, preserve episode metadata for reprocessing, make the inherited global age policy discoverable, and safely reconcile stale processing artifacts.

**Architecture:** Replace the destructive post-pruning routine with a storage-maintenance coordinator. The coordinator selects per-feed count candidates and inherited global-age candidates, skips active or ambiguous shared-GUID work, deletes only owned audio and derived processing artifacts, reconciles database paths with filesystem results, and performs a contained orphan-attempt sweep. APScheduler runs the coordinator daily regardless of whether global age cleanup is enabled. Immediate dispatches use a locked scope accumulator: feed-policy saves merge feed IDs, while global/manual requests escalate the pending scope to server-wide, so coalescing never loses or broadens the requested work accidentally.

**Tech Stack:** Flask, Flask-SQLAlchemy, Alembic/Flask-Migrate, APScheduler, SQLite, React 19, TypeScript, TanStack Query, Vitest, Docker/Compose, GitHub Actions, GHCR.

**Authoritative design:** `docs/superpowers/specs/2026-08-24-per-feed-storage-cleanup-design.md`

---

### Task 0: Restore the production container build gate

**Files:**
- Modify: `Dockerfile`
- Modify: `src/tests/test_container_build_contracts.py`

- [x] **Step 1: Reproduce the floating Wolfi package conflict**

Run the lite production-compatible build and confirm the Python 3.12 package installs `pip 26.2.1` before the Dockerfile overlays pinned `pip 26.1.2` with `--ignore-installed`, producing an import error.

Command:

```bash
docker build --build-arg LITE_BUILD=true -t podly-storage-cleanup-baseline:local .
```

Expected before the fix: failure importing `get_runnable_pip` from a mixed pip installation.

- [x] **Step 2: Add and run the failing build contract**

Require the first application dependency installation to use `--force-reinstall` and forbid `--ignore-installed` for the pinned pip package.

Run the isolated contract and verify it fails because the Dockerfile lacks the new command:

```bash
./.venv/bin/python - <<'PY'
import importlib.util
from pathlib import Path
path = Path('src/tests/test_container_build_contracts.py')
spec = importlib.util.spec_from_file_location('container_contracts', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.test_container_pip_replaces_newer_distribution_package_before_downgrade()
PY
```

- [x] **Step 3: Make the minimal Dockerfile change and verify the contract**

Replace only `--ignore-installed` with `--force-reinstall`. Re-run the isolated contract and confirm it passes.

- [x] **Step 4: Verify the real container build and commit**

```bash
docker build --build-arg LITE_BUILD=true -t podly-storage-cleanup-baseline:local .
git add Dockerfile src/tests/test_container_build_contracts.py
git commit -m "fix: replace packaged pip cleanly in containers"
```

Expected: the build completes through dependency installation, `pip check`, frontend compilation, and final image export.

---

### Task 1: Add the nullable per-feed retention policy

**Files:**
- Modify: `src/app/models.py`
- Create: `src/migrations/versions/s5t6u7v8w9x0_add_feed_processed_episode_retention_count.py`
- Create: `src/tests/test_feed_cleanup_policy_migration.py`
- Modify: `src/tests/test_feeds.py`

- [ ] **Step 1: Write failing model and migration tests**

Add tests proving:

- `Feed.processed_episode_retention_count` defaults to `None`.
- The migration upgrades a database stamped at `r4s5t6u7v8w9` with a nullable integer column.
- Existing feed rows retain `NULL` and therefore inherit the global policy.
- Downgrade removes only the new column.

Run:

```bash
pipenv run pytest src/tests/test_feed_cleanup_policy_migration.py src/tests/test_feeds.py -q
```

Expected: FAIL because the model and migration do not exist.

- [ ] **Step 2: Add the model column and focused migration**

Add a nullable `db.Integer` on `Feed`. Create revision `s5t6u7v8w9x0` with `down_revision = "r4s5t6u7v8w9"`; upgrade adds the nullable column and downgrade removes it. Do not touch existing production rows or unrelated schema.

- [ ] **Step 3: Run the focused tests and migration graph check**

```bash
pipenv run pytest src/tests/test_feed_cleanup_policy_migration.py src/tests/test_feeds.py -q
podly_migration_tmp="$(mktemp -d)"
PODLY_INSTANCE_DIR="$podly_migration_tmp" \
PODLY_PODCAST_DATA_DIR="$podly_migration_tmp/data" \
PODLY_DISABLE_SCHEDULER=1 \
pipenv run flask db heads
```

Expected: PASS and one head, `s5t6u7v8w9x0`.

- [ ] **Step 4: Commit**

```bash
git add src/app/models.py src/migrations/versions/s5t6u7v8w9x0_add_feed_processed_episode_retention_count.py src/tests/test_feed_cleanup_policy_migration.py src/tests/test_feeds.py
git commit -m "feat: add per-feed processed episode retention policy"
```

---

### Task 2: Build safe episode-artifact reconciliation primitives

**Files:**
- Create: `src/app/storage_cleanup.py`
- Modify: `src/app/jobs_manager_run_service.py`
- Replace/modify: `src/app/post_cleanup.py`
- Rewrite/extend: `src/tests/test_post_cleanup.py`
- Modify: `src/tests/test_jobs_manager_history.py`

- [ ] **Step 1: Write failing tests for candidate ordering and eligibility**

Cover real database rows for:

- A count policy keeps exactly the newest `N` posts that currently have a non-empty processed-audio path.
- Ordering is `Post.release_date DESC NULLS LAST`, then `Post.id DESC`.
- Count selection is provisional, filesystem existence is reconciled, and ranking is recomputed from valid processed artifacts before final cleanup candidates are chosen.
- A feed with a non-null count override is excluded from global-age selection.
- A feed with `NULL` inherits the global age policy.
- Global age disabled (`None`) still permits count-based selection.
- Global age uses the newer of the latest attributable successful-job completion and contained processed-file mtime, and conservatively skips when neither timestamp is trustworthy.
- `0`, negative values, booleans, non-integers, and overflow values are never accepted as stored policy inputs.

Run:

```bash
pipenv run pytest src/tests/test_post_cleanup.py -q
```

Expected: FAIL because the storage coordinator is absent and the legacy routine deletes `Post` rows.

- [ ] **Step 2: Implement selection and a structured result**

In `storage_cleanup.py`, introduce a result dataclass with requested/selected/cleaned/skipped/failed counters, warning details, file/attempt counts, reclaimed bytes, unsafe/grace skips, trigger, scope, and evaluated-policy details. Implement deterministic selectors without mutating data. Keep `post_cleanup.py` as a compatibility entry point that delegates to the new coordinator; remove its post-deletion behavior.

- [ ] **Step 3: Write failing tests for successful artifact cleanup**

For an eligible post, prove cleanup:

- preserves `Feed`, `Post`, whitelist state, enclosure/download URL, release metadata, and subscription data;
- deletes processed and unprocessed files only after path containment checks;
- clears both audio path columns after successful deletion or confirmed absence;
- deletes transcript segments, identifications, model calls, processing statistics, and correctly attributable terminal processing jobs;
- clears `Post.refined_ad_boundaries`, `refined_ad_boundaries_updated_at`, and `processed_with_preset_id`;
- leaves the episode able to enter the ordinary Process/Reprocess path again.

- [ ] **Step 4: Implement transactional reconciliation**

Add helpers that first resolve and validate allowed roots (`get_in_root()` and `get_srv_root()`), reject symlinks/path escapes, attempt filesystem deletion, and only clear each database pointer when the file was removed or already absent. Implement the count-policy two-phase reconciliation exactly: provisionally rank non-empty paths, reconcile artifact existence, recompute retained/candidate positions from valid outputs, then mutate. Commit database-derived cleanup together; on database failure, roll back and report a retryable partial state. Never delete the `Post`.

- [ ] **Step 5: Write failing tests for shared GUIDs, active work, and partial failure**

Cover:

- Any pending/running job sharing the GUID skips cleanup, including a non-null job belonging to another feed.
- Any active same-GUID legacy job with `feed_id IS NULL` conservatively skips cleanup.
- Terminal jobs with `feed_id` are deleted only for the target feed.
- A legacy null-feed job is deleted only when the GUID maps to exactly one post across all feeds.
- Ambiguous legacy jobs are preserved and logged.
- A file unlink error preserves that path and does not falsely report a clean episode.
- A missing input with valid processed output clears only the input pointer.
- A cleanup-eligible missing processed output clears stale derived data and makes the post reprocessable.
- A provisionally retained count item whose processed output is missing is removed from the retained ranking, but its input and processing data remain unless it becomes cleanup-eligible after recomputation.
- A missing processed output under a disabled policy preserves input and processing data while reporting reconciliation drift.

- [ ] **Step 6: Implement job attribution and affected-run counter repair**

Add a jobs-manager helper that recalculates every explicit affected `JobsManagerRun` ID as well as the singleton when attributable job rows are removed. Preserve ambiguous rows. Keep active rows untouched.

- [ ] **Step 7: Emit and test one structured summary per run**

At coordinator completion, log one JSON-serializable summary containing trigger, scope, policies evaluated, candidates selected, episodes cleaned, active/ambiguous/unsafe/grace skips, files removed, stale attempts removed, reclaimed bytes, warnings, and errors. Add log-capture tests for scheduled, feed-scoped, and partial-failure runs; do not rely on scattered per-file log lines as the run summary.

- [ ] **Step 8: Run focused tests and commit**

```bash
pipenv run pytest src/tests/test_post_cleanup.py src/tests/test_jobs_manager_history.py -q
git add src/app/storage_cleanup.py src/app/post_cleanup.py src/app/jobs_manager_run_service.py src/tests/test_post_cleanup.py src/tests/test_jobs_manager_history.py
git commit -m "feat: reconcile processed episode storage safely"
```

---

### Task 3: Add contained orphan-attempt maintenance

**Files:**
- Modify: `src/app/storage_cleanup.py`
- Modify: `src/tests/test_post_cleanup.py`
- Modify: `src/shared/processing_paths.py` only if a path helper is needed

- [ ] **Step 1: Write failing filesystem tests**

Using `PODLY_PODCAST_DATA_DIR` and temporary directories, cover:

- Only `data/in/jobs/<guid>/<job-id>` attempt directories are considered.
- Pending/running attempts and entries newer than 24 hours are preserved.
- Failed/cancelled/jobless attempts older than 24 hours are removed when no valid processed output depends on their input.
- A valid processed output preserves the currently referenced input.
- A stale failed/cancelled final referenced attempt without processed output may be removed and clears `Post.unprocessed_audio_path`.
- Unknown files outside the attempt layout, symlinks, path escapes, ambiguous GUID mappings, and active same-GUID work are preserved and warned.
- Empty parent directories are removed only inside the contained jobs root.

Run and observe expected failures:

```bash
pipenv run pytest src/tests/test_post_cleanup.py -k orphan -q
```

- [ ] **Step 2: Implement the 24-hour orphan sweep**

Walk only immediate GUID/job directories below the resolved jobs root. Use database job status plus post references to decide eligibility. Apply the same containment, symlink, ambiguity, and partial-failure rules as episode cleanup. Return orphan counts and warnings through the shared result object.

- [ ] **Step 3: Verify and commit**

```bash
pipenv run pytest src/tests/test_post_cleanup.py -q
git add src/app/storage_cleanup.py src/shared/processing_paths.py src/tests/test_post_cleanup.py
git commit -m "feat: clean stale processing attempt artifacts"
```

---

### Task 4: Schedule daily maintenance and coalesce immediate runs

**Files:**
- Modify: `src/app/background.py`
- Modify: `src/app/post_cleanup.py`
- Modify: `src/app/__init__.py`
- Create: `src/tests/test_storage_cleanup_scheduler.py`

- [ ] **Step 1: Write failing scheduler/dispatcher tests**

Prove:

- The daily `storage_cleanup` job exists even when global age retention is `None` or disabled.
- The scheduled entry point reads the current runtime retention at execution time.
- `PODLY_DISABLE_SCHEDULER=1` prevents both scheduled and immediate jobs.
- A feed-scoped immediate request returns `queued`; another feed request while pending returns `coalesced` and the worker receives the union of feed IDs.
- A global/manual request while feed scopes are pending returns `coalesced` and escalates the worker scope to server-wide.
- A feed request coalesced into an already server-wide run remains server-wide.
- Exceptions are logged and do not kill APScheduler.

Run:

```bash
pipenv run pytest src/tests/test_storage_cleanup_scheduler.py -q
```

Expected: FAIL because the legacy scheduler removes cleanup entirely when global age is disabled.

- [ ] **Step 2: Implement the always-on maintenance schedule and dispatcher**

Rename the scheduled job ID to an unambiguous storage-maintenance ID, keep the 24-hour interval and coalescing, and make global age merely one selector input. Add a fixed-ID immediate APScheduler date job plus a process-local locked accumulator that merges feed IDs and escalates to server-wide for global/manual requests. Atomically drain scope when execution begins. Map an existing pending job to `coalesced` and a disabled scheduler to `scheduler_disabled`.

- [ ] **Step 3: Verify and commit**

```bash
pipenv run pytest src/tests/test_storage_cleanup_scheduler.py src/tests/test_post_cleanup.py -q
git add src/app/background.py src/app/post_cleanup.py src/app/__init__.py src/tests/test_storage_cleanup_scheduler.py
git commit -m "feat: schedule storage maintenance independently of age policy"
```

---

### Task 5: Add admin cleanup APIs and response contracts

**Files:**
- Modify: `src/app/routes/feed_routes.py`
- Modify: `src/app/routes/config_routes.py`
- Modify: `src/app/config_store.py`
- Create: `src/tests/test_storage_cleanup_routes.py`
- Modify: `src/tests/test_admin_routes.py`

- [ ] **Step 1: Write failing authorization, validation, and response tests**

Test all three endpoints with auth disabled, anonymous, regular-user, admin, missing feed, malformed JSON, `true`, zero, negative, float/string, excessive integer, valid positive integer, and `null`:

- `POST /api/feeds/<feed_id>/cleanup-policy`
- `POST /api/admin/storage-cleanup/run`
- `PUT /api/config` when global retention changes

Assert:

- admin-only behavior follows the existing `_require_admin()` contract;
- the feed policy route returns 202 with the stored nullable value, effective policy summary, and cleanup dispatch status;
- a valid save commits before enqueueing cleanup;
- clearing an override queues feed-scoped immediate cleanup so the newly inherited global rule is enforced;
- manual run returns 202 and `queued`, `coalesced`, or `scheduler_disabled`;
- `PUT /api/config` returns `{config, cleanup_dispatch}` and requests server-wide cleanup for every changed positive global day count, including increases;
- unrelated config saves return `not_requested`.

Run:

```bash
pipenv run pytest src/tests/test_storage_cleanup_routes.py src/tests/test_admin_routes.py -q
```

- [ ] **Step 2: Serialize feed policy data**

Add `processed_episode_retention_count` and an `effective_cleanup_policy` object to `/feeds` responses. The effective object must state either per-feed count, inherited global age, or disabled age while explaining that orphan maintenance remains active.

- [ ] **Step 3: Implement feed policy and manual-run endpoints**

Parse JSON strictly so Python booleans do not pass as integers. Bound positive counts to a documented safe maximum. Commit the policy first, then request a coalesced feed-scoped sweep for both positive-count saves and `null`/inherit saves. Return 202 because cleanup is asynchronous.

- [ ] **Step 4: Refactor config update metadata without changing unrelated persistence**

Make the app-settings update report old/new retention to the route. Preserve the existing runtime hydration and secret sanitation. Return the new response envelope and dispatch server-wide whenever the changed new value is positive, whether the day count increases or decreases; disabling positive-to-null must explicitly report `requested: false`, `status: "not_requested"`.

- [ ] **Step 5: Verify and commit**

```bash
pipenv run pytest src/tests/test_storage_cleanup_routes.py src/tests/test_admin_routes.py src/tests/test_post_cleanup.py -q
git add src/app/routes/feed_routes.py src/app/routes/config_routes.py src/app/config_store.py src/tests/test_storage_cleanup_routes.py src/tests/test_admin_routes.py
git commit -m "feat: expose admin storage cleanup controls"
```

---

### Task 6: Make global cleanup visible in Settings

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/pages/ConfigPage.tsx`
- Create: `frontend/src/storageCleanup.ts`
- Create: `frontend/src/storageCleanup.test.ts`

- [ ] **Step 1: Write failing frontend contract tests**

Test pure helpers for:

- converting the “Enable global age cleanup” toggle plus day input to `number | null`;
- rejecting enabled cleanup with a non-positive/invalid day count;
- rendering queued/coalesced/disabled/not-requested dispatch messages;
- describing that per-feed policies and orphan maintenance continue when global age is off.

Run:

```bash
cd frontend
npm test -- storageCleanup.test.ts
```

Expected: FAIL because the helpers and response types do not exist.

- [ ] **Step 2: Add API types and client methods**

Add `CleanupDispatch`, the new config-update envelope, feed effective-policy types, `feedsApi.setCleanupPolicy()`, and `configApi.runStorageCleanup()`. Update existing config-save callers to consume `response.config` and show dispatch feedback without breaking secret previews or env override behavior.

- [ ] **Step 3: Build the dedicated “Storage & Cleanup” section**

Remove the buried generic “Cleanup Retention (days)” field from App. Add a clearly titled admin section with:

- “Enable global age cleanup” checkbox;
- positive “Delete processed episode files older than … days” input shown/enabled with the toggle;
- copy explaining inheritance, metadata preservation, per-feed count overrides, and orphan maintenance;
- “Run cleanup now” button with pending state and result toast.

- [ ] **Step 4: Verify and commit**

```bash
cd frontend
npm test -- storageCleanup.test.ts
npm run lint -- --max-warnings=0
npm run build
cd ..
git add frontend/src/types/index.ts frontend/src/services/api.ts frontend/src/pages/ConfigPage.tsx frontend/src/storageCleanup.ts frontend/src/storageCleanup.test.ts
git commit -m "feat: add global storage cleanup settings"
```

---

### Task 7: Add the per-feed cleanup policy modal

**Files:**
- Create: `frontend/src/components/FeedCleanupPolicyModal.tsx`
- Create: `frontend/src/feedCleanupPolicy.ts`
- Create: `frontend/src/feedCleanupPolicy.test.ts`
- Modify: `frontend/src/pages/FeedDetailView.tsx`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Write failing policy-view-model tests**

Test:

- `null` means inherit the current global age rule;
- a positive count means keep newest `N` successfully processed episodes;
- invalid count input blocks submission;
- cleanup dispatch results map to clear success/warning copy;
- inherited global-disabled state is distinguishable from per-feed cleanup disabled.

Run:

```bash
cd frontend
npm test -- feedCleanupPolicy.test.ts
```

- [ ] **Step 2: Implement an admin-only portal modal**

Use `createPortal(..., document.body)`. Add an admin-only “Storage cleanup” item in the show Settings menu. The modal must:

- show feed title and current effective policy;
- choose “Inherit global policy” or “Keep newest processed episodes”;
- accept only a positive integer for count mode;
- explain release-date ordering and metadata preservation;
- save via the 202 endpoint, close on success, invalidate the feeds query, and report queued/coalesced/scheduler-disabled state.

Use `user?.role === "admin"`; regular users must not see the menu item, while backend authorization remains authoritative.

- [ ] **Step 3: Verify and commit**

```bash
cd frontend
npm test -- feedCleanupPolicy.test.ts storageCleanup.test.ts
npm run lint -- --max-warnings=0
npm run build
cd ..
git add frontend/src/components/FeedCleanupPolicyModal.tsx frontend/src/feedCleanupPolicy.ts frontend/src/feedCleanupPolicy.test.ts frontend/src/pages/FeedDetailView.tsx frontend/src/types/index.ts frontend/src/services/api.ts
git commit -m "feat: add per-feed storage cleanup controls"
```

---

### Task 8: Update operator and user documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/RELEASE_RUNBOOK.md`
- Create or modify relevant screenshot/help copy only if the existing docs use it

- [ ] **Step 1: Document actual behavior**

Describe:

- Settings → Storage & Cleanup global age control;
- Podcasts → Show Settings → Storage cleanup per-feed count override;
- null/inherit semantics and release-date ordering;
- metadata preservation and reprocessing behavior;
- 24-hour orphan-attempt maintenance;
- daily maintenance remaining active with global age off;
- new migration head `s5t6u7v8w9x0`.

- [ ] **Step 2: Update documentation contract tests if needed**

Run:

```bash
pipenv run pytest src/tests/test_container_build_contracts.py -q
rg -n "Cleanup Retention \(days\)|processed files are automatically deleted after 14 days" README.md AGENTS.md docs frontend/src
```

Expected: no stale user-facing description of the old destructive or hidden behavior.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md README.md docs/ARCHITECTURE.md docs/RELEASE_RUNBOOK.md src/tests/test_container_build_contracts.py
git commit -m "docs: explain storage cleanup policies"
```

---

### Task 9: Run release-grade verification

**Files:**
- Verify all changed files
- Modify only defects revealed by failing checks, using a fresh red/green cycle

- [ ] **Step 1: Backend and migration verification**

```bash
pipenv run pytest --disable-warnings
pipenv run python -m pip check
podly_release_tmp="$(mktemp -d)"
PODLY_INSTANCE_DIR="$podly_release_tmp" \
PODLY_PODCAST_DATA_DIR="$podly_release_tmp/data" \
PODLY_DISABLE_SCHEDULER=1 \
pipenv run flask db heads
```

Create one explicit temporary instance directory, point `PODLY_INSTANCE_DIR` and `PODLY_PODCAST_DATA_DIR` below that directory, set `PODLY_DISABLE_SCHEDULER=1`, then run every `flask db stamp/upgrade/current` command in that environment. Podly derives the SQLite URI from `PODLY_INSTANCE_DIR`. Seed the disposable database at the previous head with representative feeds/posts/jobs, upgrade it, run cleanup, and prove metadata remains while eligible artifacts are removed. Never run Flask migration commands against the worktree default `src/instance/sqlite3.db` or production data.

- [ ] **Step 2: Frontend verification**

```bash
cd frontend
npm ci
npm test
npm run lint -- --max-warnings=0
npm run build
npm audit --audit-level=high
cd ..
```

- [ ] **Step 3: Production-container verification**

```bash
docker build --build-arg LITE_BUILD=true -t podly-storage-cleanup-candidate:local .
docker run --rm --entrypoint python3 podly-storage-cleanup-candidate:local -m pip check
```

Start the candidate against a brand-new disposable instance directory, wait for `/api/health`, verify the migration head, exercise authenticated global/per-feed saves, create disposable artifact fixtures through test setup, run cleanup, and confirm UI/API behavior. Never mount `src/instance/sqlite3.db` or any production data.

- [ ] **Step 4: Independent code review**

Use `superpowers:requesting-code-review`. Resolve every correctness issue with targeted tests. Re-run the affected suite after each fix and the full release gates afterward.

- [ ] **Step 5: Commit verification-only fixes and confirm clean tree**

```bash
git status --short
git log --oneline main..HEAD
```

Expected: clean tree and only scoped feature/build commits.

---

### Task 10: Integrate, publish, and verify the immutable release

**Files:**
- Follow: `docs/RELEASE_RUNBOOK.md`
- Do not edit release artifacts manually unless a verified workflow defect requires it

- [ ] **Step 1: Finish the development branch**

Use `superpowers:finishing-a-development-branch`. Because the user requested production deployment, integrate the verified branch into `main` without rewriting unrelated history. Confirm local `main` is current and clean first.

- [ ] **Step 2: Push and watch all acceptance workflows**

Push `main`, record the exact commit SHA, and use GitHub workflow status/logs to wait for backend acceptance, frontend gates, multi-platform build, candidate verification, and promotion. If semantic-release creates a `[skip ci]` release commit, follow the dispatched publication for that exact new `main` SHA.

- [ ] **Step 3: Verify registry identity**

Confirm:

- `ghcr.io/lukefind/podly-unicorn:sha-<full-main-sha>` exists and is immutable;
- `latest` resolves to the same digest;
- the manifest contains `linux/amd64` and `linux/arm64`;
- `org.opencontainers.image.revision` equals the deployed main SHA;
- an anonymous pull and health smoke test succeed.

Do not deploy an unverified or mismatched digest.

---

### Task 11: Back up and deploy to production host `big`

**Files/Systems:**
- Production SSH alias: `big`
- Production service/container: discover read-only before mutation; expected container name `podly-pure-podcasts`
- Follow: `docs/RELEASE_RUNBOOK.md`

- [ ] **Step 1: Restore and verify network reachability**

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 big 'hostname; id; docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}"'
```

Expected: successful read-only inventory. If the route remains `No route to host`, stop before production mutation and report the exact network blocker.

- [ ] **Step 2: Capture the current deployment and data mapping**

Resolve the compose directory, compose file, current image digest, container ID, health, bind-mounted instance path, environment-file path, and stable `PODLY_SECRET_KEY` presence without printing secrets. Confirm the database is `/app/src/instance/sqlite3.db` inside the container.

- [ ] **Step 3: Create rollback tag and consistent predeploy backup**

Follow the runbook to:

- record the currently deployed digest and configuration checksum;
- tag the running image with a local rollback tag;
- stop the service for a consistent `src/instance` archive;
- verify the archive is non-empty and contains the SQLite database;
- restart the old service if any predeploy verification fails.

- [ ] **Step 4: Pull the verified digest and deploy**

Deploy only the digest verified in Task 10. Preserve the existing env file, compose overrides, bind mounts, and `PODLY_SECRET_KEY`. Let startup apply migration `s5t6u7v8w9x0` automatically.

- [ ] **Step 5: Run production acceptance**

Verify:

- container health and startup logs contain no migration/scheduler errors;
- database Alembic version is `s5t6u7v8w9x0` through a read-only Python query inside the container;
- Settings shows the dedicated Storage & Cleanup controls;
- an admin can save global age cleanup and receive a dispatch status;
- a feed’s Show Settings contains the per-feed policy modal;
- saving a conservative test policy queues cleanup and preserves episode rows;
- scheduler lists daily storage maintenance even if global age is disabled;
- existing RSS/download/process flows still work.

Do not inspect or mutate production rows directly beyond the application-supported settings/actions and the read-only migration/version checks.

- [ ] **Step 6: Roll back on any failed gate**

If health, migration, UI, or data-preservation checks fail, follow the runbook: stop the candidate, restore the predeploy instance archive if migration occurred, redeploy the recorded rollback image/config, and verify health before reporting.
