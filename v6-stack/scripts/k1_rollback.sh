#!/usr/bin/env bash
# AAATS κ1 — rollback migration 0001 (drops aaats + compliance schemas).
#
# Destructive. Refuses to run unless CONFIRM-K1-ROLLBACK is passed as arg.
# Use ONLY when:
#   - migration 0001 has been applied to a database that was never in
#     production use (e.g. test/staging), OR
#   - operator has explicitly authorised destruction (see K1_MANIFEST.md
#     "Rollback procedure").

set -euo pipefail

CONFIRM="${1:-}"
if [[ "$CONFIRM" != "CONFIRM-K1-ROLLBACK" ]]; then
  cat >&2 <<USAGE
DESTRUCTIVE OPERATION — refusing to run without explicit confirmation.

To proceed:
  $0 CONFIRM-K1-ROLLBACK

This will execute Alembic downgrade for revision 0001:
  DROP SCHEMA aaats CASCADE;
  DROP SCHEMA compliance CASCADE;

All v6 substrate state will be lost. v5 SQLite files are untouched, but a
fresh v5 snapshot is recommended before running this.
USAGE
  exit 1
fi

if [[ -z "${AAATS_PG_DSN:-}" ]]; then
  echo "ERROR: AAATS_PG_DSN env var is required." >&2
  exit 2
fi

cd "$(dirname "$0")/.."

if ! command -v alembic >/dev/null 2>&1; then
  echo "ERROR: alembic not installed" >&2
  exit 3
fi

echo "downgrading migration 0001 → base on $(echo "$AAATS_PG_DSN" | sed -E 's|//[^@]+@|//***:***@|')…"
alembic -c alembic/alembic.ini downgrade base
echo "rollback complete; both schemas dropped."
