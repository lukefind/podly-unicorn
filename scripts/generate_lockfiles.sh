#!/bin/bash
set -euo pipefail

REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

# Generate lock file for the regular Pipfile
echo "Locking Pipfile..."
PIPENV_PIPFILE="${REPOSITORY_ROOT}/Pipfile" pipenv lock

# Pipenv names each lock after its manifest; keep the full lock and both
# manifests in place even if the lite resolution fails.
echo "Locking Pipfile.lite..."
PIPENV_PIPFILE="${REPOSITORY_ROOT}/Pipfile.lite" pipenv lock

echo "Lockfiles generated successfully!"
echo "- Pipfile.lock"
echo "- Pipfile.lite.lock"
