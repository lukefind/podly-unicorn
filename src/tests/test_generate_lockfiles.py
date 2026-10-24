"""Exercise lock generation without resolving or installing any packages."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("outside_repository", [False, True])
@pytest.mark.parametrize("fail_lite", [False, True])
def test_generate_lockfiles_preserves_both_manifests_and_outputs(
    tmp_path, outside_repository, fail_lite
):
    repository = tmp_path / "project with spaces"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "generate_lockfiles.sh"
    shutil.copyfile(REPOSITORY_ROOT / "scripts/generate_lockfiles.sh", script)
    for name, content in (("Pipfile", "FULL"), ("Pipfile.lite", "LITE")):
        (repository / name).write_text(content)
        (repository / f"{name}.lock").write_text(f"OLD {content}")

    binaries = tmp_path / "bin"
    binaries.mkdir()
    pipenv = binaries / "pipenv"
    pipenv.write_text(
        "#!/bin/sh\n"
        'manifest="${PIPENV_PIPFILE:-Pipfile}"\n'
        'if [ "$1" != lock ]; then exit 99; fi\n'
        'if [ "$PODLY_TEST_FAIL_LITE" = 1 ] && '
        '[ "$(cat "$manifest")" = LITE ]; then exit 17; fi\n'
        'cp "$manifest" "$manifest.lock"\n'
    )
    pipenv.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("PIPENV_PIPFILE", None)
    environment["PATH"] = f"{binaries}{os.pathsep}{environment['PATH']}"
    environment["PODLY_TEST_FAIL_LITE"] = "1" if fail_lite else "0"

    result = subprocess.run(
        ["bash", str(script)],
        cwd=tmp_path if outside_repository else repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == (17 if fail_lite else 0), result.stderr
    assert (repository / "Pipfile").read_text() == "FULL"
    assert (repository / "Pipfile.lite").read_text() == "LITE"
    assert (repository / "Pipfile.lock").read_text() == "FULL"
    assert (repository / "Pipfile.lite.lock").read_text() == (
        "OLD LITE" if fail_lite else "LITE"
    )
    assert not (repository / "Pipfile.tmp").exists()
