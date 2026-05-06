#!/usr/bin/env bash
# AAATS κ1 — apply Alembic baseline migration 0001 to a Postgres instance.
#
# Refuses to run unless:
#   1. AAATS_PG_DSN env var is set.
#   2. A v5 snapshot exists (env var AAATS_K1_SNAPSHOT_DIR points to a verified
#      snapshot dir; verification can be done with k1_verify_restore.sh).
#
# Idempotent — Alembic's migration table tracks state; re-running is a no-op
# once 0001 is applied.

set -euo pipefail

if [[ -z "${AAATS_PG_DSN:-}" ]]; then
  echo "ERROR: AAATS_PG_DSN env var is required." >&2
  echo "  example: postgresql+psycopg2://aaats:<pwd>@localhost:5432/aaats" >&2
  exit 2
fi

if [[ -z "${AAATS_K1_SNAPSHOT_DIR:-}" ]]; then
  echo "ERROR: AAATS_K1_SNAPSHOT_DIR must point to a verified snapshot dir." >&2
  echo "  Run scripts/k1_export_v5_snapshots.sh first, then" >&2
  echo "  scripts/k1_verify_restore.sh <snapshot-dir>." >&2
  exit 3
fi
if [[ ! -d "$AAATS_K1_SNAPSHOT_DIR" ]]; then
  echo "ERROR: snapshot dir not found: $AAATS_K1_SNAPSHOT_DIR" >&2
  exit 4
fi

cd "$(dirname "$0")/.."   # → v6-stack/

if ! command -v alembic >/dev/null 2>&1; then
  echo "ERROR: alembic not installed (pip install -r storage/requirements.txt)" >&2
  exit 5
fi

echo "applying migration 0001 to $(echo "$AAATS_PG_DSN" | sed -E 's|//[^@]+@|//***:***@|')…"
alembic -c alembic/alembic.ini upgrade 0001
echo
echo "current revision:"
alembic -c alembic/alembic.ini current
