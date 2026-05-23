#!/bin/bash
# One-time migration: state-crypto -> state-crypto-paper (A.1, 2026-05-23).
#
# Phase A.1 splits the single state-crypto named volume into per-mode
# state-crypto-paper and state-crypto-live volumes so a paper-to-live mode
# flip cannot inherit the other mode's peak/drawdown high-water marks.
#
# Spec: docs/decisions/2026-05-22_state_isolation_design.md
#
# Pre-flight assumptions (verify before running):
#  - aaats-paper-crypto is stopped (the source volume must be idle).
#  - The new compose has been merged but NOT yet `up`d (else the new
#    container will already have written empty state into the new volume).
#  - state-crypto-paper does not yet exist (docker creates it on first
#    `-v state-crypto-paper:/to`).
#
# The migration:
#  1. Copy every file from state-crypto:/  into state-crypto-paper:/.
#  2. Rename the legacy filename risk_engine_state.json to
#     risk_engine_state.paper.json so the new engine's per-mode discriminator
#     finds it. (See risk/engine.py::_state_file_path.)
#  3. Print before/after listings so the operator can sanity-check.
#
# Run on the Contabo box as the aaats user:
#  cd /home/aaats/aaats && bash scripts/migrate_state_to_per_mode.sh
#
# This script is idempotent: re-running after a successful migration is a
# no-op (the legacy file no longer exists in state-crypto-paper).

set -euo pipefail

echo "=================================================================="
echo "  A.1 state migration: state-crypto -> state-crypto-paper"
echo "=================================================================="

# Pick the source volume:
#  1. SRC_VOL env override (operator-supplied).
#  2. The compose-prefixed `deployment_state-crypto` if it exists AND contains
#     a `risk_engine_state.json` (the legacy filename) -- this is the path
#     the box actually uses, observed empirically 2026-05-23.
#  3. The unprefixed `state-crypto` (the original design).
#  4. Fatal if neither exists.
_have_volume() {
    docker volume inspect "$1" >/dev/null 2>&1
}
_volume_has_legacy_state() {
    docker run --rm -v "$1:/probe:ro" alpine \
        sh -c 'test -f /probe/risk_engine_state.json' >/dev/null 2>&1
}

if [ -n "${SRC_VOL:-}" ]; then
    :  # operator override -- trust it
elif _have_volume "deployment_state-crypto" && _volume_has_legacy_state "deployment_state-crypto"; then
    SRC_VOL="deployment_state-crypto"
elif _have_volume "state-crypto" && _volume_has_legacy_state "state-crypto"; then
    SRC_VOL="state-crypto"
elif _have_volume "deployment_state-crypto"; then
    SRC_VOL="deployment_state-crypto"
elif _have_volume "state-crypto"; then
    SRC_VOL="state-crypto"
else
    echo "FATAL: neither 'state-crypto' nor 'deployment_state-crypto' exists."
    echo "Candidates on this host:"
    docker volume ls --format '{{.Name}}' | grep -i state-crypto || echo "  (none)"
    exit 1
fi

DST_VOL="${DST_VOL:-state-crypto-paper}"
echo "Resolved source volume: ${SRC_VOL} -> ${DST_VOL}"

echo
echo "[1/4] Source volume contents (BEFORE):"
docker run --rm -v "${SRC_VOL}:/from:ro" alpine sh -c "ls -la /from || true"

echo
echo "[2/4] Copying ${SRC_VOL} -> ${DST_VOL}..."
docker run --rm \
    -v "${SRC_VOL}:/from:ro" \
    -v "${DST_VOL}:/to" \
    alpine sh -c "cp -a /from/. /to/ && echo 'cp OK'"

echo
echo "[3/4] Renaming legacy risk_engine_state.json -> risk_engine_state.paper.json..."
docker run --rm -v "${DST_VOL}:/to" alpine sh -c '
    if [ -f /to/risk_engine_state.json ]; then
        mv /to/risk_engine_state.json /to/risk_engine_state.paper.json
        echo "renamed risk_engine_state.json -> risk_engine_state.paper.json"
    else
        echo "(no legacy risk_engine_state.json present; rename skipped)"
    fi
'

echo
echo "[4/4] Destination volume contents (AFTER):"
docker run --rm -v "${DST_VOL}:/to:ro" alpine sh -c "ls -la /to"

echo
echo "=================================================================="
echo "  Migration complete."
echo "  Source volume ${SRC_VOL} is UNTOUCHED -- safe rollback for 7+ days."
echo "  Verify the new engine reads ${DST_VOL}/risk_engine_state.paper.json"
echo "  before deleting the legacy volume."
echo "=================================================================="
