# Prune Log (Phase 1)

> Archive safety net: branch + tag **`archive/pre-prune-2026-06-10`** at commit
> `3786b100` capture all code prior to this prune. Every deletion below is
> reversible via `git checkout archive/pre-prune-2026-06-10 -- <path>`.
> Date: 2026-06-10.

## Posture

This session makes **repo-side changes only** — the trading container is NOT
redeployed (research-bed framing, perp reconfig skipped). Therefore:

- **Deleted now:** only code with **zero live dependents** and zero effect on the
  running container — verified by import-graph grep.
- **Staged (NOT deleted now):** anything wired into the live runner. Deleting it
  from the repo without a matching deploy would make the repo lie about the box.
  These are listed as the payload for a later, explicitly-confirmed deploy.

## Deleted (verified zero dependents)

| Path | Why | Dependency check |
|---|---|---|
| `=2.0` | Stray pip-install log accidentally captured as a filename (`pip install "pydantic>=2.0"` redirected to a file). Pure garbage. | not imported; not referenced; git-tracked junk |
| `tools/backtest/_c3_regime_gate_oneoff.py` | Throwaway one-off (leading `_`) behind the B.1.5 Phase-5 regime-gate finding. Canonical harness `tools/backtest/run_b15_c3.py` + `c3_replay.py` retained. | `grep -rl` → 0 importers |
| `tools/backtest/_c3_walkforward_oneoff.py` | Throwaway one-off behind the B.1.5 Phase-4 walk-forward finding. | 0 importers |
| `tools/backtest/_slip_sweep_oneoff.py` | Throwaway slippage-sweep one-off. | 0 importers |

Post-delete check: `import tools.backtest` succeeds; no module references the
removed files; test suite unaffected.

## Staged for deploy-coupled removal (NOT deleted this session)

These failed validation and add risk/noise per the mandate, but each is imported
by `trading/live_paper_runner.py` (the live loop). Removing them requires editing
the runner + redeploying so the repo and box stay in sync. Recommended payload
for the next confirmed deploy:

| Component | File(s) | Status | Action |
|---|---|---|---|
| C5b funding-arb | `trading/funding_arb.py` | disabled at source (`halted_src`); known $25/$50 asymmetry bug | delete module + runner import/call |
| C2 momentum breakout | `trading/momentum_breakout.py` | FAIL (memory: C2 verdict); no trades in window | delete module + runner import/call |
| C1 / C3 / C6 live strategies | `trading/stat_arb.py`, `trading/altcoin_reversion.py`, `trading/bollinger_range.py` | NO EDGE (AUDIT/loss_attribution.md) | **demote to no-trade** (disable entries) rather than delete — backtest tooling + research provenance depend on them |
| XGBoost ML gate | `_score_ml`/`_ml_position_scale` in runner, `data/ml/*` | stale 33.9d, val_acc 0.55 (near-random), and bypassed by C3/C6 | remove the gate (dead weight) per mandate, OR retrain walk-forward |

## Catalogued, NOT actioned (provenance / low-value-to-delete)

- **27 one-time deploy scripts** (`scripts/deploy_*.py`, `tools/operator/deploy_*.py`):
  historical, spent. Low risk to delete but they document how past fixes shipped.
  Recommend a separate housekeeping pass, not bundled with structural work.
- **12 root status docs** (`*_COMPLETE.md`, `AUTONOMOUS_*.md`, `MASTER_*.md`):
  doc clutter. CLAUDE.md's doc philosophy keeps earlier decisions for history, so
  these are retained pending an explicit "archive old status docs" decision.

## Clean-restart confirmation

Repo imports cleanly after deletion (`import tools.backtest` OK). No live module
referenced a deleted file. The running container is untouched (no deploy), so its
health is unaffected by this prune.
