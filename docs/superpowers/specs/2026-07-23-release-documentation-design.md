# Release Documentation Design

## Purpose

Make the complete path from an application change to a verified public container—and from that container to the Home Lab deployment—unambiguous, recoverable, and resistant to documentation drift.

## Problem

The implementation is safer and more complete than the active documentation:

- `.github/workflows/docker-publish.yml` publishes every authoritative `main` commit through an immutable `sha-<full-commit>` candidate and promotes only a verified digest to `latest`.
- `.github/workflows/release.yml` may create a semantic-release commit and explicitly dispatch publication for that new `main`.
- The README explains installation and updating, but not the maintainer release lifecycle.
- `docs/contributors.md` describes Conventional Commits but does not explain the two-workflow interaction, publication gates, failure recovery, or rollback.
- The Home Lab note explains how to pull the image but not how a source change becomes that image.
- Historical design and implementation documents contain useful dated context but are not the current operational authority.
- `AGENTS.md` contains a stale migration-head statement and lacks a concise release checklist.

## Documentation Architecture

### Canonical operational source

Create `docs/RELEASE_RUNBOOK.md` as the one complete maintainer and operator reference. It will cover:

1. Pre-change requirements:
   - branch and review expectations;
   - required migrations for model changes;
   - dependency lockfiles;
   - branding/PWA asset verification;
   - local tests appropriate to the change.
2. Commit and release semantics:
   - Conventional Commit examples;
   - `fix` → patch, `feat` → minor, and breaking changes → major;
   - non-release types may still publish a new container because every `main` commit is deployable;
   - the current absence of semantic-version Docker tags.
3. Automated publication:
   - direct `main` push and manual-main dispatch triggers;
   - semantic-release’s optional release commit and explicit dispatch;
   - immutable `sha-<full-commit>` candidate;
   - release acceptance, manifest validation, strict vulnerability scans, dual-platform health smoke, stale-main guard, and atomic `latest` promotion.
4. Failure handling:
   - failures before the promotion step leave `latest` unchanged;
   - a failure inside the promotion step requires explicit registry inspection because the tag operation may have completed before post-promotion verification failed;
   - inspect the failed job before retrying;
   - if a candidate was already pushed, fix with a new commit rather than overwriting or rerunning the write-once tag;
   - manual dispatch is valid only for current `main`.
5. Verification:
   - identify the intended `main` SHA;
   - verify workflow conclusions;
   - inspect public manifest architectures and digest;
   - verify OCI source revision;
   - perform an anonymous pull and `/health` check.
6. Home Lab deployment:
   - record the currently deployed image reference and digest before pulling `latest`;
   - secure backup;
   - record the backup archive path alongside the pre-deploy digest;
   - preserve `PODLY_SECRET_KEY`;
   - `docker compose pull` and `up -d`;
   - automatic migrations;
   - application and real-episode checks.
7. Rollback:
   - prefer the immutable `sha-<full-commit>` tag or recorded digest;
   - retain persistent data;
   - treat schema rollback separately and restore the pre-deploy data backup when an older application is incompatible with a newer schema;
   - verify health after rollback.

### Active summaries

Update these active documents to summarize their audience-specific workflow and link to the canonical runbook:

- `README.md`: short maintainer release and public-image verification section.
- `docs/contributors.md`: correct local-development commands, commit semantics, and the merge-to-image lifecycle.
- `.github/PULL_REQUEST_TEMPLATE.md`: release-impact checklist for migrations, lockfiles, assets, and documentation.
- `AGENTS.md`: release checklist, canonical-runbook pointer, current migration head, and shell guidance matching the Chainguard image.
- Home Lab Obsidian note: source-change-to-image summary, routine deployment, failure behavior, verification, and rollback.

### Historical documents

Keep dated specs/plans unchanged as records, but place a prominent notice at the top of container-release documents pointing to `docs/RELEASE_RUNBOOK.md`. Do not rewrite history.

The required historical notices are:

- `docs/superpowers/specs/2026-07-22-unicorn-branding-and-public-container-design.md`
- `docs/superpowers/plans/2026-07-22-unicorn-public-container-release.md`

Each notice must explicitly say that the document is a preserved historical record, that its operational release instructions are superseded, and that `docs/RELEASE_RUNBOOK.md` is authoritative.

## Drift Prevention

Extend `src/tests/test_container_build_contracts.py` with documentation contracts that read the actual workflow and active documents. The tests will require:

- the canonical runbook exists and is linked by all active repository docs;
- documented image names and tags match the workflow;
- the runbook distinguishes immutable SHA candidates from mutable `latest`;
- the runbook records that semantic-version Docker tags are not currently emitted;
- failure, retry, verification, deployment, rollback, migration, and secret-preservation guidance exists;
- stale statements such as “the image is not published,” routine local production builds, or `bash` as the canonical production-container shell are absent from active docs.

The Home Lab vault is outside the Git repository, so verify it with a dedicated shell audit in the implementation and record the canonical repository runbook URL.

## Scope

This work changes documentation and documentation-contract tests only. It does not change the release workflow, image tags, semantic-release behavior, application code, database schema, or the running Home Lab service.

## Success Criteria

- A maintainer can determine exactly how a change reaches GHCR and how to diagnose a failed release.
- An operator can deploy or roll back without rebuilding or losing persistent state.
- Active documentation has no contradictory image/build/tag instructions.
- Historical records clearly identify the canonical current runbook.
- Automated tests catch future drift between the workflow and active repository documentation.
