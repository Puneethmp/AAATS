#!/usr/bin/env bash
# κ2 — one-shot capture of the golden baseline.
# Usage:
#   bash v6-stack/scripts/k2_capture_baseline.sh           # refuses if baseline already exists
#   bash v6-stack/scripts/k2_capture_baseline.sh --force   # overwrite

set -euo pipefail

FORCE=${1:-}
HERE="$(dirname "$(realpath "$0")")"
WORKSPACE="$(realpath "$HERE/../..")"
TAPE="$WORKSPACE/data/crypto.db"
OUT="$WORKSPACE/v6-stack/replay/golden/baseline.jsonl"

if [[ -f "$OUT" && "$FORCE" != "--force" ]]; then
  echo "$OUT already exists; pass --force to re-capture." >&2
  exit 1
fi
if [[ ! -f "$TAPE" ]]; then
  echo "tape source not found: $TAPE" >&2
  exit 2
fi

cd "$WORKSPACE"
python v6-stack/replay/runner.py \
  --mode=capture \
  --tape-source="$TAPE" \
  --out="$OUT"

echo
echo "captured: $(wc -l < "$OUT") events → $OUT"
echo "sha256:   $(sha256sum "$OUT" | awk '{print $1}')"
