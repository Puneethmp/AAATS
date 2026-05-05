#!/usr/bin/env bash
# AAATS κ1 — export full SQLite snapshots + compute SHA-256 hashes (κ1 req 2).
#
# Run BEFORE applying any v5→v6 schema migration. Idempotent — re-running
# overwrites the previous snapshot dir but never touches v5 originals.
#
# Inputs:
#   AAATS_V5_DATA_DIR     (default: ./data)        — root of v5 SQLite files
#   AAATS_K1_SNAPSHOT_DIR (default: ./v6-stack/k1-snapshots)
# Outputs:
#   <SNAPSHOT_DIR>/<timestamp>/{*.db, *.db.sha256, MANIFEST.txt}
#
# Behaviour:
#   - Uses sqlite3's `.backup` command (consistent online snapshot, even if
#     v5 is currently writing — sqlite handles this safely).
#   - Computes SHA-256 of each backup; stores alongside.
#   - Writes MANIFEST.txt listing files + hashes + sizes + source mtimes.
#   - DOES NOT delete or modify any v5 file.

set -euo pipefail

V5_DIR="${AAATS_V5_DATA_DIR:-./data}"
SNAP_ROOT="${AAATS_K1_SNAPSHOT_DIR:-./v6-stack/k1-snapshots}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP_DIR="${SNAP_ROOT}/${TS}"

if [[ ! -d "$V5_DIR" ]]; then
  echo "ERROR: v5 data dir not found: $V5_DIR" >&2
  exit 2
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "ERROR: sqlite3 binary required (apt-get install sqlite3)" >&2
  exit 3
fi

mkdir -p "$SNAP_DIR"
MANIFEST="$SNAP_DIR/MANIFEST.txt"

{
  echo "AAATS κ1 v5 snapshot manifest"
  echo "timestamp_utc: $TS"
  echo "source_dir: $V5_DIR"
  echo "snapshot_dir: $SNAP_DIR"
  echo
  echo "files:"
} > "$MANIFEST"

count=0
for src in "$V5_DIR"/*.db; do
  [[ -e "$src" ]] || continue
  name="$(basename "$src")"
  dst="$SNAP_DIR/$name"
  echo "  -> $name"
  sqlite3 "$src" ".backup '$dst'"
  hash="$(sha256sum "$dst" | awk '{print $1}')"
  echo "$hash  $name" > "${dst}.sha256"
  size="$(stat -c '%s' "$dst")"
  src_mtime="$(stat -c '%y' "$src")"
  printf "  %-32s  %12d B  sha256=%s  src_mtime=%s\n" \
    "$name" "$size" "$hash" "$src_mtime" >> "$MANIFEST"
  count=$((count + 1))
done

if [[ $count -eq 0 ]]; then
  echo "ERROR: no .db files found in $V5_DIR" >&2
  exit 4
fi

echo
echo "snapshotted $count databases → $SNAP_DIR"
echo "manifest: $MANIFEST"
