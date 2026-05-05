#!/usr/bin/env bash
# AAATS κ1 — verify a snapshot directory's restorability (κ1 req 2).
#
# For each snapshot file: opens it, verifies SHA-256 matches the recorded
# hash, and runs `PRAGMA integrity_check` to validate the SQLite contents.
# Read-only; no mutation.

set -euo pipefail

SNAP_DIR="${1:-}"
if [[ -z "$SNAP_DIR" || ! -d "$SNAP_DIR" ]]; then
  echo "usage: $0 <snapshot_dir>" >&2
  echo "  example: $0 ./v6-stack/k1-snapshots/20260505T120000Z" >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "ERROR: sqlite3 binary required" >&2
  exit 2
fi

fail=0
ok=0
for db in "$SNAP_DIR"/*.db; do
  [[ -e "$db" ]] || continue
  name="$(basename "$db")"
  hash_file="${db}.sha256"

  if [[ ! -f "$hash_file" ]]; then
    echo "FAIL  $name  (sha256 file missing)"
    fail=$((fail+1))
    continue
  fi

  expected="$(awk '{print $1}' "$hash_file")"
  actual="$(sha256sum "$db" | awk '{print $1}')"
  if [[ "$expected" != "$actual" ]]; then
    echo "FAIL  $name  (sha256 mismatch — expected=${expected} actual=${actual})"
    fail=$((fail+1))
    continue
  fi

  ic="$(sqlite3 "$db" 'PRAGMA integrity_check;' 2>&1 || echo 'ERR')"
  if [[ "$ic" != "ok" ]]; then
    echo "FAIL  $name  (sqlite integrity_check returned: $ic)"
    fail=$((fail+1))
    continue
  fi

  echo "PASS  $name"
  ok=$((ok+1))
done

echo
echo "verified $ok PASS, $fail FAIL"
if [[ $fail -gt 0 ]]; then
  exit 3
fi
