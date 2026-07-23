# Container Release Runbook

This is the canonical operational runbook for publishing and deploying the
Podly Unicorn container. The public artifact is
`ghcr.io/lukefind/podly-unicorn`, and every published candidate supports
`linux/amd64` and `linux/arm64`.

The implementation is authoritative when this runbook and automation differ:

- `.github/workflows/docker-publish.yml` defines acceptance, publication,
  verification, and promotion.
- `.github/workflows/release.yml` defines semantic-release and its handoff to
  container publication.

This process publishes CPU images. It does not describe development-only local
builds or GPU images.

## Before changing the application

Complete this checklist on a branch and have the change reviewed before it is
accepted into `main`.

- Classify the release impact and use a Conventional Commit title.
- If `src/app/models.py` changes, add the matching reversible migration under
  `src/migrations/versions/` in the same change. The current migration head is
  `r4s5t6u7v8w9`; confirm that the new migration revises the actual head rather
  than trusting this sentence.
- If Python dependencies change, update and commit both `Pipfile` and
  `Pipfile.lock`. If frontend dependencies change, update and commit
  `frontend/package.json` and `frontend/package-lock.json`.
- For branding, favicon, or PWA changes, verify every committed source and
  generated asset, including the web manifest and all icon sizes. Run
  `pipenv run python scripts/verify_brand_assets.py`.
- Run the backend and frontend tests appropriate to the change, strict
  frontend lint, the frontend production build, and relevant dependency
  audits. Update active documentation when behavior or operations change.

Useful pre-review checks from the repository root are:

```sh
pipenv install --dev --deploy
pipenv run python -m pip check
pipenv run pytest --disable-warnings
pipenv run python scripts/verify_brand_assets.py

(
  cd frontend
  npm ci
  npm test
  npm run lint -- --max-warnings=0
  npm run build
  npm audit --audit-level=high
)

pipenv run python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

config = Config()
config.set_main_option("script_location", "src/migrations")
heads = ScriptDirectory.from_config(config).get_heads()
assert len(heads) == 1, heads
print(heads[0])
PY
git diff --check
```

Do not merge a model change unless the migration is present and the reported
head is the intended head.

## Commit and release semantics

Podly uses Conventional Commit semantics:

- `fix: correct feed refresh` requests a patch release.
- `feat: add per-feed retention` requests a minor release.
- A commit with `!`, such as `feat!: replace the feed API`, or a
  `BREAKING CHANGE:` footer requests a major release.

Types that do not produce a semantic release, such as `docs`, `test`, `ci`, and
`chore`, may still publish a container because every accepted `main` commit is
deployable. A semantic release creates a Git tag and GitHub release as
appropriate, but **semantic-version Docker tags are not currently published**.
The supported container tags are the immutable candidate
`sha-<full-commit>` and the mutable deployment tag `latest`.

## How an accepted commit reaches GHCR

### Direct main-push flow

1. A push to `main` starts both authoritative workflows.
2. `docker-publish.yml` runs release acceptance for that exact commit and, if
   accepted, creates and verifies its write-once candidate.
3. The same workflow confirms that its commit is still current `main`, then
   promotes the verified digest to `latest`.
4. `release.yml` runs semantic-release. If no release commit is created, the
   original main-push publication remains authoritative.

### Semantic-release flow

For a release-producing Conventional Commit, semantic-release may create and
push a `[skip ci]` commit named `chore(release): <version>`. That new commit is
then the authoritative `main`. Because its skip marker prevents the normal push
automation, `release.yml` explicitly sends a `workflow_dispatch` for
`docker-publish.yml` at `main`. Publication checks out and publishes that new
current-main commit. Any older in-flight publication is rejected by the
stale-main guard before promotion.

A maintainer may also invoke `workflow_dispatch` manually, but only with
`ref=main`, and only current `main` is eligible for release acceptance and
promotion. Never use manual dispatch to publish an older branch or commit.

## Publication gates

The gates below are in the order implemented by
`.github/workflows/docker-publish.yml`.

### 1. Release acceptance

The workflow uses Python 3.12 and a deployed `Pipfile.lock`, installs the pinned
CPU Triton and PyTorch replacements, checks backend dependency consistency,
then runs:

1. the complete backend test suite;
2. committed branding verification;
3. frontend dependency installation with `npm ci`;
4. frontend unit tests;
5. strict frontend lint with zero warnings;
6. the frontend production build;
7. the frontend audit at `high` severity.

Publication cannot start unless this job succeeds.

### 2. Candidate publication and verification

After authentication to GHCR, the publication job runs:

1. **Write-once preflight:** it refuses to continue if
   `ghcr.io/lukefind/podly-unicorn:sha-<full-commit>` already exists. Registry
   inspection errors other than an unambiguously missing manifest also fail
   closed.
2. **Multi-architecture build:** it builds and pushes one candidate manifest
   for `linux/amd64` and `linux/arm64`, labeled with the full source revision.
3. **Manifest validation:** it checks the build digest and requires exactly the
   two runtime platforms, allowing only BuildKit attestation manifests in
   addition.
4. **Vulnerability gates:** Trivy scans the AMD64 image and then the ARM64
   image. Either scan fails on any `HIGH` or `CRITICAL` vulnerability.
5. **Dual-platform health smoke:** each platform-specific digest starts with
   isolated persistent storage and must answer `/health`.
6. **Stale-main guard:** the workflow compares its SHA with remote `main` and
   refuses to promote a candidate after `main` advances.
7. **Promotion and digest verification:** the promotion step moves `latest` to
   the already-verified candidate digest, reads `latest` back from GHCR, and
   requires the resolved digest to match.

No source is rebuilt during promotion.

## Failure handling

Start with the failed GitHub Actions job and step:

```sh
# Placeholder: replace RUN_ID with the failed GitHub Actions run ID.
RUN_ID="replace-with-run-id"
gh run view "$RUN_ID"
gh run view "$RUN_ID" --log-failed
```

The recovery boundary is the promotion step:

- **Failures before the promotion step leave `latest` unchanged.** Inspect the
  release-acceptance, registry, build, manifest, Trivy, health-smoke, or
  stale-main logs and fix the cause.
- A **failure inside the promotion step** requires registry inspection because
  the tag may have moved before the post-promotion digest check failed. Do not
  assume either the old or new digest is live.

Inspect both tags after a promotion-step failure:

```sh
IMAGE="ghcr.io/lukefind/podly-unicorn"
FAILED_SHA="replace-with-full-commit-sha"

docker buildx imagetools inspect "$IMAGE:sha-$FAILED_SHA"
docker buildx imagetools inspect "$IMAGE:latest"
```

If the candidate was already pushed, make the correction in a **new commit**.
Never overwrite the immutable candidate or rerun publication against its
existing write-once tag. A workflow rerun will correctly fail its preflight.
If `main` advanced, use the run for the new current-main commit; do not try to
promote the stale candidate. Manual `workflow_dispatch` is a recovery option
only for current `main` when its candidate tag does not already exist.

## Verify a publication

The following verification starts by fixing the expected authoritative SHA. It
checks GitHub Actions, the public manifest and digest, the OCI revision label,
an anonymous pull, and the running `/health` endpoint.

```sh
REPOSITORY="lukefind/podly-unicorn"
IMAGE="ghcr.io/lukefind/podly-unicorn"
EXPECTED_MAIN_SHA="$(gh api "repos/$REPOSITORY/commits/main" --jq .sha)"
CANDIDATE="$IMAGE:sha-$EXPECTED_MAIN_SHA"

printf 'Expected main SHA: %s\n' "$EXPECTED_MAIN_SHA"
gh run list --workflow docker-publish.yml --commit "$EXPECTED_MAIN_SHA" \
  --json databaseId,event,headSha,status,conclusion,url
gh run list --workflow release.yml --branch main \
  --json databaseId,event,headSha,status,conclusion,url
```

Require the publication run for `EXPECTED_MAIN_SHA` to have conclusion
`success`. Also require the triggering release run to succeed when
semantic-release created that SHA; the dispatched publication, rather than a
push run, is expected for a `[skip ci]` release commit.

Inspect the anonymously readable manifests:

```sh
ANON_DOCKER_CONFIG="$(mktemp -d)"
export DOCKER_CONFIG="$ANON_DOCKER_CONFIG"

docker buildx imagetools inspect "$CANDIDATE" --raw |
  jq -r '.manifests[]
    | select(.platform.os == "linux")
    | select(.platform.architecture == "amd64" or .platform.architecture == "arm64")
    | "\(.platform.os)/\(.platform.architecture) \(.digest)"'

CANDIDATE_DIGEST="$(
  docker buildx imagetools inspect "$CANDIDATE" \
    --format '{{json .Manifest}}' | jq -r .digest
)"
LATEST_DIGEST="$(
  docker buildx imagetools inspect "$IMAGE:latest" \
    --format '{{json .Manifest}}' | jq -r .digest
)"
printf 'candidate digest: %s\nlatest digest:    %s\n' \
  "$CANDIDATE_DIGEST" "$LATEST_DIGEST"
test "$CANDIDATE_DIGEST" = "$LATEST_DIGEST"
```

The platform list must contain `linux/amd64` and `linux/arm64`, and the
candidate and `latest` digests must match. Verify the source label and perform
an anonymous pull and health smoke on the operator's native platform:

```sh
VERIFY_CONTAINER="podly-release-verification"
VERIFY_VOLUME="podly-release-verification"

docker pull "$CANDIDATE"
test "$(
  docker image inspect "$CANDIDATE" \
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
)" = "$EXPECTED_MAIN_SHA"

docker run -d --name "$VERIFY_CONTAINER" \
  -p 127.0.0.1::5001 \
  -e REQUIRE_AUTH=false \
  -v "$VERIFY_VOLUME:/app/src/instance" \
  "$CANDIDATE"
VERIFY_PORT="$(docker port "$VERIFY_CONTAINER" 5001/tcp | sed 's/.*://')"
curl --fail --show-error --silent \
  "http://127.0.0.1:$VERIFY_PORT/health"
docker rm -f "$VERIFY_CONTAINER"
docker volume rm "$VERIFY_VOLUME"
unset DOCKER_CONFIG
rm -r "$ANON_DOCKER_CONFIG"
```

`DOCKER_CONFIG` points at a new empty directory, so the pull and inspections do
not use saved registry credentials.

## Home Lab pre-deploy record and backup

Use the values for the target Home Lab host. Replace every value beginning
`/replace/` before running the block. The bind mount in `compose.yml` is
`src/instance`; it contains the SQLite database and processed podcast data.

```sh
COMPOSE_DIR="/replace/with/podly-compose-directory"
BACKUP_DIR="/replace/with/secure-podly-backup-directory"
ENV_FILE="/replace/with/the-compose-env-file"
SERVICE="podly"
CONTAINER="podly-pure-podcasts"

test -f "$COMPOSE_DIR/compose.yml"
test -f "$ENV_FILE"
grep -q '^PODLY_SECRET_KEY=.' "$ENV_FILE"
mkdir -p "$BACKUP_DIR"
cd "$COMPOSE_DIR"

DEPLOY_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_RECORD="$BACKUP_DIR/predeploy-$DEPLOY_TIMESTAMP.txt"
BACKUP_ARCHIVE="$BACKUP_DIR/podly-instance-$DEPLOY_TIMESTAMP.tar.gz"
ENV_FILE_CHECKSUM="$(sha256sum "$ENV_FILE" | awk '{print $1}')"

{
  printf 'timestamp=%s\n' "$DEPLOY_TIMESTAMP"
  printf 'configured_ref=%s\n' \
    "$(docker inspect "$CONTAINER" --format '{{.Config.Image}}')"
  printf 'local_image_id=%s\n' \
    "$(docker inspect "$CONTAINER" --format '{{.Image}}')"
  printf 'repo_digests:\n'
  docker image inspect \
    "$(docker inspect "$CONTAINER" --format '{{.Image}}')" \
    --format '{{range .RepoDigests}}{{println .}}{{end}}'
  printf 'backup_archive=%s\n' "$BACKUP_ARCHIVE"
  printf 'env_file_sha256=%s\n' "$ENV_FILE_CHECKSUM"
} | tee "$RELEASE_RECORD"
chmod 600 "$RELEASE_RECORD"

docker compose stop "$SERVICE"
tar --create --gzip --file "$BACKUP_ARCHIVE" \
  --directory "$COMPOSE_DIR" src/instance
test -s "$BACKUP_ARCHIVE"
tar --list --file "$BACKUP_ARCHIVE" >/dev/null
chmod 600 "$BACKUP_ARCHIVE"
```

This is how to **record the currently deployed** configured reference and local
image ID, list **every repo digest**, and record the exact backup archive path.
Keep the service stopped between this consistent backup and deployment.

`PODLY_SECRET_KEY` protects sessions, derived feed-token secrets, and encrypted
saved LLM keys. Never print, rotate, replace, or remove it as part of a release:
**PODLY_SECRET_KEY remains unchanged during deploy and rollback**. The
non-secret environment-file checksum makes an accidental edit detectable; it
is not a substitute for securely backing up the environment file and other
host configuration. Store the release record, backup, and configuration backup
according to the Home Lab backup policy.

## Deploy on the Home Lab

From `COMPOSE_DIR`, pull and recreate the service:

```sh
cd "$COMPOSE_DIR"
docker compose pull "$SERVICE"
docker compose up -d "$SERVICE"
docker compose logs --tail=200 "$SERVICE"

test "$(sha256sum "$ENV_FILE" | awk '{print $1}')" = "$ENV_FILE_CHECKSUM"
curl --fail --show-error --silent http://127.0.0.1:5001/health
docker inspect "$CONTAINER" \
  --format 'status={{.State.Status}} health={{.State.Health.Status}} image={{.Image}}'
```

Application startup applies **automatic migrations** before serving requests
and refuses partial startup if migration fails. Check the logs for migration or
startup errors; do not treat a merely running container as a successful
deployment.

Finally, use the real authenticated UI to refresh one subscribed feed, process
or reprocess a representative episode, and play or download the resulting
audio. Confirm the episode reaches Ready and the audio is the expected
ad-processed result.

## Rollback

Prefer the immutable `sha-<full-commit>` tag recorded for the prior release, or
the exact recorded digest. Do not delete or replace the `src/instance` bind
mount and never use `docker compose down -v`.

An application rollback and a schema rollback are separate decisions:

- If the older application is compatible with the current database, retain the
  bind mount and roll back only the image.
- If the older application is incompatible with migrations applied during the
  failed deploy, stop the service and **restore the pre-deploy backup**. Do not
  improvise destructive SQL or assume an application-image rollback reverses
  the schema. Restoring the coordinated data backup also discards data written
  after that backup, so preserve a post-failure copy for investigation.

For an application-only rollback, replace the placeholder with either
`ghcr.io/lukefind/podly-unicorn:sha-<full-commit>` or
`ghcr.io/lukefind/podly-unicorn@sha256:<recorded-digest>`:

```sh
IMAGE="ghcr.io/lukefind/podly-unicorn"
ROLLBACK_REF="replace-with-immutable-sha-tag-or-recorded-digest"

cd "$COMPOSE_DIR"
docker pull "$ROLLBACK_REF"
# This changes only the host-local tag; it does not mutate GHCR.
docker tag "$ROLLBACK_REF" "$IMAGE:latest"
docker compose up -d --pull never --force-recreate "$SERVICE"
docker compose logs --tail=200 "$SERVICE"
curl --fail --show-error --silent http://127.0.0.1:5001/health
test "$(sha256sum "$ENV_FILE" | awk '{print $1}')" = "$ENV_FILE_CHECKSUM"
```

When schema restoration is required, keep the service stopped and use the exact
`BACKUP_ARCHIVE` recorded before deployment:

```sh
ROLLBACK_TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
POST_FAILURE_COPY="$BACKUP_DIR/podly-instance-post-failure-$ROLLBACK_TIMESTAMP.tar.gz"

cd "$COMPOSE_DIR"
docker compose stop "$SERVICE"
tar --create --gzip --file "$POST_FAILURE_COPY" \
  --directory "$COMPOSE_DIR" src/instance
mv "$COMPOSE_DIR/src/instance" \
  "$COMPOSE_DIR/src/instance.post-failure-$ROLLBACK_TIMESTAMP"
tar --extract --gzip --file "$BACKUP_ARCHIVE" --directory "$COMPOSE_DIR"

docker pull "$ROLLBACK_REF"
docker tag "$ROLLBACK_REF" "$IMAGE:latest"
docker compose up -d --pull never --force-recreate "$SERVICE"
docker compose logs --tail=200 "$SERVICE"
curl --fail --show-error --silent http://127.0.0.1:5001/health
test "$(sha256sum "$ENV_FILE" | awk '{print $1}')" = "$ENV_FILE_CHECKSUM"
```

After either path, verify container health, login, feed refresh, and a real
episode. Retain the release record, the original pre-deploy archive, and any
post-failure archive until the rollback is fully investigated.
