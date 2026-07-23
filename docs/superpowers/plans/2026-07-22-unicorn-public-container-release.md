# Unicorn Public Container Release Implementation Plan

> This is a preserved historical record. Its operational release instructions
> are superseded; `docs/RELEASE_RUNBOOK.md` is the authoritative current
> procedure.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore Podly Unicorn as the default brand, modernize and clean the supported dependency stack, and publish a verified public AMD64/ARM64 image at `ghcr.io/lukefind/podly-unicorn:latest`.

**Architecture:** Work in ordered, independently committed checkpoints. First establish a clean test/lint baseline and modern frontend/Python dependency sets, then restore theme behavior and assets, then separate pull-based deployment from contributor builds, and finally publish a write-once candidate that is scanned and runtime-tested before atomic `latest` promotion.

**Tech Stack:** React 19.2, TypeScript 6, Vite 8, Tailwind CSS 4, Vitest, Playwright, Flask/Python 3.12, Pipenv, Docker Buildx/QEMU, GitHub Actions, GHCR, pip-audit, Trivy.

---

## File map

- `frontend/src/themePreference.ts`: pure saved/system theme resolution.
- `frontend/src/themePreference.test.ts`, `frontend/src/theme.test.ts`: theme compatibility and branding contracts.
- `frontend/src/contexts/ThemeContext.tsx`, `frontend/src/theme.ts`: provider integration and theme branding.
- `frontend/package.json`, `frontend/package-lock.json`, `frontend/vite.config.ts`, `frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/eslint.config.js`: modern frontend toolchain.
- `frontend/playwright.config.ts`, `frontend/e2e/theme-visual.spec.ts`, `frontend/e2e/theme-visual.spec.ts-snapshots/`: desktop/mobile visual acceptance for all themes.
- Existing frontend source files reported by ESLint: targeted hook/type/unused-variable fixes only.
- `Pipfile`, `Pipfile.lock`, `Pipfile.lite`, `Pipfile.lite.lock`: current Python 3.12-compatible dependencies.
- `src/tests/test_transcribe.py`, `src/tests/test_ad_classifier.py`: mocked provider SDK contracts.
- `Dockerfile`: Node 24 builder and lock-compatible PyTorch pin.
- `frontend/public/manifest.json`, `frontend/public/sw.js`, `frontend/index.html`, `scripts/generate_pwa_icons.py`, logo/PWA/social/screenshot assets: Unicorn PWA and branding restoration.
- `README.md`, `docs/ARCHITECTURE.md`: Unicorn identity and pull/run documentation.
- `compose.yml`, `compose.build.yml`: pull-based runtime and explicit contributor build override.
- `.github/workflows/lint-and-format.yml`: clean Node 24/frontend and Python validation.
- `.github/workflows/docker-publish.yml`: PR build validation and atomic GHCR publication.

### Task 1: Establish a clean frontend quality baseline

**Files:**
- Modify: `frontend/src/components/EpisodeProcessingStatus.tsx`
- Modify: `frontend/src/components/FeedList.tsx`
- Modify: `frontend/src/components/OnboardingModal.tsx`
- Modify: `frontend/src/components/ProcessingProgressUI.tsx`
- Modify: `frontend/src/components/SubscriptionModal.tsx`
- Modify: `frontend/src/contexts/AudioPlayerContext.tsx`
- Modify: `frontend/src/contexts/AuthContext.tsx`
- Modify: `frontend/src/layouts/PodcastsLayout.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`
- Modify: `frontend/src/theme.ts`
- Create: `frontend/src/hooks/useOnboarding.ts`
- Create: `frontend/src/constants/processingSteps.ts`
- Modify: `frontend/eslint.config.js`

- [ ] **Step 1: Capture the existing lint failures**

Run: `cd frontend && npm run lint`

Expected: FAIL with 16 errors, including a conditional `useMemo`, unnecessary `any` casts, unused bindings, and a missing hook dependency warning.

- [ ] **Step 2: Correct hook ordering and stable dependencies**

Move `FeedList`'s `useMemo` before every early return and memoize the array normalization:

```tsx
const feedsArray = useMemo(() => (Array.isArray(feeds) ? feeds : []), [feeds]);
const filteredFeeds = useMemo(() => {
  // existing filter
}, [feedsArray, searchTerm]);

if (feedsArray.length === 0) return /* existing empty state */;
```

Use `state.currentEpisode` as a dependency of the audio event-listener effect, and include the already-`useCallback`-stable `setField` in ConfigPage's effect dependencies.

- [ ] **Step 3: Replace unsafe and unused bindings**

Use `feed.is_private` directly (it already exists on `Feed`), type `presets` as `PromptPreset[] | undefined`, omit unused caught errors, stop destructuring unused props, and make `getThemeBrandName(theme)` use its argument through the approved Blue-versus-Unicorn mapping. Do not disable `no-explicit-any` globally.

- [ ] **Step 4: Narrowly document intentional Fast Refresh module exports**

Move `useOnboarding` and its storage key to `src/hooks/useOnboarding.ts`, and move `STEP_NAMES` to `src/constants/processingSteps.ts`, updating every import. Add file-pattern overrides only for `src/contexts/*.tsx` and `src/layouts/PodcastsLayout.tsx`, whose Provider/context hook exports are intentionally co-located, with a comment explaining that Fast Refresh warning exception. Fix every exhaustive-dependency warning in code.

- [ ] **Step 5: Verify the baseline is clean**

Run: `cd frontend && npm run lint -- --max-warnings 0 && npm run build`

Expected: both commands exit 0 with zero lint warnings.

- [ ] **Step 6: Commit the baseline fixes**

```bash
git add frontend/src frontend/eslint.config.js
git commit -m "fix: clean frontend lint baseline"
```

### Task 2: Upgrade the frontend toolchain and add test coverage

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.js`
- Delete: `frontend/postcss.config.js`
- Modify: `Dockerfile`
- Modify: `.github/workflows/lint-and-format.yml`
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Record current vulnerability and version failures**

Run `cd frontend && npm outdated || true`, then run `npm audit` as a separate command.

Expected: outdated major versions and direct findings through Axios, PostCSS, React Router, and Vite.

- [ ] **Step 2: Install the newest mutually compatible stable stack**

Run from `frontend/`:

```bash
npm install @tanstack/react-query@latest axios@latest clsx@latest react@latest react-dom@latest react-hot-toast@latest react-router-dom@latest tailwind-merge@latest
npm install -D @eslint/js@latest @playwright/test@latest @tailwindcss/vite@latest @types/react@latest @types/react-dom@latest @vitejs/plugin-react@latest eslint@latest eslint-plugin-react-hooks@latest eslint-plugin-react-refresh@latest globals@latest postcss@latest typescript@6.0.3 typescript-eslint@latest vite@latest vitest@latest
npm uninstall @tailwindcss/line-clamp autoprefixer
```

Before committing, run `npm view` on each direct dependency and record any intentional non-latest constraint. TypeScript 6.0.3 is expected because `typescript-eslint` rejects TypeScript 7.

- [ ] **Step 3: Migrate Vite and Tailwind integration**

Add `@tailwindcss/vite` to Vite plugins. Replace legacy CSS directives with:

```css
@config "../tailwind.config.js";
@import "tailwindcss";
```

Remove the obsolete line-clamp plugin and Autoprefixer/PostCSS config while keeping PostCSS itself at the latest release for the Vite/Tailwind dependency chain. Preserve custom colors, dark-class behavior, and Blue selectors.

- [ ] **Step 4: Move all build environments to Node 24 LTS**

Change `FROM node:18-alpine` to `FROM node:24-alpine` and every `actions/setup-node` version used by this release from 20 to 24.

- [ ] **Step 5: Add unit and browser test scripts**

Add scripts:

```json
"test": "vitest run",
"test:e2e": "playwright test",
"test:e2e:update": "playwright test --update-snapshots"
```

Defer Playwright configuration and snapshots until Task 5, after final branding/assets are present.

- [ ] **Step 6: Verify dependency, lint, test, and build health**

Run:

```bash
cd frontend
npm ci
npm test
npm run lint -- --max-warnings 0
npm run build
npm audit
```

Expected: all exit 0 and `npm audit` reports zero vulnerabilities. If an upstream-only exception remains, stop and document its reachability before proceeding.

- [ ] **Step 7: Commit the frontend modernization**

```bash
git add Dockerfile .github/workflows frontend
git commit -m "chore: modernize frontend dependencies and toolchain"
```

### Task 3: Refresh Python dependencies and prove provider compatibility

**Files:**
- Modify: `Pipfile`
- Modify: `Pipfile.lock`
- Modify: `Pipfile.lite`
- Modify: `Pipfile.lite.lock`
- Modify: `Dockerfile`
- Modify: `src/tests/test_transcribe.py`
- Modify: `src/tests/test_ad_classifier.py`

- [ ] **Step 1: Replace skipped provider checks with passing characterization contracts before upgrading**

Unskip and rewrite remote/Groq transcription tests against the currently locked SDKs. Patch `podcast_processor.transcribe.OpenAI`/`Groq` constructors, supply SDK-shaped response objects, use a real temporary audio file, and assert the exact calls:

```python
client.audio.transcriptions.create.assert_called_once_with(
    model=config.model,
    file=ANY,
    timestamp_granularities=["segment"],
    language=config.language,
    response_format="verbose_json",
)
```

For Groq assert the existing request shape—`file=Path(path)`, `model`, `response_format="verbose_json"`, and `language`—then prove SDK response segments become Podly `Segment` objects. Do not require `timestamp_granularities`, which current Groq code does not send. Keep the LiteLLM response test and assert the actual Podly contract: `model`, two-message system/user list, resolved `api_key`, optional `api_base`, `timeout`, and the model-appropriate max-token keyword passed to `litellm.completion`. No live keys or network calls are allowed.

- [ ] **Step 2: Run the contracts against the current environment**

Run in a clean Python 3.12 verifier: `pytest src/tests/test_transcribe.py src/tests/test_ad_classifier.py -q`.

Expected: PASS against the current locks, establishing behavior before dependency replacement. If a seam is not injectable, make the smallest production refactor that only accepts/internally stores an optional client, rerun RED against the absent seam, implement it, and rerun GREEN before upgrading.

- [ ] **Step 3: Align full/lite declarations and regenerate locks**

First query CPU, PyPI/NVIDIA, and ROCm 6.4 indices for a common PyTorch release. Pin `torch==2.9.1` in the full Pipfile because the current ROCm 6.4 index stops at 2.9.1 while the old lock selected 2.10.0; verify all three indices before locking. Ensure all shared runtime dependencies appear in both Pipfiles. Remove or raise the lite LiteLLM `<1.75.0` cap, then regenerate each lock with Pipenv 2026.0.3 inside clean Python 3.12 containers:

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PIPENV_CACHE_DIR=/tmp/pipenv-cache -v "$PWD:/app" -w /app python:3.12-slim sh -lc 'python -m pip install --user pipenv==2026.0.3 && PIPENV_PIPFILE=Pipfile python -m pipenv lock --clear'
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e PIPENV_CACHE_DIR=/tmp/pipenv-cache -v "$PWD:/app" -w /app python:3.12-slim sh -lc 'python -m pip install --user pipenv==2026.0.3 && PIPENV_PIPFILE=Pipfile.lite python -m pipenv lock --clear'
```

- [ ] **Step 4: Pin Docker PyTorch to the full lockfile**

Read the exact locked `torch` version (expected 2.9.1) and add `ARG TORCH_VERSION=<version>` plus explicit CPU/NVIDIA/ROCm wheel index arguments. After Pipenv completes, force-reinstall the selected backend wheel from its index so the PyPI wheel already installed by dependency resolution cannot win. Before building, run `pip index versions torch` against all three indices. Verify both version and backend: CPU requires no CUDA/HIP and a CPU wheel, NVIDIA requires `torch.version.cuda`, and ROCm requires `torch.version.hip`; fail the Docker build if the selected flavor is wrong.

- [ ] **Step 5: Verify fresh full and lite environments**

For the full environment copy the read-only checkout to a writable container directory so repository-relative fixtures and `.venv` both work, and install/audit `pip-audit` inside that exact virtualenv:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /work python:3.12-slim sh -lc '
  apt-get update && apt-get install -y --no-install-recommends ffmpeg &&
  cp -a /repo/. /work/ && cd /work &&
  python -m pip install pipenv==2026.0.3 &&
  PIPENV_VENV_IN_PROJECT=1 python -m pipenv sync --dev &&
  python -m pipenv run python -m pip install pip-audit &&
  python -m pipenv run pip check &&
  PYTHONPATH=/work/src python -m pipenv run python -c "import flask, whisper, openai, groq, litellm" &&
  PYTHONPATH=/work/src python -m pipenv run pytest src/tests --disable-warnings &&
  python -m pipenv run python -m pip_audit'
```

Run lite verification explicitly by replacing the active Pipfile pair inside the writable copy before syncing:

```bash
docker run --rm -v "$PWD:/repo:ro" -w /work python:3.12-slim sh -lc '
  apt-get update && apt-get install -y --no-install-recommends ffmpeg &&
  cp -a /repo/. /work/ && cd /work &&
  cp Pipfile.lite Pipfile && cp Pipfile.lite.lock Pipfile.lock &&
  python -m pip install pipenv==2026.0.3 &&
  PIPENV_VENV_IN_PROJECT=1 python -m pipenv sync --dev &&
  python -m pipenv run python -m pip install pip-audit &&
  python -m pipenv run pip check &&
  PYTHONPATH=/work/src python -m pipenv run python -c "import flask, openai, groq, litellm" &&
  PYTHONPATH=/work/src python -m pipenv run pytest src/tests/test_transcribe.py src/tests/test_ad_classifier.py --disable-warnings &&
  python -m pipenv run python -m pip_audit'
```

Expected: imports succeed, `pip check` is clean, all tests pass, and no unmitigated high/critical runtime vulnerability remains.

- [ ] **Step 6: Commit Python modernization and contracts**

```bash
git add Pipfile Pipfile.lock Pipfile.lite Pipfile.lite.lock Dockerfile src/tests/test_transcribe.py src/tests/test_ad_classifier.py
git commit -m "chore: refresh Python dependencies and provider contracts"
```

### Task 4: Restore Unicorn theme defaults and product branding test-first

**Files:**
- Create: `frontend/src/themePreference.ts`
- Create: `frontend/src/themePreference.test.ts`
- Create: `frontend/src/theme.test.ts`
- Modify: `frontend/src/contexts/ThemeContext.tsx`
- Modify: `frontend/src/theme.ts`
- Modify: visible branding components identified by the baseline-to-HEAD diff
- Modify: `src/app/feeds.py` and affected branding expectations only where product identity changed

- [ ] **Step 1: Write failing default/persistence tests**

Cover all ten compatibility cases: each valid saved value under both OS preferences, plus missing and invalid values under both preferences:

```ts
for (const stored of ['light', 'dark', 'original'] as const) {
  expect(resolveInitialTheme(stored, false)).toBe(stored);
  expect(resolveInitialTheme(stored, true)).toBe(stored);
}
expect(resolveInitialTheme(null, false)).toBe('light');
expect(resolveInitialTheme(null, true)).toBe('dark');
expect(resolveInitialTheme('invalid', false)).toBe('light');
expect(resolveInitialTheme('invalid', true)).toBe('dark');
```

Also assert Light/Dark use the Unicorn logo and `Podly Unicorn`, while `original` remains labeled Blue and uses the Blue logo/name.

- [ ] **Step 2: Run tests and observe RED**

Run: `cd frontend && npm test -- themePreference.test.ts theme.test.ts`

Expected: FAIL because no pure resolver exists and the current provider defaults to `original`/Podly.

- [ ] **Step 3: Implement the minimal resolver and provider integration**

```ts
export function resolveInitialTheme(
  stored: string | null,
  prefersDark: boolean,
): Theme {
  if (isValidTheme(stored)) return stored;
  return prefersDark ? 'dark' : 'light';
}
```

Make `ThemeContext` call it with `matchMedia`; restore conditional product names without renaming the `original` storage value.

- [ ] **Step 4: Restore visible product identity selectively**

Use the diff against `41ec583004309d774b2746e4b5f548554fcbcb8a` to restore `Podly Unicorn` and Unicorn logo choices in sidebar/login/onboarding/help/trigger/social surfaces. Preserve intentional “Podly RSS” feature text and newer behavior.

- [ ] **Step 5: Verify GREEN and backend branding expectations**

Run: `cd frontend && npm test && npm run lint -- --max-warnings 0 && npm run build`, then targeted Python feed/trigger tests.

Expected: all pass.

- [ ] **Step 6: Commit theme behavior**

```bash
git add frontend/src src/app src/tests
git commit -m "feat: restore Unicorn as the default theme"
```

### Task 5: Restore Unicorn PWA, social, screenshot, and README assets

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/public/manifest.json`
- Modify: `frontend/public/sw.js`
- Modify: `scripts/generate_pwa_icons.py`
- Create: `scripts/verify_brand_assets.py`
- Modify/Create: files under `frontend/public/images/logos/`, `frontend/public/images/screenshots/`, and `frontend/public/images/social-card1200x630.png`
- Modify: `frontend/src/components/HelpModal.tsx`
- Modify: `frontend/src/components/OnboardingModal.tsx`
- Modify: `frontend/src/components/layout/Sidebar.tsx`
- Modify: `frontend/src/pages/ConfigPage.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`
- Modify: `frontend/src/pages/TriggerPage.tsx`
- Modify: `src/app/feeds.py`
- Modify: `src/tests/test_combined_feed.py` (or the existing combined-feed test module found by `rg`)
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/theme-visual.spec.ts`
- Create: `frontend/e2e/theme-visual.spec.ts-snapshots/*.png`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add a failing metadata/asset verification script or test**

Create a standard-library verifier that asserts all of the following:

- document title, Apple title, Open Graph title, and Twitter title are `Podly Unicorn`;
- manifest `name`, background/theme colors, ordinary/maskable purposes and 192/512 dimensions;
- service-worker cache is `v6`, manifest query is `v8`, and icon queries are `v3`;
- PNG signature/IHDR dimensions, ICO header, SVG root, and all required files exist;
- the four historical favicon SHA-256 hashes remain `f3f78a10fc7ad0cc9d197668d37a0d2a584f654dfce82cb9215c08cdf5c429ba`, `08afef87a7679554f7e85bc8fa70a67fc82c1d2c91c189326fb9332c6f8b6422`, `f2f6f220a2c21a0a4da07c63bce605c88b5d035b713911c8a902d732d92d470f`, and `08edb85ef549cf6c312fa90d21841949a7e62455f156b24b6e375edf8eeec3f4` after verifying them with `git show 41ec583:<path> | shasum -a 256`;
- README heading, badge, repository/issues links, upstream credit, and Unicorn image references are correct.

- [ ] **Step 2: Run the verification and observe RED**

Expected: current Blue PWA metadata, social card, screenshots, and README fail.

- [ ] **Step 3: Restore historical assets and update the generator**

Restore the flat Unicorn/social/screenshot assets from `41ec583004309d774b2746e4b5f548554fcbcb8a`. Preserve current favicon files after verifying their blobs already match. Make the PWA generator use a dedicated flat Unicorn source, purple background, full ordinary icon area, and 75% maskable safe zone; regenerate all four PWA outputs. Update exactly the listed Help/Onboarding/Sidebar/Config/Home/Login/Trigger components and combined-feed title/image paths; use `rg -n "Podly|original-logo"` with an intentional allowlist so “Podly RSS” remains unchanged.

- [ ] **Step 4: Restore PWA metadata and invalidate caches**

Return document/manifest names and colors to Unicorn, increment manifest/icon query strings, and increment the service-worker cache version.

- [ ] **Step 5: Restore README identity without reverting content**

Restore the Unicorn hero, heading, fork badge, repository/issues links, upstream credit, alt text, social image, and Unicorn screenshots while retaining current feature/configuration documentation.

- [ ] **Step 6: Configure and generate visual acceptance snapshots**

Use Playwright projects with exact viewports `1440x1000` and `390x844`. For `light`, `dark`, and `original`, set `podly-theme` and `podly_onboarding_completed=true` in `page.addInitScript`, load `/`, assert the expected logo path/title/navigation, and assert:

```ts
expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
await expect(page).toHaveScreenshot(`${theme}-${projectName}.png`, {
  fullPage: true,
  animations: 'disabled',
});
```

Generate and compare against a real lite server using only unique disposable resources:

```bash
visual_suffix="${RANDOM}-$$"
visual_image="podly-unicorn:visual-${visual_suffix}"
visual_container="podly-visual-${visual_suffix}"
visual_volume="podly-visual-${visual_suffix}"
cleanup_visual() { docker rm -f "$visual_container" 2>/dev/null || true; docker volume rm "$visual_volume" 2>/dev/null || true; }
trap cleanup_visual EXIT
docker build --build-arg LITE_BUILD=true -t "$visual_image" .
docker run -d --name "$visual_container" -p 127.0.0.1::5001 -e REQUIRE_AUTH=false -v "$visual_volume:/app/src/instance" "$visual_image"
visual_port=$(docker port "$visual_container" 5001/tcp | sed 's/.*://')
for attempt in $(seq 1 60); do curl -fsS "http://127.0.0.1:${visual_port}/health" && break; sleep 2; done
curl -fsS "http://127.0.0.1:${visual_port}/health" || { docker logs "$visual_container"; exit 1; }
cd frontend && npx playwright install chromium
PLAYWRIGHT_BASE_URL="http://127.0.0.1:${visual_port}" npm run test:e2e:update
PLAYWRIGHT_BASE_URL="http://127.0.0.1:${visual_port}" npm run test:e2e
cleanup_visual
trap - EXIT
```

Open all six generated PNGs with the workspace image viewer before accepting them.

- [ ] **Step 7: Run metadata tests and frontend build**

Run `python scripts/verify_brand_assets.py`, targeted combined-feed tests, frontend unit tests, zero-warning lint, build, and the Playwright comparison. Expected: all pass.

- [ ] **Step 8: Commit asset and documentation restoration**

```bash
git add README.md docs/ARCHITECTURE.md frontend/index.html frontend/public frontend/e2e frontend/playwright.config.ts frontend/src scripts/generate_pwa_icons.py scripts/verify_brand_assets.py src/app/feeds.py src/tests
git commit -m "feat: restore Unicorn PWA and project branding"
```

### Task 6: Add pull-based deployment and atomic GHCR publication

**Files:**
- Modify: `compose.yml`
- Create: `compose.build.yml`
- Modify: `README.md`
- Modify: `.github/workflows/docker-publish.yml`

- [ ] **Step 1: Write failing Compose assertions**

First make the service env file overrideable as `${PODLY_ENV_FILE:-./.env.local}` so validation never needs to create or overwrite a user's `.env.local`. Run with `PODLY_ENV_FILE=.env.local.example docker compose config --format json` and prove the current configuration fails this executable desired-state assertion:

```bash
PODLY_ENV_FILE=.env.local.example docker compose config --format json |
  jq -e '.services.podly.image == "ghcr.io/lukefind/podly-unicorn:latest"
    and (.services.podly | has("build") | not)
    and any(.services.podly.volumes[]; .target == "/app/src/instance")'
```

- [ ] **Step 2: Split runtime and contributor build configuration**

Set default `image: ghcr.io/lukefind/podly-unicorn:latest`, remove `build`, retain `./src/instance:/app/src/instance`, and add `compose.build.yml` containing the existing Dockerfile and all build arguments. Verify the prior `jq` assertion and this contributor assertion:

```bash
PODLY_ENV_FILE=.env.local.example docker compose config --format json | jq -e '.services.podly.image == "ghcr.io/lukefind/podly-unicorn:latest" and (.services.podly | has("build") | not) and any(.services.podly.volumes[]; .type == "bind" and .target == "/app/src/instance")'
PODLY_ENV_FILE=.env.local.example docker compose -f compose.yml -f compose.build.yml config --format json | jq -e '.services.podly.build.context and .services.podly.build.dockerfile == "Dockerfile"'
```

- [ ] **Step 3: Write the exact no-clone README path**

Document creation of `podly.env` containing all five settings, a saved `openssl rand -hex 32` secret, password minimum, localhost cookie rule, named volume, `docker run`, provider setup in the web UI, HTTPS reverse-proxy/cookie guidance, and `docker pull` plus safe container recreation. Also include a complete pull-based Compose file/download path and `docker compose pull && docker compose up -d` update flow.

- [ ] **Step 4: Replace Docker validation with validate-and-publish workflow**

Implement these exact safety properties:

- workflow-level default `contents: read`; PR validation has no package write permission;
- publish job has `contents: read, packages: write`, runs only for a `main` push or manual dispatch whose selected ref is `refs/heads/main`;
- `concurrency: { group: publish-podly-container, cancel-in-progress: false }` serializes releases, and immediately before promotion `git ls-remote origin refs/heads/main` must still equal `${GITHUB_SHA}` so a stale run cannot overwrite `latest`;
- canonical args are `BASE_IMAGE=python:3.12-slim`, `LITE_BUILD=false`, `USE_GPU=false`, `USE_GPU_NVIDIA=false`, and `USE_GPU_AMD=false`;
- OCI labels include source, revision, licenses, title, and description;
- after GHCR login, capture both status and stderr from `docker buildx imagetools inspect "$IMAGE:sha-${GITHUB_SHA}"`: status 0 means the write-once tag exists and aborts; nonzero is allowed only when stderr matches registry `manifest unknown`/HTTP 404. Authentication, authorization, timeout, DNS, or other network failures abort rather than authorize an overwrite;
- Buildx pushes `linux/amd64,linux/arm64`; capture `steps.build.outputs.digest`, inspect `"$IMAGE@$DIGEST" --raw`, and use `jq` to require exactly both target platforms (allowing only documented attestation manifests in addition);
- run Trivy separately with `--platform linux/amd64` and `linux/arm64`, `--exit-code 1 --severity HIGH,CRITICAL`, against `"$IMAGE@$DIGEST"`; do not ignore unfixed findings automatically—every exception requires explicit reviewed mitigation;
- set up QEMU, run a uniquely named container for each platform from `"$IMAGE@$DIGEST"`, poll `/health` conditionally for up to 120 seconds, print logs on failure, and always remove containers in a trap;
- promote only with `docker buildx imagetools create --tag "$IMAGE:latest" "$IMAGE@$DIGEST"`, then assert the remote `latest` digest equals `$DIGEST`.

- [ ] **Step 5: Validate workflow syntax and Compose output**

Use Ruby/Python YAML parsing plus `actionlint` (containerized if absent), run both executable Compose assertions, and inspect permissions/guards/concurrency with targeted `yq` assertions.

- [ ] **Step 6: Commit distribution configuration**

```bash
git add compose.yml compose.build.yml README.md .github/workflows/docker-publish.yml
git commit -m "ci: publish verified multi-architecture GHCR image"
```

### Task 7: Execute full local release verification

**Files:**
- Modify only if a verification failure identifies a root cause; use a new focused commit for each fix.
- Create locally but do not commit: temporary volumes, containers, reports, and screenshots outside tracked snapshot paths.

- [ ] **Step 1: Run frontend acceptance**

Run unit tests, zero-warning lint, production build, and `npm audit` from a clean `npm ci`.

- [ ] **Step 2: Run full/lite Python acceptance**

In clean Python 3.12 environments run provider contracts, the full suite, `pip check`, import smokes, and `pip-audit`.

- [ ] **Step 3: Build baseline and candidate images**

Create a validated temporary workspace and cleanup trap, then build a pre-code-change baseline and current candidates:

```bash
release_tmp_dir=$(mktemp -d /tmp/podly-release.XXXXXX)
baseline_path="$release_tmp_dir/baseline"
release_volume="podly-release-${RANDOM}"
baseline_container="podly-baseline-${RANDOM}"
candidate_container="podly-candidate-${RANDOM}"
cleanup_release_test() {
  docker rm -f "$baseline_container" "$candidate_container" 2>/dev/null || true
  docker volume rm "$release_volume" 2>/dev/null || true
  git worktree remove --force "$baseline_path" 2>/dev/null || true
  rm -rf "$release_tmp_dir"
}
trap cleanup_release_test EXIT
git worktree add --detach "$baseline_path" 5aaee1a
docker build --build-arg LITE_BUILD=true -t podly-unicorn:baseline "$baseline_path"
docker build --build-arg LITE_BUILD=false -t podly-unicorn:candidate-full .
docker build --build-arg LITE_BUILD=true -t podly-unicorn:candidate-lite .
docker image inspect podly-unicorn:baseline podly-unicorn:candidate-full podly-unicorn:candidate-lite --format '{{.RepoTags}} {{.Id}}'
```

- [ ] **Step 4: Test fresh and existing volumes**

Health-smoke full and lite on fresh temporary volumes. For the upgrade test, create `$release_volume`, start the baseline lite image with `REQUIRE_AUTH=false`, wait on `/health`, and insert a real SQLite marker row:

```bash
docker exec "$baseline_container" python -c 'import sqlite3; p="/app/src/instance/sqlite3.db"; c=sqlite3.connect(p); c.execute("CREATE TABLE IF NOT EXISTS release_marker (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"); c.execute("INSERT OR REPLACE INTO release_marker VALUES (1, ?)", ("preserve-me",)); c.commit()'
```

Stop/remove only the baseline container, start `podly-unicorn:candidate-full` with the same volume, and wait for automatic migration/health. Verify `SELECT value FROM release_marker WHERE id=1` returns `preserve-me`. Compute the single Alembic head from the candidate source by parsing every migration's `revision`/`down_revision`, query `alembic_version.version_num` inside the mounted database, and require equality. Print container logs on any failure; the trap removes only the uniquely named containers, volume, and `mktemp` worktree.

- [ ] **Step 5: Run browser visual acceptance**

Install Playwright Chromium, start the candidate without auth, generate Light/Dark/Blue desktop/mobile snapshots, compare with committed expectations, and visually inspect all six images for branding, layout, utilities, and overflow.

- [ ] **Step 6: Scan local candidate**

Run Trivy against both local images:

```bash
trivy image --exit-code 1 --severity HIGH,CRITICAL podly-unicorn:candidate-full
trivy image --exit-code 1 --severity HIGH,CRITICAL podly-unicorn:candidate-lite
```

If the CLI is absent, use the official `aquasec/trivy` container with a read-only Docker socket mount. Publication is blocked unless fixed or explicitly reviewed as unreachable/mitigated.

- [ ] **Step 7: Re-run the complete verification matrix after any fix**

Expected: all required checks pass with fresh output.

### Task 8: Integrate, publish, and verify the public artifact

**Files:**
- No planned source changes; fixes require returning to the relevant prior task and re-verifying.

- [ ] **Step 1: Review branch scope and commits**

Run `git status`, `git diff main...HEAD --check`, inspect every changed file, and request code review using `superpowers:requesting-code-review`.

- [ ] **Step 2: Integrate the branch into local `main`**

Use `superpowers:finishing-a-development-branch`; preserve the user's existing local commits, merge non-destructively, and rerun release verification on the integrated commit.

- [ ] **Step 3: Push public `main`**

Push `main` to `origin` only after local verification is green. This triggers validation, semantic release, and container publication.

- [ ] **Step 4: Monitor GitHub Actions to terminal success**

Watch the validation and Docker workflows. If any gate fails, diagnose, fix on the branch, re-verify, integrate, and push a new commit; do not bypass a gate.

- [ ] **Step 5: Make the GHCR package public**

Inspect package visibility. GitHub does not document a Packages REST visibility-update endpoint, so if the first GHCR publication is private, open the owner package settings page, choose **Change package visibility → Public**, and complete the owner confirmation. This is an explicit UI step; do not invent an API call. Then verify anonymously.

- [ ] **Step 6: Verify the published artifact independently**

Use a clean Docker client config with no credentials:

```bash
anonymous_docker_config=$(mktemp -d /tmp/podly-docker-config.XXXXXX)
DOCKER_CONFIG="$anonymous_docker_config" docker buildx imagetools inspect ghcr.io/lukefind/podly-unicorn:latest
DOCKER_CONFIG="$anonymous_docker_config" docker pull ghcr.io/lukefind/podly-unicorn:latest
```

Require AMD64 and ARM64, record the candidate and `latest` digests and require equality. Set up QEMU, then for each of `linux/amd64` and `linux/arm64` run `docker run --platform <platform>` from the anonymously accessible digest with a unique container and volume, poll `/health`, and print logs on failure. A cleanup trap removes only those unique resources and the temporary Docker config. Confirm README commands use the exact public image.

- [ ] **Step 7: Report release evidence**

Provide the image name, digest, architectures, workflow links, test/audit results, visibility/pull proof, and any explicitly accepted vulnerability exception.
