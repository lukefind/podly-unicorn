#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/downgrade_db.sh [revision]
# Rolls back the most recent migration (or down to the given revision).

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

# Prefer using repo-local src/instance to avoid writing to /app
export PODLY_INSTANCE_DIR="${PODLY_INSTANCE_DIR:-$REPO_ROOT/src/instance}"

echo "Using PODLY_INSTANCE_DIR=$PODLY_INSTANCE_DIR"
if [ $# -gt 0 ]; then
    pipenv run flask --app ./src/main.py db downgrade "$1"
else
    pipenv run flask --app ./src/main.py db downgrade
fi
