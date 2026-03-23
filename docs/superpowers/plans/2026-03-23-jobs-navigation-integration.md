# Jobs Navigation Integration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Jobs overview the canonical `/jobs` entry point, move the list view under `/jobs/history`, and improve discovery from the main dashboard.

**Architecture:** Repoint the route tree so the existing analytics page becomes the Jobs section root, keep the existing list page as a history subpage, and use the dashboard home page as an entry point into that section. No backend work is required because the needed jobs data APIs already exist.

**Tech Stack:** React 19, React Router 7, TypeScript, TanStack Query, Vite

---

### Task 1: Document the new Jobs route structure

**Files:**
- Create: `docs/superpowers/specs/2026-03-23-jobs-navigation-design.md`
- Create: `docs/superpowers/plans/2026-03-23-jobs-navigation-integration.md`

- [x] **Step 1: Write the approved design and implementation plan**

Record the canonical route map:
- `/jobs` -> Jobs overview
- `/jobs/history` -> Jobs history list
- `/jobs/dashboard` -> redirect to `/jobs`

- [ ] **Step 2: Keep this plan updated while implementing**
- [x] **Step 2: Keep this plan updated while implementing**

Mark completed items as the work lands.

### Task 2: Repoint the Jobs routes

**Files:**
- Modify: `frontend/src/App.tsx`

- [x] **Step 1: Change the canonical Jobs routes**

Update the router so:
- `/jobs` renders `JobsDashboardPage`
- `/jobs/history` renders `JobsPage`
- `/jobs/dashboard` redirects to `/jobs`

- [x] **Step 2: Keep the existing admin guard semantics**

Only expose the overview routes in the same contexts where the current dashboard route is allowed. Users without overview access should be redirected from `/jobs` to `/jobs/history`.

- [x] **Step 3: Build to validate route changes**

Run: `cd frontend && npm run build`
Expected: build succeeds without route/type errors

### Task 3: Make the Jobs overview read like the section root

**Files:**
- Modify: `frontend/src/pages/JobsDashboardPage.tsx`

- [x] **Step 1: Update the header and actions**

Make the page clearly read as the Jobs hub and point its secondary navigation to `/jobs/history`.

- [x] **Step 2: Keep the current analytics content intact**

Do not reshape the metrics layout beyond the new positioning/copy needed for the hub role.

- [x] **Step 3: Rebuild after the page change**

Run: `cd frontend && npm run build`
Expected: build succeeds

### Task 4: Reframe the list page as history

**Files:**
- Modify: `frontend/src/pages/JobsPage.tsx`

- [x] **Step 1: Update the page title and descriptive copy**

Make it clear this page is the detailed Jobs history/list view rather than the main Jobs landing page.

- [x] **Step 2: Update navigation controls**

Replace the old dashboard button target with `/jobs` and keep the history actions usable.

- [x] **Step 3: Rebuild after the history-page change**

Run: `cd frontend && npm run build`
Expected: build succeeds

### Task 5: Improve Jobs discoverability from the main dashboard

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx`

- [x] **Step 1: Promote the existing Jobs card into a clearer section entry point**

Keep the live active jobs preview, but add clearer Jobs-overview framing and a direct link to `/jobs`.

- [x] **Step 2: Add a secondary path to history**

Let users jump directly from the home dashboard into `/jobs/history` when they want the raw list.

- [x] **Step 3: Rebuild after the dashboard change**

Run: `cd frontend && npm run build`
Expected: build succeeds

### Task 6: Verify the finished flow

**Files:**
- Modify: `docs/superpowers/plans/2026-03-23-jobs-navigation-integration.md`

- [x] **Step 1: Run the final frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds
Result: passed

- [x] **Step 2: Smoke-check the route flow in the browser**

Verify:
- `/jobs` loads the overview
- `/jobs/history` loads the list
- `/jobs/dashboard` redirects to `/jobs`
- the home dashboard Jobs card links to the new overview and history
Result: confirmed with a local Vite smoke check

- [x] **Step 3: Do a final code review**

Review for routing regressions, broken links, and misleading copy.
