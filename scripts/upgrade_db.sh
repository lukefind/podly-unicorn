#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/upgrade_db.sh
# Applies all pending database migrations.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

# Prefer using repo-local src/instance to avoid writing to /app
export PODLY_INSTANCE_DIR="${PODLY_INSTANCE_DIR:-$REPO_ROOT/src/instance}"

echo "Using PODLY_INSTANCE_DIR=$PODLY_INSTANCE_DIR"
pipenv run flask --app ./src/main.py db upgrade
