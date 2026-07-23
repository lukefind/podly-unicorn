# Release Documentation Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document and continuously verify the complete path from a Podly source change to the public multi-architecture image and onward to a safe Home Lab deployment or rollback.

**Architecture:** `docs/RELEASE_RUNBOOK.md` becomes the canonical operational source. Active repository documentation and the Home Lab Obsidian note contain audience-specific summaries that link back to it, while dated design documents are preserved with explicit supersession notices. Focused contract tests compare the active documentation with the real GitHub Actions workflow so future changes cannot silently reintroduce contradictory release instructions.

**Tech Stack:** Markdown, GitHub Actions YAML, pytest, PyYAML, Docker/GHCR operational commands, Obsidian Markdown.

---

### Task 1: Add Failing Documentation Contracts

**Files:**
- Modify: `src/tests/test_container_build_contracts.py`
- Test: `src/tests/test_container_build_contracts.py`

- [ ] **Step 1: Add a repository-documentation contract test**

Add a test that reads:

```python
runbook = (REPOSITORY_ROOT / "docs/RELEASE_RUNBOOK.md").read_text()
readme = (REPOSITORY_ROOT / "README.md").read_text()
contributors = (REPOSITORY_ROOT / "docs/contributors.md").read_text()
agents = (REPOSITORY_ROOT / "AGENTS.md").read_text()
pull_request_template = (
    REPOSITORY_ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
).read_text()
```

Require the active documents to link to `docs/RELEASE_RUNBOOK.md`. Require the runbook to contain:

```python
for required in (
    "ghcr.io/lukefind/podly-unicorn",
    "sha-<full-commit>",
    "latest",
    "linux/amd64",
    "linux/arm64",
    "Conventional Commit",
    "PODLY_SECRET_KEY",
    "docker compose pull",
    "rollback",
    "promotion step",
    "semantic-version Docker tags are not currently published",
):
    assert required.lower() in runbook.lower()
```

Read `.github/workflows/docker-publish.yml` through `yaml.safe_load()` and assert the documented image matches the workflow `IMAGE`, the build uses `sha-${{ github.sha }}`, and promotion targets `latest`.

Require the current migration head `r4s5t6u7v8w9` in `AGENTS.md`.

- [ ] **Step 2: Add stale-guidance rejection**

Check active docs (`README.md`, `docs/contributors.md`, `AGENTS.md`) for prohibited claims:

```python
for stale in (
    "the image is not published",
    "do not run `sudo docker compose pull`",
    "sudo docker compose up -d --build",
    "docker exec -it podly-pure-podcasts bash",
):
    assert stale.lower() not in active_docs.lower()
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/python \
  -m pytest -q src/tests/test_container_build_contracts.py \
  -k release_documentation
```

Expected: failure because `docs/RELEASE_RUNBOOK.md` and the required links/content do not yet exist.

- [ ] **Step 4: Commit the failing contract**

```bash
git add src/tests/test_container_build_contracts.py
git commit -m "test: define release documentation contract"
```

### Task 2: Create the Canonical Release Runbook

**Files:**
- Create: `docs/RELEASE_RUNBOOK.md`
- Test: `src/tests/test_container_build_contracts.py`

- [ ] **Step 1: Write the runbook**

Cover all requirements from the approved design:

1. scope, artifact name, supported architectures, and authoritative workflow files;
2. pre-change checklist for migrations, lockfiles, branding/PWA assets, tests, and docs;
3. Conventional Commit release mapping and the fact that every accepted `main` commit may publish a container even without a semantic version;
4. direct push and semantic-release-commit data flows;
5. immutable candidate and `latest` tag behavior, including the absence of semantic-version Docker tags;
6. every release gate in workflow order;
7. failure diagnosis and write-once retry rules;
8. pre-promotion versus promotion-step failure state;
9. manual dispatch constraints;
10. commit/digest/platform/revision/anonymous-pull verification;
11. pre-deploy digest and backup-path recording;
12. Home Lab deployment and automatic migrations;
13. rollback by immutable SHA tag or digest, including schema/data-backup cautions.

Use executable commands with placeholders that clearly identify values the operator must substitute. Never include secrets.

- [ ] **Step 2: Run the focused documentation test**

Run the same `pytest -k release_documentation` command.

Expected: still fails because active-document links and historical notices are not complete.

- [ ] **Step 3: Commit the canonical runbook**

```bash
git add docs/RELEASE_RUNBOOK.md
git commit -m "docs: add canonical container release runbook"
```

### Task 3: Update Active Repository Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/contributors.md`
- Modify: `.github/PULL_REQUEST_TEMPLATE.md`
- Modify: `AGENTS.md`
- Test: `src/tests/test_container_build_contracts.py`

- [ ] **Step 1: Update README**

Add a concise “Maintainer release process” section linking to `docs/RELEASE_RUNBOOK.md`. State that a verified `main` commit becomes an immutable SHA candidate and then `latest`, and that operators must wait for the Build and Publish Container workflow to succeed before pulling.

- [ ] **Step 2: Correct and expand the contributor guide**

Replace obsolete production/development command examples. Production must use the pull-only default:

```bash
./run_podly_docker.sh
```

Development-only build options must include `--dev`, for example:

```bash
./run_podly_docker.sh --dev --build
./run_podly_docker.sh --dev --lite --build
./run_podly_docker.sh --dev --gpu --build
```

Document the merge-to-image lifecycle, Conventional Commit mapping, release/non-release container behavior, required workflows, and canonical-runbook link.

- [ ] **Step 3: Expand the pull-request checklist**

Add conditional checklist items for:

- model migration;
- Python and frontend lockfiles;
- branding/favicon/PWA verification;
- release-impact documentation;
- Conventional Commit release intent.

Link to the canonical runbook.

- [ ] **Step 4: Update AGENTS.md**

Add a “Releases and Public Container” section linking to the runbook and summarizing the required checks and tags. Change production shell examples from `bash` to `sh`. Correct the current migration head to `r4s5t6u7v8w9` and add the four post-`m0n1o2p3q4r5` migrations to the recent history.

- [ ] **Step 5: Run focused tests**

Run:

```bash
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/python \
  -m pytest -q src/tests/test_container_build_contracts.py
```

Expected: documentation tests may still fail only on historical notices; all earlier container contracts remain passing.

- [ ] **Step 6: Commit active documentation**

```bash
git add README.md docs/contributors.md .github/PULL_REQUEST_TEMPLATE.md AGENTS.md
git commit -m "docs: explain change to image release lifecycle"
```

### Task 4: Mark Historical Release Documents Superseded

**Files:**
- Modify: `docs/superpowers/specs/2026-07-22-unicorn-branding-and-public-container-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-unicorn-public-container-release.md`

- [ ] **Step 1: Add preserved-history notices**

Immediately after each title, add a blockquote that says the document is a preserved historical record, its operational release instructions are superseded, and `docs/RELEASE_RUNBOOK.md` is authoritative.

Do not rewrite the historical contents.

- [ ] **Step 2: Extend the contract test**

Require both historical files to contain “preserved historical record,” “superseded,” and the canonical runbook link.

- [ ] **Step 3: Run the complete focused contract suite**

Run:

```bash
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/python \
  -m pytest -q src/tests/test_container_build_contracts.py
```

Expected: all tests pass.

- [ ] **Step 4: Commit historical notices and final contract**

```bash
git add \
  docs/superpowers/specs/2026-07-22-unicorn-branding-and-public-container-design.md \
  docs/superpowers/plans/2026-07-22-unicorn-public-container-release.md \
  src/tests/test_container_build_contracts.py
git commit -m "docs: mark historical container plans superseded"
```

### Task 5: Update the Home Lab Obsidian Runbook

**Files:**
- Modify: `/Users/luke/Nextcloud/Projects, Work, Business/Home Lab/home lab setup 2ba873cae2b680048572f5e607b9ed89.md`

- [ ] **Step 1: Add maintainer publication lifecycle**

Expand the Podly section to explain:

- merge/push to `main`;
- semantic-release may create a release commit;
- wait for Validation, Release, and Build and Publish Container;
- immutable SHA candidate and gated `latest` promotion;
- non-versioned container-tag limitation;
- failure/retry behavior.

Link to:

`https://github.com/lukefind/podly-unicorn/blob/main/docs/RELEASE_RUNBOOK.md`

- [ ] **Step 2: Add pre-deploy recording and rollback**

Before the backup and pull commands, record:

```bash
sudo docker inspect podly-pure-podcasts \
  --format '{{.Config.Image}}' \
  | sudo tee /home/bob/podly-unicorn-pre-deploy-image-2026-07-23.txt
```

Also record the backup path. Add rollback instructions that pin `image:` to `ghcr.io/lukefind/podly-unicorn:sha-<full-commit>` or an immutable digest, preserve the bind mount, and restore the pre-deploy data backup if schema compatibility requires it.

- [ ] **Step 3: Audit the entire vault note**

Require balanced Markdown fences and reject stale Podly statements:

```bash
note='/Users/luke/Nextcloud/Projects, Work, Business/Home Lab/home lab setup 2ba873cae2b680048572f5e607b9ed89.md'
fences=$(rg -c '^```' "$note")
test $((fences % 2)) -eq 0
! rg -n -i \
  'image is not published|do not.*compose pull|pull access denied|podly.*up -d --build' \
  "$note"
```

Expected: exit 0 and no stale matches.

### Task 6: Full Verification and Documentation Audit

**Files:**
- Verify all changed repository and Home Lab files.

- [ ] **Step 1: Run repository tests**

```bash
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/python \
  -m pytest -q src/tests/test_container_build_contracts.py
```

Expected: all tests pass.

- [ ] **Step 2: Validate workflow and formatting**

```bash
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/*.yml
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/black \
  --check src/tests/test_container_build_contracts.py
/Users/luke/.local/share/virtualenvs/podly-unicorn-JtboXT4j/bin/isort \
  --check-only src/tests/test_container_build_contracts.py
git diff --check main...HEAD
```

Expected: all commands exit 0.

- [ ] **Step 3: Run a cross-document stale-guidance audit**

Search active repository Markdown and the Home Lab note for obsolete image names, unpublished-image claims, production local-build instructions, old migration-head claims, and incorrect shell commands. Review every match rather than relying only on prohibited-string tests.

- [ ] **Step 4: Review the requirements line by line**

Compare the final diff with:

- `docs/superpowers/specs/2026-07-23-release-documentation-design.md`
- this implementation plan.

Confirm every success criterion has direct evidence.

- [ ] **Step 5: Request final review**

Dispatch an independent reviewer with the base SHA, head SHA, approved spec, and changed-file list. Resolve all critical or important findings and rerun verification.

- [ ] **Step 6: Integrate and push**

Merge the reviewed documentation branch into `main`, push `main`, monitor Validation, Release, and Build and Publish Container to terminal success, and confirm `latest` reports the final documentation commit as its OCI revision.

Because any accepted `main` commit publishes a container, do not claim completion until this final workflow and public-registry verification succeed.
