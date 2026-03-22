# Jobs Analytics And Admin Tools Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve processing-job history across restarts, capture durable per-job analytics, finish the jobs dashboard, and complete transcript export plus database backup/restore tooling.

**Architecture:** Extend `processing_job` into the durable source of truth for per-run history by storing immutable snapshot data and processing metrics on each job row. Build dashboard aggregates from those persisted snapshots instead of live `post`/`processing_statistics` joins, then layer the jobs UI and admin export/maintenance tools on top of those stable APIs.

**Tech Stack:** Flask, SQLAlchemy, Alembic, React, TypeScript, React Query, Vite

---

### Task 1: Persist Durable Job History And Metrics

**Files:**
- Modify: `src/app/models.py`
- Modify: `src/app/__init__.py`
- Modify: `src/app/jobs_manager.py`
- Modify: `src/app/job_manager.py`
- Modify: `src/podcast_processor/processing_status_manager.py`
- Modify: `src/podcast_processor/podcast_processor.py`
- Create: `src/migrations/versions/p2q3r4s5t6u7_add_processing_job_history_metrics.py`
- Test: `src/tests/test_jobs_manager_history.py`

- [x] **Step 1: Write failing tests for history preservation and metric snapshots**

Add tests that prove:
- completed jobs survive restart recovery
- pending/running jobs are marked terminal on restart instead of being deleted
- completed jobs persist their own titles/feed data/ad-removal metrics even if post-level stats change later

- [x] **Step 2: Run the targeted tests to verify they fail for the expected reason**

Run: `pipenv run pytest -q src/tests/test_jobs_manager_history.py`
Expected: FAIL because restart recovery still deletes all jobs and `ProcessingJob` has no snapshot metric fields.

- [x] **Step 3: Add additive `processing_job` snapshot columns and migration**

Add nullable snapshot columns to `ProcessingJob` for:
- feed identity/display data
- post title
- ad-removal totals/percentages
- original/processed duration values

Create migration `src/migrations/versions/p2q3r4s5t6u7_add_processing_job_history_metrics.py` with `down_revision = "n1o2p3q4r5s6"`.

- [x] **Step 4: Replace startup job wiping with restart recovery**

Change startup handling in `src/app/__init__.py` and `src/app/jobs_manager.py` so startup preserves completed history and only converts interrupted active jobs into a terminal state with a clear error message.

- [x] **Step 5: Populate immutable job snapshots at creation/completion**

Capture feed/post snapshot data when the job is created and copy final processing statistics onto the same job row when processing completes.

- [x] **Step 6: Re-run the targeted tests**

Run: `pipenv run pytest -q src/tests/test_jobs_manager_history.py`
Expected: PASS.

### Task 2: Build Stable Backend Analytics APIs

**Files:**
- Modify: `src/app/routes/jobs_routes.py`
- Modify: `src/app/models.py` (only if helper properties/types become necessary)
- Test: `src/tests/test_jobs_routes.py`

- [x] **Step 1: Write failing API tests for the new analytics behavior**

Cover:
- `/api/jobs/dashboard` aggregates counts by period/status/trigger/user/feed
- dashboard performance metrics come from persisted job snapshots
- recent completed jobs expose completed timestamps, durations, and ad-removal details
- admin-only analytics behavior when auth is enabled

- [x] **Step 2: Run the targeted API tests to verify they fail**

Run: `pipenv run pytest -q src/tests/test_jobs_routes.py`
Expected: FAIL because the current route still depends on mutable `processing_statistics` joins and has no auth guard for user analytics.

- [x] **Step 3: Refactor `/api/jobs/dashboard` to read from durable job history**

Aggregate off `ProcessingJob` snapshot fields and timestamps, not live post statistics. Ensure the time-period filter is bounded and recent-completed rows include duration and ad-removal values directly from the job.

- [x] **Step 4: Tighten supporting jobs endpoints**

Make sure list/history payloads include the date/time and duration data needed by the frontend without extra client-side guesswork.

- [x] **Step 5: Re-run the targeted API tests**

Run: `pipenv run pytest -q src/tests/test_jobs_routes.py`
Expected: PASS.

### Task 3: Finish Jobs UI And Dashboard

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/JobsPage.tsx`
- Modify: `frontend/src/pages/JobsDashboardPage.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Optionally modify: `frontend/src/components/layout/Sidebar.tsx`

- [x] **Step 1: Write a failing frontend verification target**

Use the current build as the red check for the interrupted frontend work.

- [x] **Step 2: Run the frontend build to verify it currently fails**

Run: `cd frontend && npm run build`
Expected: FAIL with TypeScript errors from the partial dashboard implementation.

- [x] **Step 3: Fix types, route wiring, and dashboard/job-list rendering**

Implement:
- stable `JobsDashboard` type imports
- completed-at/date-time rendering in the job list
- dashboard cards/charts/tables wired to the new API contract
- routing/entry points so admins can reach the dashboard cleanly

- [x] **Step 4: Re-run the frontend build**

Run: `cd frontend && npm run build`
Expected: PASS.

### Task 4: Complete Transcript Export And Database Maintenance Tools

**Files:**
- Modify: `src/app/routes/admin_routes.py`
- Modify: `frontend/src/components/ProcessingStatsButton.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts` (if new admin response types are needed)
- Test: `src/tests/test_admin_routes.py`

- [x] **Step 1: Write failing tests for transcript export and backup/restore**

Cover:
- single transcript export in `json`, `txt`, and `srt`
- bulk transcript export returns a downloadable archive for the selected scope/format
- backup endpoint returns the SQLite file for admins
- restore rejects invalid uploads and reports a clear error

- [x] **Step 2: Run the targeted admin-route tests to verify they fail**

Run: `pipenv run pytest -q src/tests/test_admin_routes.py`
Expected: FAIL because bulk export is incomplete/inconsistent and the new routes are not fully covered.

- [x] **Step 3: Refactor transcript exports around shared formatting helpers**

Create shared transcript serialization helpers so single and bulk exports use the same content generation. Bulk export should return a consistent archive format suitable for offline analysis/refinement.

- [x] **Step 4: Finish the admin UI**

Implement:
- per-episode transcript export buttons using the shared API helper
- bulk transcript export controls in Settings
- backup/restore buttons wired through `adminApi` instead of ad hoc requests

- [x] **Step 5: Re-run the targeted admin-route tests and frontend build**

Run: `pipenv run pytest -q src/tests/test_admin_routes.py`
Expected: PASS.

Run: `cd frontend && npm run build`
Expected: PASS.

### Task 5: End-To-End Verification And Review

**Files:**
- Modify plan checkboxes in this file as tasks complete
- Review: working tree diff for all touched files

- [x] **Step 1: Run the focused backend regression suite**

Run: `pipenv run pytest -q src/tests/test_jobs_manager_history.py src/tests/test_jobs_routes.py src/tests/test_admin_routes.py src/tests/test_post_routes.py src/tests/test_post_cleanup.py src/tests/test_trigger_routes.py`
Expected: PASS.

- [x] **Step 2: Run the frontend build one more time**

Run: `cd frontend && npm run build`
Expected: PASS.

- [x] **Step 3: Perform a manual code review**

Review for:
- history persistence regressions
- incorrect aggregation from mutable post-level data
- unsafe restore behavior or missing admin guards
- missing type imports / route guards / UX dead ends

- [x] **Step 4: Summarize remaining risks**

Document any residual risk, especially around restore semantics, large bulk transcript exports, or analytics gaps for legacy jobs created before the new snapshot fields existed.
