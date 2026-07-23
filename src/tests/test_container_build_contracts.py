import os
import subprocess
from pathlib import Path

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_launcher(tmp_path, *arguments, nvidia_available=False):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = compose ] && [ "$2" = version ]; then exit 0; fi\n'
        'printf "%s|CUDA=%s\\n" "$*" "$CUDA_VISIBLE_DEVICES" >> "$DOCKER_LOG"\n'
    )
    docker.chmod(0o755)

    if nvidia_available:
        nvidia_smi = fake_bin / "nvidia-smi"
        nvidia_smi.write_text("#!/bin/sh\nexit 0\n")
        nvidia_smi.chmod(0o755)

    environment = os.environ.copy()
    environment["DOCKER_LOG"] = str(docker_log)
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
    result = subprocess.run(
        ["bash", str(REPOSITORY_ROOT / "run_podly_docker.sh"), *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    commands = docker_log.read_text().splitlines() if docker_log.exists() else []
    return result, commands


def _workflow_commands(job):
    return "\n".join(
        step.get("run", "") for step in job["steps"] if isinstance(step, dict)
    )


def test_publication_requires_full_release_acceptance():
    workflow_path = REPOSITORY_ROOT / ".github/workflows/docker-publish.yml"
    workflow = yaml.safe_load(workflow_path.read_text())
    release_tests = workflow["jobs"]["release-tests"]
    publish = workflow["jobs"]["publish"]
    commands = _workflow_commands(release_tests)

    assert publish["needs"] == "release-tests"
    assert publish["if"] == release_tests["if"]
    assert release_tests["permissions"] == {"contents": "read"}
    assert 'python-version: "3.12"' in workflow_path.read_text()
    assert "pipenv install --dev --deploy" in commands
    assert "pipenv run pytest --disable-warnings" in commands
    assert "pipenv run python -m pip check" in commands
    assert "pipenv run python scripts/verify_brand_assets.py" in commands
    assert "npm ci" in commands
    assert "npm test" in commands
    assert "npm run lint -- --max-warnings=0" in commands
    assert "npm run build" in commands
    assert "npm audit --audit-level=high" in commands

    pr_validation = workflow["jobs"]["validate-pr"]
    assert pr_validation["permissions"] == {"contents": "read"}


def test_release_commit_explicitly_dispatches_main_container_publication():
    docker_workflow = (
        REPOSITORY_ROOT / ".github/workflows/docker-publish.yml"
    ).read_text()
    release_workflow_path = REPOSITORY_ROOT / ".github/workflows/release.yml"
    release_workflow = yaml.safe_load(release_workflow_path.read_text())
    release_commands = _workflow_commands(release_workflow["jobs"]["release"])

    for config_name in (".releaserc.json", ".releaserc.cjs"):
        release_config = (REPOSITORY_ROOT / config_name).read_text().lower()
        assert "[skip ci]" in release_config
        assert "chore(release): ${nextrelease.version}" in release_config

    assert release_workflow["permissions"]["actions"] == "write"
    original_sha = release_commands.index("git rev-parse HEAD")
    semantic_release = release_commands.index("semantic-release")
    remote_main = release_commands.index("git ls-remote origin refs/heads/main")
    dispatch = release_commands.index(
        "actions/workflows/docker-publish.yml/dispatches"
    )
    confirmation = release_commands.index("Dispatched container publication")
    assert original_sha < semantic_release < remote_main < dispatch < confirmation
    assert 'if [ "$remote_main" = "$ORIGINAL_SHA" ]' in release_commands
    assert "gh api --method POST" in release_commands
    assert "-f ref=main" in release_commands
    assert "set -euo pipefail" in release_commands

    assert "branches: [main]" in docker_workflow
    assert "workflow_dispatch:" in docker_workflow
    assert "needs: release-tests" in docker_workflow
    assert "Confirm run still targets current main" in docker_workflow


def test_production_defaults_to_fixed_cpu_latest_on_gpu_host(tmp_path):
    result, commands = _run_launcher(tmp_path, nvidia_available=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert commands == ["compose -f compose.yml up|CUDA=-1"]
    assert "Branch tag" not in result.stdout


@pytest.mark.parametrize(
    "option",
    [
        "--build",
        "--test-build",
        "--rebuild",
        "--gpu",
        "--lite",
        "--branch=feature",
        "--cuda=12.6.3",
        "--rocm=7.0",
    ],
)
def test_production_rejects_options_ignored_by_pull_only_compose(tmp_path, option):
    result, commands = _run_launcher(tmp_path, option)

    assert result.returncode != 0
    assert "--dev" in result.stdout
    assert commands == []


def test_development_gpu_and_lite_build_paths_remain_available(tmp_path):
    gpu_result, gpu_commands = _run_launcher(
        tmp_path / "gpu", "--dev", "--gpu", "--build", nvidia_available=True
    )
    lite_result, lite_commands = _run_launcher(
        tmp_path / "lite", "--dev", "--lite", "--build"
    )

    assert gpu_result.returncode == 0, gpu_result.stdout + gpu_result.stderr
    assert gpu_commands == [
        "compose -f compose.dev.cpu.yml -f compose.dev.nvidia.yml build|CUDA=0"
    ]
    assert lite_result.returncode == 0, lite_result.stdout + lite_result.stderr
    assert lite_commands == ["compose -f compose.dev.cpu.yml build|CUDA=-1"]


def test_dev_gpu_base_images_use_python_312_distribution():
    runner = (REPOSITORY_ROOT / "run_podly_docker.sh").read_text()

    assert runner.count(
        'nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu24.04'
    ) == 2
    assert runner.count(
        'rocm/dev-ubuntu-24.04:${ROCM_VERSION}-complete'
    ) == 2
    assert "ubuntu22.04" not in runner
    assert "ubuntu-22.04" not in runner


def test_debian_family_build_installs_python_alias_before_version_assertions():
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text()
    package_install, version_assertions = dockerfile.split(
        "python3 -c 'import sys; assert sys.version_info[:2] == (3, 12)", 1
    )

    assert "python-is-python3" in package_install
    assert "python -c 'import sys; assert sys.version_info[:2] == (3, 12)" in (
        version_assertions
    )


def test_container_pip_supports_externally_managed_distribution_python():
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text()

    override = dockerfile.index("ENV PIP_BREAK_SYSTEM_PACKAGES=1")
    pip_bootstrap = dockerfile.index(
        "python3 -m pip install --no-cache-dir --upgrade --ignore-installed"
    )
    first_install = dockerfile.index("python3 -m pip install")
    assert override < first_install
    assert pip_bootstrap == first_install
