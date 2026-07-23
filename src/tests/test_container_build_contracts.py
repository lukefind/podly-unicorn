from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
