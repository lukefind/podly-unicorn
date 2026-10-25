# RSS Trigger Confirmation Implementation Plan

> **For agentic workers:** Execute directly unless the plan contains at least two genuinely independent tasks that qualify for superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent passive RSS link fetches from starting paid episode processing, preserve existing RSS URLs, and deploy the verified correction.

**Architecture:** GET and HEAD `/trigger` authenticate the existing feed capability and display status or an explicit confirmation form without starting jobs. Only POST `/trigger`, with the same authenticated capability and a short-lived signed confirmation bound to the feed token and episode, may enter the existing queueing path. A successful POST redirects to GET so browser refresh cannot repeat submission. Confirmation is rendered on the server, including when the React bundle is present, and requires no JavaScript or cookies.

**Tech Stack:** Flask, itsdangerous (already a Flask dependency), Jinja autoescaping, SQLite test fixtures, pytest, Docker/GitHub Actions.

## Files and responsibilities

- `src/app/routes/post_routes.py`: safe method boundary, feed-scoped episode lookup, signed confirmation validation, redirect, and an app-wide response hook protecting trigger responses even when auth middleware returns early.
- `src/app/templates/trigger_confirm.html`: accessible explicit submit form with escaped episode metadata and URL; no auto-submit code.
- `src/tests/test_trigger_routes.py`: passive request, confirmation, authorization, replay/deduplication and escaping regressions with mocked workers (no external model calls).
- `docs/TRIGGER_ARCHITECTURE.md` and `AGENTS.md`: accurate trigger behavior and verification steps.
- `scripts/verify_trigger_links.py`: passive trigger smoke verifies confirmation/status without expecting GET to create a job.
- No model or dependency changes; no migration is required.

## Implementation and verification

- [ ] Write regressions first: GET/HEAD, prefetch headers, and status polling never start a worker; GET returns a confirmation form even with a built frontend.
- [ ] Run new tests against the old implementation and confirm failures demonstrate the bug.
- [ ] Add server-rendered confirmation and signed, expiring, episode/token-bound POST validation. Reject missing, forged, expired, mismatched or query-only confirmation before creating work.
- [ ] Preserve disabled/missing episode and invalid/combined/revoked/cross-feed token checks. Scope lookup to the authenticated feed, and return 409 for ambiguous GUIDs before dispatch: the existing queue/worker accepts only a GUID and cannot distinguish these episodes safely. Test that no worker is reached.
- [ ] Preserve active-job deduplication, ready behavior and existing cooldown. Successful POST returns 303 to the canonical GET URL.
- [ ] Set no-store, noindex/nofollow and no-referrer headers on trigger responses, including middleware 401/429; block framing of the confirmation page.
- [ ] Verify special characters in episode metadata, GUID and query values cannot corrupt the form or inject markup.
- [ ] Run targeted and full backend tests, frontend tests, strict lint and production build, brand verification and dependency audits as required by the release runbook.
- [ ] Obtain independent code review and resolve material findings before merge.

## Release and live acceptance

- [ ] Create and attach a PR, wait for its checks, then merge using a `fix:` Conventional Commit.
- [ ] Wait for semantic release and successful current-main container acceptance/publication. Verify candidate/latest digest, platforms and OCI source revision.
- [ ] Record the existing deployed image, durable rollback tag and environment checksum. Follow `docs/RELEASE_RUNBOOK.md` for a stopped, coordinated instance backup, verify the archive and preserve it before replacing the container.
- [ ] Deploy the published candidate through the existing Compose setup, preserving the environment and instance mount. Confirm health, migration head and source SHA.
- [ ] Verify a real tokenized trigger GET and HEAD, prefetch GET and status poll leave production job counts unchanged; verify invalid POST also creates no job. Inspect the explicit confirmation UI. Verify a valid submit in isolated acceptance with a mocked worker, without spending provider credits in production.
- [ ] Confirm existing ready-episode status/audio delivery still works. Record any external provider limitation separately; do not change keys, models or billing settings.
- [ ] Report the live version, completed checks and any remaining limitation.
