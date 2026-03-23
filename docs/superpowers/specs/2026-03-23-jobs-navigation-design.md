# Jobs Navigation Design

## Summary

The Jobs area has outgrown its original structure. The analytics view is now the strategic entry point, but the application still treats the history list as the section root. This change makes the Jobs overview the primary destination, keeps history available as a subpage, and surfaces a clearer entry point from the main dashboard.

## Goals

- Make `/jobs` the canonical Jobs section landing page.
- Move the detailed list/history view to `/jobs/history`.
- Preserve existing external or bookmarked links to `/jobs/dashboard`.
- Improve discoverability of Jobs analytics from the main dashboard.
- Keep the existing permission model intact.

## Non-Goals

- No backend API changes.
- No redesign of the metrics themselves.
- No new subpages beyond the overview/history split.

## Information Architecture

### Canonical routes

- `/jobs` renders the Jobs overview page.
- `/jobs/history` renders the current list/history page.
- `/jobs/dashboard` redirects to `/jobs` for compatibility.

### Navigation model

- The sidebar `Jobs` item continues to point to `/jobs`.
- The overview page becomes the hub and includes a visible action to open `/jobs/history`.
- The history page includes a visible action back to `/jobs`.

## Main Dashboard Integration

The current dashboard already exposes active jobs, but it acts more like a live queue widget than a Jobs section entry point. That card should be promoted into a stronger Jobs summary card:

- Keep the live active-jobs preview.
- Add a compact summary line for the total active count.
- Add a direct call-to-action into the Jobs overview.
- Add a secondary action into history for users who want the raw list.

This keeps the home dashboard lightweight while making the Jobs section easier to discover and understand.

## Permission and Access Rules

- The canonical `/jobs` route should keep the same access behavior as the existing Jobs area.
- The Jobs overview remains admin-only when authentication is enabled, matching the current analytics access rule.
- The history page remains available under the existing Jobs page access rule.
- Users without overview access who hit `/jobs` should be redirected to `/jobs/history` so the sidebar link continues to work.
- The compatibility redirect from `/jobs/dashboard` should only exist where the overview route is already allowed.

## Implementation Notes

- Reuse the existing `JobsDashboardPage` component as the new `/jobs` page.
- Reuse the existing `JobsPage` component as `/jobs/history`.
- Implement the legacy `/jobs/dashboard` route as a client-side redirect with `Navigate`.
- Update copy in both jobs pages so the hierarchy is obvious.
- Update the main dashboard card so its links reflect the new structure.

## Verification

There is no frontend test harness in the repo today, so verification will rely on:

- TypeScript and production build success via `npm run build`
- Manual route smoke checks for `/jobs`, `/jobs/history`, and `/jobs/dashboard`
- Visual confirmation that the main dashboard links into the new Jobs overview correctly
