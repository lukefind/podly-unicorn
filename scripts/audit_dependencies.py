"""Audit every exact pin in both Pipenv locks, including other platforms.

The locks already contain resolved transitive dependencies. Omitting their
environment markers audits Windows/macOS/Linux entries on any CI runner, without
installing packages or downloading model wheels. No findings are suppressed.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def audit_lock(lock_path: Path) -> int:
    lock = json.loads(lock_path.read_text())
    requirements = set()
    for category in ("default", "develop"):
        for name, package in lock[category].items():
            version = package.get("version", "")
            if not version.startswith("==") or "*" in version:
                raise ValueError(f"{lock_path.name}: {name} must have an exact pin")
            requirements.add(f"{name}{version}")

    print(f"Auditing {lock_path.name}: {len(requirements)} locked packages", flush=True)
    with tempfile.TemporaryDirectory(prefix="podly-audit-") as directory:
        path = Path(directory) / "requirements.txt"
        path.write_text("\n".join(sorted(requirements)) + "\n")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--strict",
                "--no-deps",
                "--disable-pip",
                "--progress-spinner=off",
                "-r",
                str(path),
            ],
            check=False,
        )
    if result.returncode < 0:
        print(
            f"{lock_path.name}: scanner terminated by signal {-result.returncode}",
            file=sys.stderr,
        )
        return 2
    return result.returncode


def main() -> int:
    paths = [Path(argument) for argument in sys.argv[1:]] or [
        REPOSITORY_ROOT / "Pipfile.lock",
        REPOSITORY_ROOT / "Pipfile.lite.lock",
    ]
    status = 0
    for path in paths:
        try:
            status = max(status, audit_lock(path))
        except (OSError, ValueError, KeyError) as error:
            print(f"Dependency audit failed: {error}", file=sys.stderr)
            status = max(status, 2)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
