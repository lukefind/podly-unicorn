# Refresh and Processing Resilience Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep background feed refreshes live when an upstream host stalls, retry transient episode downloads safely, expose scheduler liveness through Docker health, and correct `user_download.post_id` nullability without losing production data.

**Architecture:** Bound RSS network access before parsing, retain the sequential per-feed loop, and guard refresh-all with a process-wide non-blocking lock plus a thread-safe health snapshot. Retry only transient audio failures while writing to an atomic partial file. Correct the already-declared nullable model with a focused Alembic batch migration.

**Tech Stack:** Python 3.12, Flask, Requests, feedparser, APScheduler, SQLAlchemy/Alembic, SQLite, pytest, Docker Compose.

**Design spec:** `docs/superpowers/specs/2026-07-20-refresh-processing-resilience-design.md`

---

## File map

- Modify `src/app/feeds.py`: bounded RSS HTTP retrieval and byte parsing.
- Modify `src/tests/test_feeds.py`: RSS timeout, status, final-URL, and byte-parsing regressions.
- Modify `src/podcast_processor/podcast_downloader.py`: transient retries, backoff, and atomic partial-file handling.
- Modify `src/tests/test_podcast_downloader.py`: retry classification and partial-file regressions.
- Create `src/app/refresh_health.py`: refresh-all lock and sanitized liveness state.
- Modify `src/app/jobs_manager.py`: integrate refresh lifecycle, overlap prevention, and per-feed error tracking.
- Create `src/app/routes/health_routes.py`: public `/health` JSON endpoint.
- Modify `src/app/routes/__init__.py`: register health before the SPA catch-all.
- Create `src/tests/test_refresh_health.py`: state, overlap, staleness, log de-duplication, and response sanitization tests.
- Modify `compose.yml`: point Docker healthcheck at `/health`.
- Create `compose.production-health.yml`: minimal deploy-time override for servers whose base checkout must remain untouched.
- Create `src/migrations/versions/r3s4t5u6v7w8_make_user_download_post_id_nullable.py`: corrective SQLite-safe migration.
- Create `src/tests/test_user_download_nullable_migration.py`: real SQLite upgrade/downgrade/data-preservation tests.

### Task 1: Bound RSS retrieval

**Files:**
- Modify: `src/tests/test_feeds.py`
- Modify: `src/app/feeds.py:297-302`

- [ ] **Step 1: Write the failing RSS retrieval tests**

Replace the existing URL-parser assertion with tests that patch `app.feeds.requests.get` and assert:

```python
response.content = b"<rss>...</rss>"
response.url = "https://cdn.example.com/final.xml"
result = fetch_feed("https://example.com/feed.xml")
mock_get.assert_called_once_with(
    "https://example.com/feed.xml",
    headers={"User-Agent": feedparser.USER_AGENT},
    timeout=(10, 30),
)
mock_parse.assert_called_once_with(response.content)
response.raise_for_status.assert_called_once_with()
assert result.href == response.url
```

Add a second test proving an HTTP error propagates and `feedparser.parse` is not called.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_feeds.py -k fetch_feed
```

Expected: failures show the current implementation calls `feedparser.parse(url)` and never calls Requests.

- [ ] **Step 3: Implement minimal bounded retrieval**

Import Requests, call `requests.get()` with `(10, 30)`, call `raise_for_status()`, parse `response.content`, and preserve `response.url` as `feed_data.href`. Keep GUID normalization unchanged.

- [ ] **Step 4: Run targeted feed tests and verify GREEN**

Run the command from Step 2, then:

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_feeds.py src/tests/test_job_triggers.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the bounded RSS change**

```bash
git add src/app/feeds.py src/tests/test_feeds.py
git commit -m "fix: bound background feed retrieval"
```

### Task 2: Retry transient audio downloads safely

**Files:**
- Modify: `src/tests/test_podcast_downloader.py`
- Modify: `src/podcast_processor/podcast_downloader.py:29-115`

- [ ] **Step 1: Write failing retry and atomic-file tests**

Add focused tests for:

- a `requests.ReadTimeout` followed by a 200 response makes two calls and returns the completed file;
- three transient failures raise `DownloadError` and leave neither destination nor `.part` file;
- HTTP 503 retries, while HTTP 404 does not;
- an exception from `iter_content()` removes the partial file;
- success calls `os.replace(part_path, destination)` and exposes only complete bytes.

Patch `time.sleep` so tests assert one- and two-second backoffs without waiting. Update existing call assertions to require `timeout=(10, 60)`.

- [ ] **Step 2: Run downloader tests and verify RED**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_podcast_downloader.py
```

Expected: new tests fail because only one direct-to-destination attempt exists.

- [ ] **Step 3: Implement the minimal retry loop**

Use three total attempts. Retry `requests.Timeout`, `requests.ConnectionError`, HTTP 429, and HTTP 5xx. Sleep one second then two seconds between retryable failures. Keep other 4xx failures immediate and retain the Podtrac 403 error.

For every attempt, remove a stale sibling `<destination>.part`, stream into it, then use `os.replace()` after the response completes. Remove the partial file on every exception before retrying or raising. Wrap exhausted request exceptions in `DownloadError` without embedding credentials or tokens.

- [ ] **Step 4: Run downloader tests and verify GREEN**

Run the command from Step 2. Expected: all downloader tests pass with no real sleeps.

- [ ] **Step 5: Commit downloader resilience**

```bash
git add src/podcast_processor/podcast_downloader.py src/tests/test_podcast_downloader.py
git commit -m "fix: retry transient podcast downloads"
```

### Task 3: Track refresh liveness and expose Docker health

**Files:**
- Create: `src/tests/test_refresh_health.py`
- Create: `src/app/refresh_health.py`
- Modify: `src/app/jobs_manager.py:498-530`
- Create: `src/app/routes/health_routes.py`
- Modify: `src/app/routes/__init__.py`
- Modify: `compose.yml:27-38`
- Create: `compose.production-health.yml`

- [ ] **Step 1: Write failing unit tests for the health tracker**

Define the wished-for API around a fresh `RefreshHealth` instance:

```python
assert tracker.try_start(now) is True
tracker.set_current_feed(13)
tracker.record_feed_error(13, requests.ReadTimeout("secret https://host/?token=x"))
snapshot = tracker.snapshot(now + timedelta(minutes=16))
assert snapshot["status"] == "stale"
assert snapshot["last_error"] == "feed_13:ReadTimeout"
assert "https://" not in json.dumps(snapshot)
```

Verify a second `try_start()` returns false without modifying the active start/current-feed state, `finish(completed=True)` sets `last_completed_at`, `finish(completed=False)` does not, and stale logging occurs once per cycle.

- [ ] **Step 2: Write failing route and manager integration tests**

Register `health_bp` on a small Flask app and assert `/health` returns 200 for idle state and 503 for stale state using exactly these fields: `status`, `refresh_running`, `refresh_started_at`, `current_feed_id`, `last_completed_at`, `last_error`, and `stale_after_seconds`.

Patch the module-level tracker in `app.jobs_manager` and assert an overlapping `start_refresh_all_feeds()` returns `{"status": "already_running", ...}` without querying feeds. Assert normal completion calls `finish(completed=True)` and a cycle-level exception calls `finish(completed=False)`.

- [ ] **Step 3: Run health tests and verify RED**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_refresh_health.py
```

Expected: import or API failures because the tracker and route do not exist.

- [ ] **Step 4: Implement thread-safe state and integration**

Create `RefreshHealth` with a state `Lock`, a separate non-blocking cycle `Lock`, a 900-second stale threshold, UTC-naive internal datetimes, ISO-8601 UTC serialization, and a per-cycle stale-log flag. Store only `feed_<id>:<ExceptionClass>` in public state.

Wrap `JobsManager.start_refresh_all_feeds()` so it:

1. returns `already_running` when `try_start()` fails;
2. updates the current feed before each fetch;
3. records sanitized per-feed errors while retaining the full private log;
4. calls `finish(completed=True)` only after cleanup and enqueueing complete;
5. calls `finish(completed=False)` and releases the lock for cycle-level failures.

Register a `/health` blueprint before `main_bp`. Change Compose healthcheck to `urllib.request.urlopen('http://127.0.0.1:5001/health')`. Add a minimal `compose.production-health.yml` containing only the `podly.healthcheck` override with that same command; this file allows deployment to layer the healthcheck over an untouched server checkout.

- [ ] **Step 5: Run health and scheduler tests and verify GREEN**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_refresh_health.py src/tests/test_job_triggers.py src/tests/test_jobs_manager_history.py
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit health monitoring**

```bash
git add src/app/refresh_health.py src/app/jobs_manager.py src/app/routes/health_routes.py src/app/routes/__init__.py src/tests/test_refresh_health.py compose.yml compose.production-health.yml
git commit -m "feat: expose background refresh health"
```

### Task 4: Correct `user_download.post_id` nullability

**Files:**
- Create: `src/tests/test_user_download_nullable_migration.py`
- Create: `src/migrations/versions/r3s4t5u6v7w8_make_user_download_post_id_nullable.py`

- [ ] **Step 1: Write real-SQLite migration tests**

Create a temporary representative SQLite schema containing `users`, `feed`, `post`, and `user_download`. Define the production-relevant foreign keys from `user_download.user_id`, `post_id`, and `feed_id`, plus `ix_user_download_post_id`, `ix_user_download_feed_id`, and `ix_user_download_user_date`. Load the migration module with `importlib`, bind an Alembic `Operations(MigrationContext.configure(connection))`, and replace the module's `op` during the test.

Assert:

- `upgrade()` changes `post_id` to `nullable=True`, preserves an existing row, and preserves all representative indexes and foreign keys;
- `downgrade()` restores `nullable=False` when no null rows exist and still preserves the indexes and foreign keys;
- after upgrade and insertion of an `RSS_READ` row with null `post_id`, `downgrade()` raises `RuntimeError`, leaves the row intact, and leaves the column nullable.

- [ ] **Step 2: Run migration tests and verify RED**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q src/tests/test_user_download_nullable_migration.py
```

Expected: import failure because revision `r3s4t5u6v7w8` does not exist.

- [ ] **Step 3: Implement the focused migration**

Set `revision = "r3s4t5u6v7w8"` and `down_revision = "p2q3r4s5t6u7"`. Inspect for table/column existence and current nullability so upgrade/downgrade are idempotent. Use `batch_op.alter_column("post_id", existing_type=sa.Integer(), nullable=True/False)`.

Before downgrade, count null `post_id` values. Raise a clear `RuntimeError` if any exist; do not delete or rewrite audit data.

- [ ] **Step 4: Run migration tests and verify GREEN**

Run the command from Step 2. Expected: all migration tests pass.

- [ ] **Step 5: Commit the corrective migration**

```bash
git add src/migrations/versions/r3s4t5u6v7w8_make_user_download_post_id_nullable.py src/tests/test_user_download_nullable_migration.py
git commit -m "fix: make user download post optional"
```

### Task 5: Verify the branch

**Files:** all changed files.

- [ ] **Step 1: Run focused regression tests**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q \
  src/tests/test_feeds.py \
  src/tests/test_job_triggers.py \
  src/tests/test_podcast_downloader.py \
  src/tests/test_refresh_health.py \
  src/tests/test_jobs_manager_history.py \
  src/tests/test_user_download_nullable_migration.py
```

Expected: zero failures.

- [ ] **Step 2: Run static checks**

```bash
git diff -z --name-only --diff-filter=ACMRT main...HEAD -- '*.py' \
  | PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 \
    xargs -0 pipenv run black --check
git diff -z --name-only --diff-filter=ACMRT main...HEAD -- '*.py' \
  | PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 \
    xargs -0 pipenv run isort --check-only
git diff --check main...HEAD
```

Expected: zero errors from the same Black and isort checks used by CI.

- [ ] **Step 3: Run the full suite with the known local FFmpeg failures excluded**

```bash
PIPENV_PIPFILE=Pipfile.lite PIPENV_VENV_IN_PROJECT=1 pipenv run pytest -q \
  --ignore=src/tests/test_process_audio.py
```

Expected baseline: the existing 176 tests plus the new regressions pass; the same 3 existing skips remain.

- [ ] **Step 4: Review branch scope**

```bash
git status --short
git log --oneline main..HEAD
git diff --stat main...HEAD
```

Expected: only the spec, plan, implementation, tests, Compose healthcheck, and migration are present.

### Task 6: Deploy safely to `big`

**Production actions:** back up the database, build the image, migrate, restart, and verify. Do not delete the backup.

- [ ] **Step 1: Record and validate current production state**

Over SSH, record:

- source repository: `/home/bob/podly-unicorn`;
- Compose file: `/home/bob/podly-unicorn/compose.yml`;
- deployed database bind mount: `/home/bob/podly-unicorn/src/instance/sqlite3.db` to `/app/src/instance/sqlite3.db`;
- current container image ID, health, Git commit, Alembic revision, schema nullability, and latest refresh logs.
- the resolved Compose build arguments for `BASE_IMAGE`, `CUDA_VERSION`, `USE_GPU`, `USE_GPU_NVIDIA`, `USE_GPU_AMD`, and `LITE_BUILD` from `docker compose config`.

Run `git status --short` in the server repository. The known unrelated entries (`.claude/settings.local.json`, `backup.env.local.bak`, and `src/instance/`) must remain untouched. If any tracked change overlaps files in this branch, abort deployment and report it rather than resetting, stashing, or overwriting.

- [ ] **Step 2: Create a timestamped database backup**

Use SQLite's online backup API from Python to copy `/home/bob/podly-unicorn/src/instance/sqlite3.db` to a timestamped file under `/home/bob/podly-unicorn/src/instance/backups/`. Run `PRAGMA integrity_check` against the backup and require `ok`. Record its size and SHA-256 digest, print and retain the exact backup path, and abort before stopping Podly if verification fails.

- [ ] **Step 3: Transfer the verified commit without touching the dirty server checkout**

Create a local Git bundle containing `main..staging/refresh-resilience` and copy it over the localhost SSH tunnel to a timestamped path under `/home/bob/`. On `big`, fetch that bundle into a dedicated deployment ref and create a detached worktree at `/home/bob/podly-build-refresh-resilience-<short-commit>`. Do not switch, reset, stash, clean, or edit `/home/bob/podly-unicorn`.

Build the detached worktree as `podly-pure-podcasts:<short-commit>` with every build argument recorded in Step 1 passed explicitly to `docker build`. For the currently observed production configuration, the resolved values are `BASE_IMAGE=python:3.12-slim`, `CUDA_VERSION=12.4.1`, `USE_GPU=false`, `USE_GPU_NVIDIA=false`, `USE_GPU_AMD=false`, and `LITE_BUILD=false`; abort and use the newly recorded values instead if the production configuration changes before deployment. Require a successful build and record the new image ID. Tag the currently deployed image as `podly-pure-podcasts:rollback-<timestamp>` before changing the `podly-pure-podcasts:latest` tag.

- [ ] **Step 4: Stop Podly, migrate exclusively, and start the new image**

From `/home/bob/podly-unicorn`, stop only the `podly` Compose service and confirm the container is no longer running. With the application stopped, run the new commit-specific image as a one-shot migration container with:

- `PODLY_DISABLE_SCHEDULER=1`;
- the existing `.env.local`;
- `/home/bob/podly-unicorn/src/instance:/app/src/instance`;
- `PYTHONPATH=/app/src flask --app app db upgrade`.

Verify `alembic_version = r3s4t5u6v7w8`, `post_id` is nullable, `PRAGMA integrity_check` is `ok`, and `PRAGMA foreign_key_check` returns no rows before tagging the new image as `podly-pure-podcasts:latest`.

Define the persistent deployment Compose command as:

```bash
docker compose \
  -f /home/bob/podly-unicorn/compose.yml \
  -f /home/bob/podly-build-refresh-resilience-<short-commit>/compose.production-health.yml
```

Use that exact layered configuration for forward-deployment stop, start, and inspection. Because relative paths resolve from the first Compose file, the service retains `/home/bob/podly-unicorn/src/instance` as its bind mount while the override activates the `/health` probe. Start with `up -d --no-build --force-recreate podly`. Retain the commit-specific deployment worktree and override as production artifacts while this image is deployed.

- [ ] **Step 5: Verify production behavior**

Confirm:

- Docker health becomes `healthy` using `/health`;
- `docker inspect` shows the active healthcheck command contains `/health`;
- `/health` returns sanitized JSON and HTTP 200;
- `PRAGMA table_info(user_download)` reports `post_id` nullable;
- a complete 23-feed scheduled cycle reaches and finishes feed 13 and all later feeds;
- no new `maximum number of running instances`, scheduler-stale, or uncaught refresh errors appear;
- a combined-feed poll records `RSS_READ` without an integrity error.

- [ ] **Step 6: Use the explicit rollback sequence if verification fails**

If migration or runtime verification fails:

1. stop only the `podly` service using the forward layered Compose command;
2. verify the recorded backup digest still matches;
3. use Python while Podly is stopped to copy the backup to a sibling temporary database file and atomically replace `/home/bob/podly-unicorn/src/instance/sqlite3.db`;
4. retag `podly-pure-podcasts:rollback-<timestamp>` as `podly-pure-podcasts:latest`;
5. recreate the old image with the original base command `docker compose -f /home/bob/podly-unicorn/compose.yml up -d --no-build --force-recreate podly`, restoring its compatible `/` healthcheck rather than the new `/health` override;
6. verify the old revision, database integrity, and container health.

Do not run a destructive Git cleanup and do not delete the database backup or rollback image. On success, report the deployed commit, prior and new image IDs, database backup path/digest, migration revision, container health, completed refresh-cycle timestamps, and any remaining warnings.
