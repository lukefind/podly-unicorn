# Security Maintenance Implementation Plan

> **For agentic workers:** Execute directly unless the plan contains at least two genuinely independent tasks that qualify for superpowers:subagent-driven-development. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Resolve the dependency advisories and two code defects identified in the October 24 audit, while preserving supported deployment and processing behavior.

**Architecture:** Regenerate both Python locks and the frontend lock from compatible patched dependencies. Route untrusted RSS and enclosure downloads through one HTTP transport that restricts destination addresses at connection time and checks redirects, and generate full/lite locks without renaming manifests. Keep schema and live production data unchanged.

**Tech Stack:** Python 3.12, Flask, requests/urllib3, Pipenv, React, Vite/Vitest, Docker/Chainguard, PyTorch CPU/CUDA/ROCm.

## Requirements and boundaries

- The user authorized updating and fixing every item in the dependency audit, including LiteLLM/PyTorch compatibility review, feed SSRF, and the lockfile script.
- Known dependency targets: certifi >=2026.10.19, urllib3 >=2.8.0, aiohttp >=3.14.4, multidict >=6.9.1, Werkzeug >=3.1.9, Pillow >=13.0.0, setuptools >=84.1.0, Black >=26.10.1; latest compatible LiteLLM; Axios >=1.20.0, follow-redirects >=1.16.1, Vite >=8.1.6, Vitest >=4.1.12; patched frontend transitive dependencies.
- Examine actual advisory reachability and published wheel availability before resolving PyTorch or filelock constraints; never hide unresolved findings or fabricate safe versions.
- Do not deploy, publish, modify production schema/data, or claim GPU execution was tested without hardware.
- Rehearse any startup against disposable instance and podcast-data directories with PODLY_DISABLE_SCHEDULER=1.

## Task 1: Protect RSS and enclosure network access

**Files:** Create `src/shared/http_client.py` and `src/tests/test_http_client.py`; modify `src/app/feeds.py`, `src/app/routes/feed_routes.py`, `src/podcast_processor/podcast_downloader.py`, and their existing tests.

- [x] Write failing tests for private/loopback/link-local/multicast/reserved IPv4 and IPv6, IPv4-mapped IPv6, invalid schemes/credentials, public-to-private redirects, and DNS rebinding. Mock external transport/DNS so no private service is contacted.
- [x] Implement one HTTP(S) helper with address checks at connection time, preserving HTTPS hostname/SNI verification. Do not validate DNS then let requests independently resolve an unrestricted address. Disable environmental proxies unless explicitly validated and safe. Follow redirects only through the same policy, cap them, close discarded responses, and preserve existing streaming/timeouts/headers.
- [x] Use this helper for both RSS refresh/add and enclosure audio downloads. Return clear, safe client errors for rejected feed URLs without leaking credentials or network internals.
- [x] Update existing network mocks for the helper and prove ordinary public feeds, public redirects, CDN enclosures, and downloader retries still work.
- [x] Run focused HTTP/feed/downloader tests, then request spec review followed by code quality/security review.

## Task 2: Fix lock generation and refresh dependencies

**Files:** Modify `scripts/generate_lockfiles.sh`, `Pipfile`, `Pipfile.lite`, both `.lock` files, frontend manifests/lock, `Dockerfile`, relevant Compose/workflow pins, and security documentation; add a focused script regression test outside application startup if needed.

- [x] Reproduce lock loss using a fake Pipenv in a temporary directory; cover failed lock commands and invocation outside the repository.
- [x] Generate locks using explicit PIPENV_PIPFILE paths without moving manifests; preserve both independent outputs and nonzero failure status.
- [x] Query current registry/advisory metadata and official Torch CPU/CUDA/ROCm indexes. Select compatible released wheels and align Docker/CI/Compose pins where necessary.
- [x] Update compatible frontend versions and security transitive dependencies; keep major upgrades limited to what resolves advisories or compatibility.
- [x] Update patched Python versions and regenerate locks with Pipenv, preserving hashes/markers. Resolve LiteLLM's OpenAI/filelock constraints using a supported release or remove an unreachable runtime dependency only with evidence; document any unavoidable residual advisory precisely.
- [x] Add dependency audits to pull-request checks, including both Python locks. Consider a scheduled audit workflow so existing releases are checked as advisories change; run no deployment on scheduled audits.
- [x] Run lock verification, pip check in isolated environments, full backend tests, frontend unit tests/lint/build, and fresh package vulnerability checks.

## Task 3: Verify container and complete handoff

**Files:** `docs/SECURITY_AUDIT.md`, plan checkboxes, only compatibility repairs required by the preceding tasks.

- [x] Build and smoke-test the updated lite container, and full CPU container where feasible, without mounting the live instance directory.
- [x] Scan built containers with a public scanner that does not require Docker Scout login. Report both architectures or explicitly describe coverage limits.
- [x] Review the complete diff for correctness and scope; resolve substantive review findings and rerun affected checks.
- [x] Record actual results and remaining limitations in the security audit; leave concrete, reviewable branch changes for the user.

Completed locally on `staging/security-maintenance-2026-10`. The final backend
suite passed 467 tests with one skipped; frontend passed 71 tests, lint, and
build. Both Python lock audits and npm audit report zero findings. Trivy reports
zero findings for the canonical lite ARM64 and full CPU ARM64/AMD64 images.
All three plus an Ubuntu lite compatibility build passed disposable startup,
migration, HTTPS, and private-address rejection checks. Full CPU inference
passed on both architectures. Independent final review approved the changes.

The security audit records the remaining coverage limits: no GPU execution,
no AMD64 lite startup test, and an unresolved upstream pt2 model-loading advisory
outside Podly's current API usage. No advisory was suppressed and no production
deployment or data was modified.

On October 25, after the implementation and follow-up review, the user explicitly
authorized publication and production deployment ("get this live please"). The
earlier no-publish/no-deploy boundary applied to implementation and review; this
new authorization permits the release runbook's acceptance, publication, backup,
deployment, and health-verification steps.

## Verification commands

Use the project Python 3.12 virtualenv or an isolated temporary environment. Use temporary audit files and avoid booting Flask against `src/instance`.

```sh
pipenv verify
PIPENV_PIPFILE=Pipfile.lite pipenv verify
pipenv run python -m pip check
pipenv run pytest --disable-warnings
cd frontend
npm ci
npm test
npm run lint -- --max-warnings=0
npm run build
npm audit --audit-level=low
```

Security scans must cover direct and transitive runtime/development lock entries, deduplicate advisory aliases, and distinguish version flags from exploitability. Custom backend Torch wheels require explicit advisory evaluation because PyPI-only scanners can skip them.
