# AAATS Full Repository Audit — 2026-06-13

> ## ✅ TIER 1 IMPLEMENTED 2026-06-13 (operator-approved)
> Dead-code deletion executed in 6 reviewable commits on `main`
> (`19e126d5` → `6741e12b`), safety tag `archive/pre-cleanup-2026-06-13`.
> **Result: 495 → 241 Python files (−51%), 936 → 597 tracked files, ~70,377
> lines deleted.** No container redeploy (the live `aaats-paper-crypto` never
> imported any deleted code; verified flat + healthy after). Full pytest green
> apart from the 3 pre-existing failures + 6 India credential-gated errors
> documented before the cleanup. Commits:
> 1. `19e126d5` — v6-stack/ (87 files)
> 2. `1fa094d1` — 9 orphan packages + tests (~120 files)
> 3. `1a01838d` — in-package dead files + trimmed execution/decision inits
> 4. `a58d2689` — ~70 spent one-off scripts + coupled tests
> 5. `4d7993cc` — ~30 stale build-era root docs + dead workflow
> 6. `6741e12b` — 11 unused deps dropped from requirements
>
> **Corrections applied during implementation (vs the plan below):**
> - `scripts/migrate_positions_to_db.py` was **kept** — it is a real import
>   dependency of `scripts/drain_positions.py` (a kept operator CLI), not dead.
> - `tools/operator/deploy_ledger_flag.py` **kept** — a live test exercises its
>   pure helpers.
> - `_newdir_parity_guard.py` / `_dirty_tree_guard.py` **kept** — still used by
>   `deploy_to_contabo.py` + their tests.
>
> **Tier 2 (strategy consolidation, us/india removal) and Tier 3 (dashboard
> trim) were NOT done** — operator chose Tier 1 only. They remain available as
> separately-approved, rebuild-coupled follow-ups (see §9).

---

> Read-only audit. **No files were changed.** Every classification below is traced
> through actual imports, compose/cron references, and runtime reachability — not
> assumed. Live path = container `aaats-paper-crypto`
> (`trading/paper_loop.py --market crypto` → `live_paper_runner.run_crypto`) plus the
> other *running* compose services (`aaats-metrics`, `aaats-telegram-bot`,
> `aaats-watchdog`) and, in the separate `aaats-base` project, `aaats-dashboard` /
> Grafana / Prometheus. Box cron is the source of truth for "what runs."

## 0. Headline

The repo is **936 tracked files / 495 Python files**. Roughly **half is dead** —
abandoned parallel stacks, an orphaned strategy library that nothing imports, an
institutional-execution cluster never wired in, halted-market code, and ~70 spent
one-off deploy/fix scripts. The live trading system is small: ~40 Python files.

| | files | ~LOC | note |
|---|---|---|---|
| **Fully orphaned (zero importers anywhere)** | ~210 .py + tests | ~28,000 | safe to delete; live container never imports them |
| **Dormant-but-wired (halted us/india)** | ~20 | ~3,200 | dead in practice; removal touches runner + compose |
| **Dashboard-only (live via aaats-dashboard, not trading)** | ~28 | ~3,500 | live; deletable only if you also trim the dashboard |
| **Live trading + monitoring core** | ~45 | ~9,000 | KEEP |
| **Root status-doc clutter (*.md)** | ~30 | — | stale build-era docs |

**The single biggest finding:** the `/strategies` folder you envision *already exists*
(46 files, ~30 strategy implementations) — and **nothing imports it but tests.** The
live strategies are the 3 in `trading/`. So "consolidate strategies into one clean
folder" is mostly a *deletion* problem, not a *construction* problem.

## 1. Reconciliation with the maintenance contract (read this first)

CLAUDE.md (operator-approved 2026-06-11) forbids code changes except security and
T3-collector fixes without sign-off. This audit changes nothing. Implementation is
gated on your approval and splits cleanly by risk:

- **Tier 1 — dead-code deletion (LOW risk, no redeploy):** deleting packages the live
  container *never imports* cannot affect the running system. The container keeps
  running the image it already has; the only effect is a smaller repo and a smaller
  *next* image. Risk is limited to test-collection/CI (delete orphan tests with their
  packages). **This is ~90% of the cleanup value.**
- **Tier 2 — changes to live-imported code (MEDIUM risk, needs coordinated rebuild):**
  strategy consolidation (moving `trading/` strategies, rewriting runner imports) and
  removing the dormant us/india cluster touch files baked into the container → requires
  the paramiko deploy + container rebuild, exactly like the 2026-06-10 deploy.
- **Tier 3 — dashboard trim (MEDIUM risk, needs dashboard rebuild):** removing the
  `page_institutional` cluster.

I recommend **Tier 1 now** (huge win, near-zero risk) and treating Tier 2/3 as
separate, explicitly-approved follow-ups. See §9.

---

## 2. Deliverable 1 — Full classification (by package)

### 2a. REMOVE — fully orphaned packages (zero importers outside themselves/tests)

| package | files | ~LOC | evidence | archive-first? |
|---|---|---|---|---|
| `v6-stack/` | 38 | 4,666 | abandoned parallel "v6/CP-3" stack (own compose/alembic/systemd). Only ref: `tools/operator/_newdir_parity_guard.py`. Live `aaats-base` uses `/srv/aaats/compose/`, NOT these files. | yes (git tag) |
| `strategies/` | 46 | 3,150 | imported only by `tests/test_strategies/` + internal `registry.py`. Zero live import. Toy `generate_signals` stubs, a different paradigm from the live engines. | partial (see §6) |
| `portfolio/` | 12 | 3,780 | zero importers; runner's `portfolio` is a **local dict** from `paper_portfolio.json`, not this package. | no |
| `safety/` | 5 | 1,640 | only `scripts/safety_check.py` (manual CLI) + `live_safety_lock` self-refs. Not on any container path. | no |
| `diagnostics/` | 6 | 1,504 | 6 `__main__` scripts, none invoked by compose/cron. | no |
| `learning/` | 4 | 1,284 | adaptive-ML subsystem; zero importers (ML removed 2026-06-10). | no |
| `infrastructure/` | 5 | 1,075 | zero external importers, no entrypoint. | no |
| `ml/` | 4 | 809 | ML gate removed 2026-06-10. `model_health.py` shipped for box parity only (runner *mentions* it in a comment, never imports). `xgboost_ensemble`/`train_from_history` only used by dead `diagnostics`. | no |
| `backtesting/` | 3 | 482 | self-contained; zero live/script reach. | no |
| `engine/` | 3 | 365 | `v6_engine` consumes but is consumed by nothing. Box "aaats-engine" cron refs are to a stale **container's logs**, not this package. | no |

### 2b. REMOVE — dead files inside otherwise-live packages

Traced to **zero importers anywhere** (distinct from dashboard-only in §2d):

- **`execution/` institutional cluster (12 files, ~3,000 LOC):** `oms.py`,
  `paper_executor.py`, `fill_model.py` (the "rigorous fill model not wired into live
  PnL" — confirmed), `smart_order_router.py`, `adaptive_execution_engine.py`,
  `execution_quality_tracker.py`, `dead_letter_queue.py`, `multi_leg_validator.py`,
  `order_tif_manager.py`, `order_validator.py`, `partial_fill_handler.py`,
  `status_db.py`. (`metrics_exporter` reads their *DB files*, never imports the modules.)
  **KEEP:** `paper_trader.py`, `market_hours.py`, `idempotency.py`.
- **`decision/` (3 of 4):** `confidence_scorer.py`, `ensemble_aggregator.py`,
  `meta_coordinator.py` — only reachable via `decision/__init__.py`, which nothing
  imports. **KEEP:** `consensus_voting.py` (runner:52).
- **`markets/crypto/` dead hub (4 files):** `integration.py`, `fetcher.py`,
  `storage.py`, `confidence_scorer.py` — old wiring, zero importers. **KEEP:**
  `universe/scanner/allocator/correlation_guard/sentiment` (runner:2021-2025).
- **`indicators/regime_detector.py`** — replaced by the live `intelligence/regime/`
  HMM pipeline; only the dead `markets/crypto/integration` referenced it. **KEEP:**
  `indicators/features.py` (runner:50).
- **`monitoring/dashboard_cache_manager.py`** — only `monitoring/__init__.py`.
- **`risk/us/` (2 files)** — us halted; appears only as a string in a comment.

### 2c. REMOVE-with-rebuild — dormant us/india cluster (Tier 2)

Wired into the runner but **never executed** (crypto container runs `--market crypto`;
`aaats-paper-us`/`aaats-paper-india` are **not running** — confirmed on box):

- `markets/india/*` (8 files, ~1,681 LOC), `markets/us/*` (4 files, ~736 LOC)
- `run_india`/`run_us` paths in `live_paper_runner.py`
- compose services `aaats-paper-us`, `aaats-paper-india` + volumes `state-us`, `state-india`
- `tests/test_india/`, `tests/test_us/`

Removing these is genuinely correct (halted, capital=0, not running) but edits the
runner → needs a rebuild, so it's Tier 2, not a free delete.

### 2d. KEEP (dashboard-only) — live via `aaats-dashboard`, NOT the trading path

`streamlit_app/views/page_institutional.py` (a registered, live page) imports this
whole cluster. It is **live** — deletable only if you also remove that page (Tier 3):

- `analytics/{pnl_attribution, slippage_tracker, strategy_optimizer, stress_tester}`
- `risk/{anomaly_detector, correlation_monitor, funding_monitor, macro_hedge, overnight_manager, settlement_manager, drawdown_monitor, position_manager}`
- `foundation/{health_monitor, mode_manager, rbac, secrets_manager, shutdown_handler}`
- `execution/backup_api_handler.py`, `production_readiness/` (via `page_production_readiness`)

### 2e. KEEP — live trading + monitoring core

`trading/{paper_loop, live_paper_runner, stat_arb, altcoin_reversion, bollinger_range,
strategy_isolation}`; `risk/{engine, position_sizer, auto_halt, strategy_halt}`;
`execution/{paper_trader, market_hours, idempotency}`; `markets/crypto/{universe,
scanner, allocator, correlation_guard, sentiment}`; `foundation/{logger, kill_switch,
audit_trail, decision_ledger, state_bridge, positions}`; `intelligence/regime/{regime_pipeline,
hmm_regime}`; `indicators/features`; `decision/consensus_voting`;
`analytics/{cost_model, ledger_repricer}`; `state/schemas`; `monitoring/{metrics_exporter,
telegram_bot, realtime_state_manager, streamlit_sync_bridge, stale_data_detector,
heartbeat_monitor, daily_digest}`; `observability/alerts`; `health/watchdog`;
`streamlit_app/*`; `scripts/{init_db, reconcile_intracycle, health_check}` + operator
incident CLIs; `tools/operator/deploy_lib.py`; `tools/reports/weekly_report.py`; the
T3 reuse harness; all `scripts/box/` cron scripts.

---

## 3. Deliverable 2 — Files to REMOVE (summary lists)

1. **Whole packages (Tier 1):** `v6-stack/`, `strategies/`, `portfolio/`, `safety/`,
   `diagnostics/`, `learning/`, `infrastructure/`, `ml/`, `backtesting/`, `engine/`
   — plus their `tests/test_*` dirs.
2. **In-package dead files (Tier 1):** the `execution/` institutional cluster (12),
   `decision/` (3), `markets/crypto/` dead hub (4), `indicators/regime_detector.py`,
   `monitoring/dashboard_cache_manager.py`, `risk/us/` (2).
3. **Spent one-off scripts (Tier 1):** ~22 `tools/operator/deploy_*_<date>.py` +
   fix/remote/verify; ~17 `tools/nautilus/run_c3*/c2/c7/tsmom/ensemble/walk_forward`
   OOS one-offs (verdicts banked in `research/`); 5 `tools/backtest` replays; ~30
   `scripts/deploy_*/deploy_session*/migrate_*/live-flip` artifacts. (Operator incident
   CLIs — halt/resume/drain/reset — KEEP.)
4. **Root doc clutter (Tier 1):** ~30 root `*.md` (`*_COMPLETE.md`, `PHASE_*.md`,
   `AUTONOMOUS_*`, `MASTER_*`, `NEXT_*`, `WEB_APP_*`, `SESSION_*`, etc.). KEEP:
   CLAUDE.md, README.md, SECURITY.md, LEGAL_COMPLIANCE.md, ANGEL_ONE_SETUP.md,
   FLAGGED_ISSUES.md, the two dated 2026-06-09 research artifacts.
5. **Dead workflow:** `.github/workflows/autonomous-build.yml`.
6. **Tier 2 (with rebuild):** us/india cluster (§2c).
7. **Tier 3 (with dashboard rebuild):** `page_institutional` + its cluster (§2d).

A precise, path-level removal manifest will accompany the first implementation commit.

## 4. Deliverable 3 — Files to MODIFY

Minimal by design (boring > clever):
- `requirements.in` / `requirements.txt`: drop deps with zero live importers —
  **`xgboost`, `hmmlearn`** (the HMM is hand-rolled and never imports it),
  **`torch`, `shap`, `vectorbt`, `nsepy`, `fredapi`, `pycoingecko`, `anthropic`,
  `scikit-learn`, `web3`**. `statsmodels` is live-but-fallback-guarded (C1 only) — keep.
  Reconcile the `.in`/`.txt` divergence.
- `.github/workflows/ci.yml`: unchanged logic, but it runs `pytest tests/` over the
  whole tree — orphan test dirs **must** be deleted atomically with their packages or CI breaks.
- `tests/test_decision/`: split — keep `consensus_voting` tests, drop ensemble/meta/confidence.
- `live_paper_runner.py`: **only** under Tier 2 (remove `run_india`/`run_us`; update
  strategy imports if consolidating). Not touched in Tier 1.

## 5. Deliverable 4 — Files to MERGE (strategy consolidation)

The 3 live strategies independently re-implement ~120-150 lines of identical
boilerplate: `_load_state`/`_save_state` (4 copies), `_age_hours` (byte-identical in
C3/C6), `_record*` (3 divergent signatures), the `STRATEGY_ID/MARKET/_USE_UNIFIED_LEDGER/
ENTRIES_DISABLED/_round_trip_cost` constant block, and per-module exit-gate wiring.
These merge into one base class (§6).

## 6. Deliverable 5 + 6 — Proposed structure & strategy consolidation plan

### Proposed final structure (after Tier 1 + light Tier 2)
```
trading/            # live loop only
  paper_loop.py  live_paper_runner.py  strategy_isolation.py
strategies/         # REBUILT: live engines, not the orphan toy library
  base/base_strategy.py        # state/record/cooldown/cost/gate — the merged boilerplate
  strategy_registry.py         # maps id -> class, replaces hard-coded runner calls
  live/
    c1_stat_arb.py  c3_altcoin_reversion.py  c6_bollinger_range.py
  experimental/                # archived ideas (grid, liquidation_cascade, funding) — NOT wired
risk/  execution/  markets/crypto/  foundation/  intelligence/regime/
indicators/  decision/  analytics/  monitoring/  observability/  state/
streamlit_app/  scripts/  scripts/box/  tools/{operator,reports,nautilus,backtest,research,graduation}/
docs/  research/  AUDIT/  OPERATIONS/  deployment/  config/
```

### Strategy consolidation — two options (my recommendation: **Light**)

- **LIGHT (recommended):** delete the orphan `strategies/` tree; move the 3 live
  modules into `strategies/live/`; extract the shared boilerplate into
  `strategies/base/base_strategy.py`; add a thin `strategy_registry.py`; update the
  ~4 runner call sites + ~10 backtest-tool/test import sites; archive 3 genuinely-novel
  ideas (`grid_trading`, `liquidation_cascade`, `funding_rate`) under `experimental/`
  as **idea records, not wired code**. One coordinated rebuild.
- **HEAVY (not recommended now):** full abstract `BaseStrategy` with standardized
  signal/▸risk/telemetry hooks and a plugin registry.
  **Why not:** the strategies are **terminally closed and demoted to no-trade.** A
  reactivation requires a *new pre-registered thesis* written fresh — not a revival of
  C1/C3/C6. Building elaborate abstractions around frozen code is exactly the
  "clever over boring" the goal warns against, and it's the contract-discouraged kind
  of refactor. The Light option captures the maintainability win (one place for the
  boilerplate, a clean home) at a fraction of the risk.

**Honest note:** even the Light consolidation is *polish on frozen code*. Its value is
"reactivation-ready tidiness," not correctness or performance. If you don't foresee
reactivating before the 2027 T3 gate, the highest-value action is simply **deleting the
orphan `strategies/` tree (Tier 1) and leaving the 3 live files in `trading/`** — and
skipping the consolidation entirely. I'd genuinely consider that.

## 7. Deliverable 7 — Risk assessment per change

| Change | Risk | Why | Mitigation |
|---|---|---|---|
| Delete orphan packages (§2a) | **LOW** | live container never imports them; deletion can't affect the running process | delete tests atomically; run full pytest + `python -c "import trading.live_paper_runner"` before commit; tag `archive/pre-cleanup-2026-06-13` first |
| Delete in-package dead files (§2b) | **LOW-MED** | zero importers, but they live next to live code — risk of a missed lazy import | grep each file's symbols repo-wide before delete; import-smoke the live entrypoints |
| Delete spent scripts/docs (§3.3-3.5) | **LOW** | one-offs; history preserved in git | none needed |
| Drop unused deps (§4) | **LOW-MED** | a transitive import could surface at runtime | rebuild image in a throwaway test, import-smoke all live entrypoints before shipping |
| Strategy consolidation Light (§6) | **MEDIUM** | edits live-imported runner + 3 strategy modules → **needs box rebuild**; touches ~14 import sites | full test suite + replay-tool smoke; paramiko deploy w/ rollback manifest; verify book stays flat + 0 entries post-deploy (same protocol as 2026-06-10) |
| Remove us/india cluster (§2c) | **MEDIUM** | runner + compose edit; rebuild | confirm us/india containers stay down; rebuild crypto container; import-smoke |
| Trim dashboard `page_institutional` (§2d) | **MEDIUM** | dashboard container rebuild; loses an institutional view | confirm operator doesn't use that page; rebuild `aaats-dashboard` only |
| **Do nothing to live container in Tier 1** | — | Tier 1 needs **no redeploy** — the box keeps its current image; repo shrinks; next rebuild (only on a Tier 2/3 change) picks up the smaller tree | — |

## 8. Dependency & architecture notes (Phase 4/5)
- **Deps:** 11 cleanly-droppable libraries (§4); `requirements.in`↔`.txt` are out of sync.
- **Architecture simplification falls out of deletion, not new abstraction:** removing
  the institutional `execution/` cluster, the `decision/` meta-coordinator stack, the
  dead `markets/crypto` hub, and `portfolio/` collapses several never-used "enterprise"
  layers. The live data flow is already boring and explicit
  (`paper_loop → run_crypto → strategy fns → paper_trader → DB → metrics_exporter`);
  it just has a lot of dead scaffolding around it. **Do not add a new base abstraction
  beyond the single strategy base — the win here is subtraction.**

## 9. Recommended sequencing (small, reviewable commits, each gated on approval)
1. **Tag** `archive/pre-cleanup-2026-06-13` (full safety net).
2. **Commit 1** — delete `v6-stack/` (largest, cleanest, zero-risk).
3. **Commit 2** — delete orphan packages §2a + their tests.
4. **Commit 3** — delete in-package dead files §2b (+ split test_decision).
5. **Commit 4** — delete spent scripts + root doc clutter + autonomous-build.yml.
6. **Commit 5** — drop unused deps; rebuild-test image; import-smoke.
   → *Tier 1 ends here. No box redeploy required. ~250 files gone, repo ~halved.*
7. **(Approve separately) Commit 6** — strategy consolidation (Light) + coordinated rebuild.
8. **(Approve separately) Commit 7** — remove us/india cluster + rebuild.
9. **(Approve separately) Commit 8** — dashboard trim + dashboard rebuild.

Each commit: full pytest green + live-entrypoint import-smoke before push; Tier 2/3
commits additionally carry a `.rollback/` manifest and post-deploy flat-book/0-entry
verification.
