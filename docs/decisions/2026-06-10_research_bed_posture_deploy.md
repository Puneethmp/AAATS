# 2026-06-10 — Research-bed posture deploy (ML gate removed, C2/C5b deleted, C1/C3/C6 no-trade, ledger net-of-cost)

**Status:** DEPLOYED + VERIFIED 2026-06-10T17:12Z
**Operator confirmation:** explicit go in the 2026-06-10 session ("prepare and
execute the box deploy for #1 (remove gate) + #2 + #3"), key rotation handled
separately by the operator.
**Commit:** `1c39dde3` (workstation) · **Deploy script:**
`tools/operator/deploy_research_bed_posture_2026_06_10.py` · **Rollback:**
`.rollback/2026-06-10_research_bed_posture/MANIFEST.txt` (box backups
`.bak-20260610T170412Z`, removed modules `.removed-20260610T170412Z`).

## What shipped (the [STAGED] items from AUDIT/structural_fixes.md)

1. **ML gate removed** (FIX 2). `_score_ml` / `_ml_position_scale` /
   `_init_ml_ensemble` deleted from `trading/live_paper_runner.py`; gate call
   sites in both market loops and the `ml_size_scale` plumbing in `execute()`
   removed. Rationale: model stale 33.9d, val_acc 0.5508 (near-random), and
   the gate never covered C3/C6 — dead weight. `ml/model_health.py` remains
   the guard if a model ever returns.
2. **C5b + C2 deleted** (prune_log). `trading/funding_arb.py` and
   `trading/momentum_breakout.py` removed from repo AND box tree (mv'd, not
   rm'd); runner dispatch removed. Historical DB rows keep their strategy
   names.
3. **C1/C3/C6 demoted to no-trade.** `ENTRIES_DISABLED = True` module
   constants: runner `execute()` blocks BUY before any gate/sizing work;
   each strategy's entry block skips. Exits / ATR stops / per-trade stops /
   MTM all still run — the open book winds down to flat. India path included.
   Tests flip the attribute via monkeypatch where they exercise entry logic.
4. **Honest-PnL at write time** (FIX 1). Every realized record site writes
   `pnl` NET of `analytics/cost_model` costs: C3/C6 exits and C1's two close
   legs net fees+modeled slippage (raw-price fills); runner `execute()` SELL
   and ATR-stop paths net fees only (their fills already model slippage via
   `_fill_price` — adding slippage_bps would double-count). Gross + cost
   breakdown preserved per-row in `notes` JSON (`gross_pnl`, `costs`).
   Portfolio capital updates use the same net figure, so the L11 capital
   invariant (expected = start + DB.realized_pnl − open notional) stays
   consistent. L5 ledger-divergence is unaffected (it compares `size_usd`
   notionals, not pnl).

## Post-deploy verification (all four operator criteria)

| Criterion | Evidence |
|---|---|
| No live strategy trading | Startup banner `Posture: RESEARCH BED — entries disabled (True)`; in-container flags `True True True True` (runner, C1, C3, C6); cycle 1 (17:13Z) logged `[c3] DEMOTED … 4 open`, `[c6] DEMOTED … 1 open`, zero ENTRY lines; summary `C1=idle C2=idle C3=hold(4) C5b=halted_src C6=idle` |
| Ledger writes net-of-cost | First post-deploy exit, SAHARA/USDT SELL 17:13:11Z: `pnl=0.135614` = `gross_pnl 0.173954 − costs 0.038339` (notes JSON), `pnl_pct` net 1.4278 vs gross move 1.83% |
| Health checks green | `aaats-paper-crypto Up (healthy)`; all siblings up (grafana/prometheus/metrics/watchdog/telegram-bot/dashboard untouched); exporter :9091 emitting 280 `aaats_` series; Telegram smoke ok + pre/post alerts sent; cycle 1 completed in ~33s after warmup |
| Log-push stopped (FIX 4) | `git ls-tree origin/main runtime/` → 0 `.log` files; `runtime/*.log` rule present in origin/main `.gitignore` (propagated via box `reset --hard`) |

C6 wound down its last open position on cycle 1 (take_profit); C3 holds 4
positions in exit-only mode (XRP et al.); C1 book empty. Expect the C3 book
to reach flat via z-targets / 24h time stops within ~a day.

## Follow-ups

- **Operator:** finish API-key rotation (in progress 2026-06-10); run the
  full git-history secret scan (gitleaks/BFG) — last [STAGED] row.
- The `aaats-engine` container still runs the older image (separate stack,
  not part of this deploy's scope).
- Monitoring layers L1–L11 unchanged; L7 activity-floor will now see a
  permanently quiet book once C3 winds down — that alert firing is EXPECTED
  and can be acknowledged or the workflow variable disabled at operator
  discretion (it currently still validates that the cron/DB pipeline works).
