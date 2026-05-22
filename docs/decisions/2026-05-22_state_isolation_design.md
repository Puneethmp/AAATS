# Phase A.1 — State isolation design (read-only)

**Status:** DRAFT design — NO code edits this session. Implementation lands in session 4 per the rebuild plan.
**Authored:** 2026-05-22
**Closes:** Sub-task [4] of session 3 prompt.
**Parent plan:** [`2026-05-22_live_flip_rebuild_plan.md`](2026-05-22_live_flip_rebuild_plan.md) §A.1.
**Cross-refs:** [`2026-05-21_live_flip_mechanism_gaps.md`](../known_issues/2026-05-21_live_flip_mechanism_gaps.md) §"Gap 1 — risk state inherits across mode boundary".

## Problem statement

Today there is exactly **one** `risk_engine_state.json` per container, regardless of `SYSTEM__TRADING_MODE`:

- `risk/engine.py:44-46`:
  ```python
  STATE_FILE = Path(
      os.environ.get("AAATS_RISK_STATE_FILE",
                     "/app/data/state/risk_engine_state.json")
  )
  ```
- The state is persisted to the named Docker volume `state-crypto` (per compose `aaats-paper-crypto` service at `deployment/docker-compose.yml:88`). The volume survives container recreation, so peak/last_equity/market_peaks survive `compose up --build`.
- When the operator flips mode (paper → live) via `scripts/deploy_live_flip.py`, the env-var `SYSTEM__TRADING_MODE` changes but **the same `STATE_FILE` path is reused**. The live container inherits the paper container's peak ($131.32 on 2026-05-22) and its current drawdown (-33.4% as of the post-deploy PF1).

That inheritance is the wrong default. Live trading should start with a fresh peak (the operator's actual deposit), not with paper-mode marks-to-market from a stack that just took a -33% drawdown. The NO-GO investigation called this out as "Gap 1" of the four live-flip mechanism gaps.

## Goals

1. **Mode-isolated peaks and drawdowns.** A paper-mode session must not raise/depress the live-mode peak, and vice versa.
2. **Backwards compatible default.** Existing single-mode paper deployments must continue to work without operator intervention; the discriminator activates only when present.
3. **Container restart safety.** Whichever mode is active when the container restarts, its state must survive the restart untouched (named-volume requirement; see §"Volume implications" below).
4. **Test path coverage.** Switching modes mid-test (pytest fixtures) must rebind cleanly without leaking state across tests.

Non-goals for A.1:
- Implementing the live trade loop itself. That's Phase A.2.
- Migrating live-broker DRY_RUN state (deferred to A.2).
- Cross-mode reconciliation between paper and live ledgers. The two are deliberately isolated; reconciliation is an A.4+ concern.

## Proposed mechanism — env-var discriminator + per-mode volume

### Code change (one file, one block)

`risk/engine.py:44-46` becomes:

```python
def _state_file_path() -> Path:
    """Return the per-mode risk-engine state file path.

    Discriminator precedence (highest first):
      1. AAATS_RISK_STATE_FILE — fully-qualified override (already supported).
      2. SYSTEM__TRADING_MODE + AAATS_RISK_STATE_DIR — composed path.
      3. Legacy default: /app/data/state/risk_engine_state.json (no mode suffix).

    The legacy default preserves backwards compatibility for callers that
    don't set SYSTEM__TRADING_MODE (test paths, local scripts). Production
    sets the mode env var via compose, so it gets the per-mode path.
    """
    explicit = os.environ.get("AAATS_RISK_STATE_FILE")
    if explicit:
        return Path(explicit)
    mode = os.environ.get("SYSTEM__TRADING_MODE")
    state_dir = Path(os.environ.get("AAATS_RISK_STATE_DIR",
                                    "/app/data/state"))
    if mode in ("paper", "live"):
        return state_dir / f"risk_engine_state.{mode}.json"
    return state_dir / "risk_engine_state.json"

STATE_FILE = _state_file_path()
```

The `STATE_FILE` module-level constant becomes a one-shot call to the function at import time. The function is exposed for tests so they can rebind the path under monkeypatch.

### Compose change (one service, one block)

`deployment/docker-compose.yml` `aaats-paper-crypto` service: replace the single named volume mount with two mounts under per-mode directories:

```yaml
    volumes:
      - ../logs:/app/logs
      - ../data:/app/data
      - ../scripts:/app/scripts
      - state-crypto-paper:/app/data/state-paper
      - state-crypto-live:/app/data/state-live
    environment:
      - AAATS_RISK_STATE_DIR=/app/data/state-${SYSTEM__TRADING_MODE:-paper}
```

And add the two named volumes to the `volumes:` block at the bottom. The compose-level `${SYSTEM__TRADING_MODE}` interpolation routes the same physical container to `state-paper/` or `state-live/` based on the env var.

**Migration note:** the existing single `state-crypto` volume holds the current paper peak ($131.32). On first cutover, that volume contents must be copied to `state-crypto-paper` so paper-mode resumes with its history intact:

```bash
docker run --rm -v state-crypto:/from -v state-crypto-paper:/to alpine \
    sh -c "cp -a /from/. /to/"
```

This is a one-time on-box migration, scripted in `scripts/migrate_state_to_per_mode.sh` (deferred to implementation).

### Live-mode initial-peak handling

When `state-crypto-live` is first created (no prior file), `risk/engine.py:load_state` already handles the "no state file" case by treating peak as initial-equity. The first live container start writes the operator's actual deposit amount as the peak.

The session-4 implementation also wants a `scripts/seed_live_peak.py` helper so the operator can pre-seed the live peak with the doctrine $25 first-tranche amount before the first cycle, avoiding a 1-cycle gap where peak == 0.

## Volume implications

Three properties of the named-volume approach:

1. **Atomicity.** Each per-mode volume is independent. A paper-mode drawdown breach (-15% halt) does not write to `state-crypto-live`, so it does not trigger a live-mode halt and vice versa. This is the load-bearing invariant.
2. **Restart survival.** Both volumes persist across `compose up --build`. A paper-mode container restart preserves paper peak; flipping to live mounts a different volume with its own peak. Round-trip safe.
3. **Disk footprint.** Each volume holds a single JSON of <1 KB. Cost is negligible.

Trade-off **not** chosen:

- **Single state file, mode-keyed dict** (`{"paper": {...}, "live": {...}}`). Compact but couples write paths — a buggy mode-key lookup could silently read the wrong peak. The two-file design fails-loudly: a missing `risk_engine_state.live.json` returns an obvious "no state" answer to `load_state`, never a paper peak.
- **Per-container compose service.** Cleanest isolation but doubles container count, RAM, and image rebuild time. A.1 explicitly stays single-container with mode as an env-var flag (per the NO-GO doc's Gap 1+3 prescription).

## Test plan (deferred to session 4 implementation)

| Test | Assertion |
|------|-----------|
| `test_state_isolation::test_paper_mode_writes_paper_state` | `SYSTEM__TRADING_MODE=paper` → writes go to `risk_engine_state.paper.json` only. |
| `test_state_isolation::test_live_mode_writes_live_state` | Same, mirrored for live. |
| `test_state_isolation::test_paper_peak_survives_live_session` | Write paper peak → flip mode → write live state → flip back → paper peak unchanged. |
| `test_state_isolation::test_legacy_default_when_no_mode_env` | Without `SYSTEM__TRADING_MODE` set, falls back to legacy `risk_engine_state.json` path (back-compat for scripts). |
| `test_state_isolation::test_explicit_override_wins` | `AAATS_RISK_STATE_FILE=/tmp/foo.json` overrides the per-mode discriminator. |

## What this memo does NOT propose

- Touching any non-`risk/engine.py` writer of state JSON. The other 4 D.3-validated state files (`heartbeat.json`, `halt_state.json`, `paper_positions.json`, `share_equality_mismatches.json`) are mode-agnostic by construction; the runner writes them with the current mode's data, and on mode flip they are naturally overwritten by the new mode's first cycle. Per-mode isolation for those files would be more harm than help.
- Flipping `mode=live` for any production container. This memo prepares the state plumbing for A.2's DRY_RUN broker; the flip is gated by the Track C criteria (C.1–C.5) unchanged.

## Operator review checkpoints

- The compose change touches a named volume layout, which is a non-trivial config edit per the autonomy contract. Operator should sign off before the compose edit lands on box (workstation edit + tests can proceed under technical autonomy).
- The one-time migration script `scripts/migrate_state_to_per_mode.sh` runs on box. Operator should review the rsync/cp output before cutover.

## Status log

- **2026-05-22 (session 3)** — Design memo authored. NO code edits this session.
  Implementation queued for session 4 with the above test list as the
  pass criterion. Operator review of the compose change (per-mode named
  volumes + ENV interpolation) is the only hard gate before session-4
  implementation can land.
