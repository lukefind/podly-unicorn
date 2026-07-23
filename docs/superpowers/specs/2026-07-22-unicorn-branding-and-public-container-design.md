# Unicorn Branding and Public Container Design

> This is a preserved historical record. Its operational release instructions
> are superseded; `docs/RELEASE_RUNBOOK.md` is the authoritative current
> procedure.

## Goal

Make Podly Unicorn the default presentation again without removing the optional Blue theme, and publish a public container that users can run without cloning or building the repository.

## Branding and theme behavior

- New browsers, cleared browsers, and browsers without a valid saved preference start in the Unicorn family: `light` when the operating system prefers light and `dark` when it prefers dark.
- A valid saved theme remains authoritative. In particular, an existing browser that explicitly stored Blue is not forcibly migrated.
- Blue stays in the theme rotation and its implementation remains intact; it is simply no longer the fallback.
- Product-facing metadata returns to `Podly Unicorn`, including the document title, installable PWA name, Apple web-app title, social metadata, and theme-aware brand label.

The compatibility mapping remains:

| Stored value | Display label | Logo | Product name |
| --- | --- | --- | --- |
| `light` | Light | `unicorn-logo.png` | Podly Unicorn |
| `dark` | Dark | `unicorn-logo.png` | Podly Unicorn |
| `original` | Blue | `original-logo.png` | Podly |

The storage key remains `podly-theme`; renaming `original` would break saved preferences and is out of scope.

## Asset restoration

Use commit `41ec583004309d774b2746e4b5f548554fcbcb8a` (the parent of the Blue/upstream rebrand) as the visual and naming baseline while retaining the later service-worker and manifest correctness fixes:

- favicon SVG/PNG/ICO and Apple touch icon;
- ordinary and maskable PWA icons;
- PWA background and theme colors;
- README hero, social card, and screenshots where the Blue-theme replacements displaced Unicorn artwork;
- visible logo choices and product naming in the sidebar, login, onboarding/help, trigger, and combined-feed surfaces.

The favicon files already match that baseline and are retained after verification. Restore the baseline's flat Unicorn mark for ordinary PWA icons and use the same mark inside the Android maskable safe zone. The PWA/document colors return to `#1e1b4b` (background) and `#7c3aed` (theme). Update `scripts/generate_pwa_icons.py` so future regeneration uses the Unicorn source and these colors. Bump the service-worker cache version and the manifest/icon query-string versions in `frontend/index.html` so cache-first clients receive the restored assets.

README restoration covers the Podly Unicorn heading, hero, screenshots, alt text, fork badge, `lukefind/podly-unicorn` repository/issues/contributor links, and upstream credit. Intentional feature terms such as “Podly RSS” remain unchanged.

This is a selective restoration. It must not revert newer application behavior, accessibility fixes, PWA caching logic, or unrelated upstream-integration work.

## Public container distribution

Publish the canonical image at:

`ghcr.io/lukefind/podly-unicorn:latest`

The canonical image is the full CPU build using `BASE_IMAGE=python:3.12-slim`, `LITE_BUILD=false`, and all GPU build flags disabled. It supports `linux/amd64` and `linux/arm64`. The repository's GitHub Actions workflow publishes on pushes to `main` and on manual dispatch only when the selected ref is `main`; it has `contents: read` and `packages: write`, logs in to GHCR with the repository token, builds through Buildx, and publishes standard OCI source/revision/description labels. Pull requests retain build validation but never receive registry write permission and never publish.

Publication is atomic:

1. Refuse the release if the candidate tag `sha-<full-commit-SHA>` already exists, then push the candidate manifest under that exact tag.
2. Record its immutable registry digest and verify both advertised architectures.
3. Scan the installed Python and OS packages in both candidate architectures with Trivy and block on unresolved high/critical runtime findings unless an explicit, reviewed mitigation exists.
4. Pull and health-smoke-test the AMD64 and ARM64 candidate images under their respective runtime/QEMU platforms.
5. Promote that verified and scanned manifest to the mutable `latest` tag with `docker buildx imagetools create`.

The workflow treats `sha-<full-commit-SHA>` as write-once and records the registry digest as the immutable content reference. A failed candidate never replaces the previous `latest`.

The default end-user Compose configuration references the published image and does not contain a local build section. It retains the existing `./src/instance:/app/src/instance` bind mount so upgrades do not make existing databases appear to disappear. Contributor/local builds use `docker compose -f compose.yml -f compose.build.yml up -d --build`, where the explicit override supplies the current Dockerfile and build arguments.

## Dependency modernization and baseline quality

Modernize the application before publishing so the public image does not begin life on an obsolete or known-vulnerable toolchain. “Latest” means the newest mutually compatible stable package set available when the lockfiles are regenerated on 22 July 2026; blindly combining incompatible latest versions is not acceptable.

### Frontend

- Move local-container and CI frontend builds from Node 18/20 to Node 24 LTS.
- Upgrade to Vite 8, `@vitejs/plugin-react` 6, Tailwind CSS 4 with its supported Vite integration, ESLint 10, React/React DOM 19.2, React Router 7.18, current Axios/PostCSS releases, and the newest compatible releases of the remaining direct packages.
- Use TypeScript 6.0.3 rather than TypeScript 7 because the current `typescript-eslint` 8.65 peer range is `>=4.8.4 <6.1.0`. This is an explicit compatibility constraint, not stale pinning.
- Remove superseded packages such as the standalone Tailwind line-clamp plugin when the framework now provides the capability directly.
- Add Vitest and extract theme initialization into a small pure unit that can be tested without rendering the application.
- Resolve the existing lint baseline: conditional hooks, missing domain types hidden behind `any`, and unused parameters/errors. Existing Fast Refresh and exhaustive-dependency warnings must either be corrected or narrowly justified; errors may not be suppressed globally.

The Tailwind migration retains existing custom theme tokens, `dark` class behavior, and Blue-theme selectors. It changes the build integration, not the visual design beyond the separately approved Unicorn restoration.

### Python

- Keep Python 3.12 as the supported runtime because the audio/Whisper/PyTorch stack is validated against it.
- Regenerate `Pipfile.lock` and `Pipfile.lite.lock` using the pinned Pipenv release and current PyPI metadata.
- Resolve every wildcard to the newest Python-3.12-compatible version. Revisit the old LiteLLM cap in the lite environment: remove or raise it if the latest compatible release builds and passes tests; retain a cap only with a reproduced incompatibility and a documented reason.
- Keep full and lite dependency definitions aligned for shared packages.
- Pin the Dockerfile's post-Pipenv CPU, NVIDIA, and ROCm PyTorch installations to the exact version selected by the full lockfile. The Docker build must not silently replace the audited dependency with an unrelated newest release.

Create fresh, isolated full and lite environments and require `pip check` plus import smoke tests for Flask, Whisper (full only), OpenAI, Groq, and LiteLLM. Add mocked provider contract tests that exercise the request shapes and response handling used by Podly's OpenAI/Groq transcription and LiteLLM completion paths; these tests use no real API keys or billable calls.

### Change isolation

Commit and verify the work in checkpoints: baseline lint fixes, frontend dependency/toolchain migration, Python lock refresh, Unicorn branding/theme behavior, container distribution/docs, and release publication. This makes a regression attributable without splitting the work into separate public releases.

## Installation experience

The README leads with a no-clone container path:

1. Create a local deployment directory and a `podly.env` file without cloning the repository.
2. Create the complete environment file with `REQUIRE_AUTH=true`, `PODLY_ADMIN_USERNAME=admin`, a `PODLY_ADMIN_PASSWORD` of at least eight characters, a saved `PODLY_SECRET_KEY` generated by `openssl rand -hex 32`, and `SESSION_COOKIE_SECURE=false` for the documented localhost HTTP path.
3. Create a persistent named volume and run the public image with `--env-file podly.env`, the volume mounted at `/app/src/instance`, and port `5001` published.
4. Open the web UI and complete provider setup there.

A pull-based Compose example is also documented for users who prefer declarative deployment. It preserves the bind-mounted `src/instance` layout. Update instructions use `docker pull`/container recreation for the no-clone path or `docker compose pull` followed by `docker compose up -d` for Compose, not `git pull` and a rebuild. HTTPS deployments omit the localhost-only cookie override and should terminate TLS at a reverse proxy.

Secrets in documentation use placeholders or generated values; no real credentials are committed or baked into the image.

## Verification and release

Before publication:

- add Vitest to the frontend and test all valid stored values (`light`, `dark`, `original`) plus missing/invalid values under both operating-system color preferences;
- verify branding strings, manifest metadata, service-worker cache versioning, and restored asset dimensions/types;
- run `npm test -- --run`, `npm run lint`, and `npm run build` in `frontend/`;
- run `npm audit` and require zero known vulnerabilities, or document any unfixable upstream-only exception with its production reachability; high or critical runtime findings block publication;
- run the existing Python test suite and the new provider contract tests in clean Python 3.12 full and lite environments;
- run `pip check` in both installed environments and audit them with `pip-audit`; high or critical runtime findings block publication unless an explicit, reviewed mitigation exists;
- validate both Compose files with `docker compose config` and verify the default config resolves to the GHCR image, the bind mount, and no build section;
- build both the full canonical image and lite image, smoke-test each image's health endpoint with fresh temporary data volumes, and verify their installed imports/dependencies;
- create a representative persistent volume with the pre-change baseline image, add non-secret marker data, start the candidate image against that same volume, allow automatic migrations to run, and verify both health and marker preservation;
- run browser acceptance after the Tailwind migration at representative desktop and mobile viewports in Light, Dark, and Blue. Capture screenshots, verify the correct logo/theme in each, check key navigation/content is visible, and reject horizontal overflow or visibly missing utility styles.

For release:

- push the implementation to the public repository so the main/manual-only publishing workflow runs;
- confirm the workflow succeeds and the GHCR package is public;
- inspect the remote multi-architecture manifest;
- anonymously pull the published image into a clean local tag and repeat the health smoke test from the registry artifact;
- run the AMD64 and ARM64 images (using QEMU where the host architecture differs) and require both `/health` checks to succeed.
- confirm the workflow's pre-promotion Trivy scan covered both candidate architectures and passed its security gate.

Publication is not considered complete until an unauthenticated registry pull is possible and both advertised architectures appear in the manifest.

## Failure handling

- If a build or smoke test fails, do not publish a replacement `latest` tag until fixed and reverified.
- If GHCR creates the package as private, explicitly change package visibility to public before documenting it as available.
- If one architecture fails, retain the prior working `latest` image and report the incomplete release rather than advertising a partial multi-architecture image.
