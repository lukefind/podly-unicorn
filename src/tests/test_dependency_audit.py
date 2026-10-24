"""Check that the security gate covers both lock variants and every platform."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("scanner_exit", [0, 1, -15])
def test_dependency_audit_checks_all_locked_packages_and_propagates_failures(
    tmp_path, scanner_exit
):
    scanner = tmp_path / "pip_audit.py"
    scanner.write_text(
        "import os, pathlib, sys\n"
        "requirements = pathlib.Path(sys.argv[sys.argv.index('-r') + 1])\n"
        "with pathlib.Path(os.environ['AUDIT_LOG']).open('a') as log:\n"
        "    log.write(requirements.read_text() + '\\n')\n"
        "status = int(os.environ['AUDIT_EXIT'])\n"
        "if status < 0: os.kill(os.getpid(), -status)\n"
        "sys.exit(status)\n"
    )
    locks = []
    for name in ("Pipfile.lock", "Pipfile.lite.lock"):
        lock = tmp_path / name
        lock.write_text(
            json.dumps(
                {
                    "default": {
                        "flask": {"version": "==3.1.3"},
                        "windows-only": {
                            "version": "==1.0",
                            "markers": "sys_platform == 'win32'",
                        },
                    },
                    "develop": {"black": {"version": "==26.10.1"}},
                }
            )
        )
        locks.append(str(lock))
    log = tmp_path / "audit.log"
    environment = os.environ.copy()
    environment.update(
        PYTHONPATH=str(tmp_path), AUDIT_LOG=str(log), AUDIT_EXIT=str(scanner_exit)
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "scripts/audit_dependencies.py"),
            *locks,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == (2 if scanner_exit < 0 else scanner_exit), result.stderr
    audited = log.read_text()
    for requirement in ("flask==3.1.3", "windows-only==1.0", "black==26.10.1"):
        assert audited.count(requirement) == 2
