# B.1.7 Track 11 — drift-trend regime gate (v3) + Track E (futures/perps) entry plan

**Status:** DECISION — verdict locked. Offline backtest-harness work only; D.5 soak untouched, no box edits, no deploy.
**Authored:** 2026-05-29 (Claude Code session, D.5 soak day ~6).
**Supersedes nothing.** Extends Tracks 9 ([divergence gate](2026-05-29_*)) and 10 (correlation gate). Reads with memories `aaats-2026-05-29-regime-gate-track9`, `aaats-2026-05-29-regime-gate-v2-track10`, `aaats-2026-05-29-c3perp-window-robustness`.

---

## TL;DR

A drift-trend gate (`gate_version=3` = divergence AND |60d log-RS drift| ≥ 0.08) **does NOT flip the earlier window from FAIL to PASS — it FAILs worse** (PF 0.41 vs v1/v2's 0.69; net −5.31 vs −4.86; OOS Sharpe −3.56 vs −1.61). Unlike correlation (Track 10, inert), the drift signal is **genuinely active and independent** — it blocked 1127 bars (earlier) / 1114 bars (current) that the divergence gate let through — but blocking them removed **profitable** mean-reversion trades alongside losers, so it degraded *both* windows. The current window still PASSes but loses half its edge (PF 1.49→1.35, net +8.29→+4.27).

**Three principled allocator entry signals (divergence, correlation, drift) have now been tested. None makes C3-perp a both-window-robust candidate. The entry-gate line of attack is EXHAUSTED.**

- **C3-perp solo:** NO-GO.
- **C3-perp gated (best = plain v1 divergence):** PARTIAL — current-window-only. v2/v3 add nothing (corr) or hurt (drift).
- **Decision:** commit to **Track E (futures/perps)**. Track 11 closes the C3-class entry-gate program.

---

## 1. What was built (offline, soak-safe)

All changes are in `tools/nautilus/` and `tools/graduation/` — NT dev-only dependency, never imported by the box. The D.5 paper soak (`aaats-paper-crypto`) was not touched.

- **`tools/nautilus/regime_gate.py`** — added `compute_drift_trend()` + `is_regime_ok_v3()` + `DRIFT_LOOKBACK_BARS=1440` / `DRIFT_THRESHOLD=0.08`. v1/v2 functions byte-untouched (same backward-compat discipline as Track 9→10). Self-test extended with 4 v3 cases; all pass.
- **`tools/nautilus/run_c3_perp_funded_oos.py`** + **`run_c3_perp_funded_earlier_oos.py`** — added the `gate_version=3` branch to the allocator gate block (drift attribution counters `drift_only`/`div_only`/`both`, drift series, `mean_drift_60d`, `drift_eval_bars`). The two files' gate regions remain byte-identical (verified).
- **`tools/nautilus/run_c3_perp_v3_gated_both_windows.py`** — new Track 11 driver. Runs the genuinely-new evaluations (current v0+v3, earlier v0+v1+v3) and **cites the locked v1/v2 rows read-only** from the Track 9/10 reports — honouring "do not re-run current-window v1/v2, locked at 7/7."
- Reports: `data/graduation/C3_perp_gated_v3_{current,earlier}_2026-05-29.json`.

### The drift signal (decided a priori, NOT swept)

```
rs_t  = mean_alt( log(alt_close_t) − log(btc_close_t) )    # equal-weight basket log relative-strength vs BTC
drift = OLS_slope(rs_t vs bar_index, last 1440 bars) × 1440 # regression-fitted NET log-RS move over the 60d window
gate  : BLOCK when |drift| ≥ 0.08   (persistent relative trend ⇒ broken mean-reversion regime)
v3    : ALLOW only if divergence ≤ 0.08 AND |drift| < 0.08
```

- **Lookback = 1440 bars (60d):** LONGER than the 30d divergence lookback, per the signal spec's explicit "longer-horizon"/"LONGER" instruction. (The spec's parenthetical "e.g. 7d" contradicts both "longer-horizon" and "LONGER than the divergence lookback" and the requirement to justify from a *six-month* drift magnitude; the explicit word "LONGER" was followed and the contradiction is recorded here.) 60d is the medium-term persistence horizon that still lets the gate state evolve ~3× across the 6mo test window.
- **Threshold = 0.08 log-RS over the lookback (a priori):** the *mildest* failing alt of the earlier window (LINK) drifted −0.267 log-RS vs BTC over 6mo / 4344 bars = −6.15e-5/bar; scaled to the 1440-bar lookback that is −0.089, rounded to **0.08** (also symmetric with the divergence threshold). A 60d trailing trend at/above this magnitude means the basket is trending against BTC as hard as the weakest leg of the known-fatal regime. **Not swept** — sweeping the drift params would be fitting to the earlier window, which the session brief explicitly forbade.

**Data check (observed, not assumed):** both windows have alts bleeding vs BTC.
| window | BTC 6mo | alt 6mo range | basket mean log-RS drift / 4344 bars |
|---|---|---|---|
| earlier (Nov24→May25) | +12.7% | −13.7% … −46.7% | **−0.551** |
| current (Nov25→May26) | −18.7% | −30.2% … −46.7% | **−0.295** |

The earlier window drifts ~1.9× harder, but the current (PASSing) window drifts substantially too — so a |drift|-magnitude gate was always going to bite both. This was flagged before the run as the over-fit trap.

---

## 2. Results — `gate_version=3` on both windows (Deliverable 1)

```
window           | gate_v|  gate%| n_trades|     pnl|  sharpe|    PF| verdict
--------------------------------------------------------------------------------
current-ungated  |      0|    0.0|      234|   +9.82|    1.55|  1.45| PASS
current-v1*      |      1|   31.2|      168|   +8.29|    2.96|  1.49| PASS
current-v2*      |      2|   31.2|      168|   +8.29|    2.96|  1.49| PASS
current-v3       |      3|   62.2|      121|   +4.27|    2.46|  1.35| PASS
earlier-ungated  |      0|    0.0|      212|   -8.17|   -0.41|  0.71| FAIL
earlier-v1       |      1|   52.2|      122|   -4.86|   -1.61|  0.69| FAIL
earlier-v2*      |      2|   52.2|      122|   -4.86|   -1.61|  0.69| FAIL
earlier-v3       |      3|   83.3|       65|   -5.31|   -3.56|  0.41| FAIL
```
`*` = cited read-only from the locked Track 9 (v1) / Track 10 (v2) reports; not re-run.

### Per-criterion G1..G7, gate_version=3

| Gate | current-v3 | earlier-v3 |
|---|---|---|
| G1 net PnL > 0 | PASS (+4.27) | **FAIL** (−5.31) |
| G2 OOS Sharpe ≥ 1.0 | PASS (2.46) | **FAIL** (−3.56) |
| G3 maxDD ≤ 20% | PASS (4.96%) | PASS (6.05%) |
| G4 trades ≥ 30 | PASS (121) | PASS (65) |
| G5 PF ≥ 1.3 | PASS (1.35) | **FAIL** (0.41) |
| G6 OOS ≥ 0.5·IS | PASS | **FAIL** (IS −2.52 ≤ 0, OOS −3.56 < 0) |
| G7 PnL@fill=0.5 > 0 | PASS (+4.27) | **FAIL** (−5.31) |
| **Verdict** | **PASS 7/7** | **FAIL 5/7** |

### Drift-gate attribution diagnostic (checked first, per brief)

```
CURRENT v3: active 62.2% (2239/3600 bars) | div_only=239  drift_only=1114  both=886
  drift computable on 2881 bars; mean 60d drift −0.1092; |drift|≥0.08 on 69.4% of bars
EARLIER v3: active 83.3% (3018/3624 bars) | div_only=468  drift_only=1127  both=1423
  drift computable on 2905 bars; mean 60d drift −0.2378; |drift|≥0.08 on 87.8% of bars
```

The contrast with Track 10 is the whole point: **correlation was inert (corr_only=0 in both windows); drift is NOT (drift_only > 1100 in both).** The drift axis is genuinely independent of divergence and blocks a large, distinct set of bars.

---

## 3. Honest assessment (Deliverable 2)

**Did the drift gate block bars the divergence gate didn't? Yes, decisively** — `drift_only` = 1127 (earlier) and 1114 (current), versus correlation's 0. The drift signal is a real, independent axis: a 60d regression-smoothed relative-strength trend captures something the 30d two-endpoint divergence return does not. **Did that change the earlier-window verdict? Yes — in the wrong direction.** Earlier-v3 is FAIL *and worse* than v1/v2 (PF 0.41 < 0.69, net −5.31 < −4.86, OOS Sharpe −3.56 < −1.61), and the current window — which still PASSes — lost about half its edge (PF 1.49→1.35, net +8.29→+4.27, 168→121 trades). The drift gate is net-negative on *both* windows. Mechanism: alts bleed vs BTC throughout both windows, so |drift| ≥ 0.08 fires on 70–88% of bars; the gate therefore throttles C3 almost globally instead of surgically excising the fatal sub-periods. Throttling a positive-edge window proportionally shrinks profit; throttling a negative-edge window can't flip the sign because the survivors live in the same broken regime, and stripping out the winners alongside the losers actually *worsens* PF. This is the Track-5 over-filtering failure mode in a new guise (`feedback_regime_filtering_at_allocator`): an always-on, high-magnitude regime signal cannot manufacture an edge in a window that has none — the earlier window's C3-perp is genuinely edgeless (ungated PF 0.71, net −8.17), and no entry gate that merely subsets the same trade population can fix that. Divergence (v1) remains the best of the three precisely because it removes the *worst*-divergence entries and nothing else, halving the loss without gutting the winners — but even it cannot flip the sign. **The entry-gate line of attack is exhausted.**

---

## 4. Decision (locked)

| Item | Verdict |
|---|---|
| Earlier-window v3 flip FAIL→PASS? | **NO** (FAILs worse) |
| C3-perp solo | **NO-GO** |
| C3-perp gated, best variant | PARTIAL — current-window-only; best gate is plain **v1 divergence** (v2 inert, v3 harmful) |
| Entry-gate program (Tracks 9/10/11) | **EXHAUSTED — closed** |
| Next | **Track E (futures/perps)** |

No live flip. No deploy. The graduation gate, harness, and three regime-gate versions are reusable for any future strategy class.

---

## 5. Track E (futures/perps) — Phase F.1 entry plan

### 5.0 Provenance + a naming collision that must be fixed

The session brief instructed: *"Read `docs/decisions/2026-05-25_track_e_futures_spec.md` (7 phases F.1–F.7, 4 prereq blockers)."* **That file does not exist.** Track E (futures/perps) has never been written into a formal spec — it exists only as forward references:
- `docs/decisions/2026-05-28_b17_c3_supplements_plan.md` §Risks: *"Track E (futures/perps) opens up"* if the alt-vs-major mean-reversion class hits its ceiling.
- `docs/decisions/2026-05-27_nt_final_extraction_for_success.md` item 8: *"Re-evaluate at Track E (futures/perps)"* for the event-driven loop.
- `docs/decisions/2026-05-22_live_flip_rebuild_plan.md` PF5 exclusions: *"Adding futures = Track E (new broker adapter, new liquidation engine, new state schemas)."*

**Naming collision:** the rebuild plan ALREADY defines a "Track E" = *Operator-away autonomous-soak setup* (phases E.1–E.6) — and that one is **done** (the D.5 soak is live). The brief's "Track E (futures/perps)" is a *different* track. Its phase prefix "F.1–F.7" suggests the brief author already intended a fresh track letter. **Recommendation: name the futures program "Track F — Futures/Perps" (phases F.1–F.7)** to end the collision. This doc uses "Track E (futures/perps) / phases F.1–F.7" to match the brief but flags the rename as the first F.1 cleanup.

This section IS the missing spec's foundation, built from the on-disk evidence above. It is planning + soak-safe scaffolding only — no live, no deploy, no doctrine change enacted.

### 5.1 The 4 prereq blockers (derived + cited)

Futures/perps cannot reach live capital until all four clear. Each is grounded in existing docs, not invented:

| # | Blocker | Why (citation) | Offline-startable now? |
|---|---|---|---|
| **B1** | **Doctrine amendment: spot-only → futures-allowed** | AAATS is spot-only per locked doctrine (`aaats_locked_doctrine_2026_05_14.md`, cited in rebuild-plan PF5 exclusions). Perps violate it. | DRAFT only (operator enacts). Soak-safe. |
| **B2** | **Liquidation + margin risk engine** | `risk/engine.py` has no margin/maintenance/liquidation modeling; PF5 excludes "leverage liquidation cascade" because "spot has no liquidation." | PROTOTYPE offline in the NT harness. Soak-safe. |
| **B3** | **Futures broker adapter (Binance USDT-M / Bybit)** | AAATS is single-exchange Binance *spot* paper; NT supplies verified `adapters.binance`/`adapters.bybit` (NT extraction item 6). | INTERFACE design only. Soak-safe. |
| **B4** | **Futures state schema (funding, margin, leverage, liq-price, mark vs index)** | `paper_trades.db` is `price REAL, value REAL` with no funding/margin columns (NT extraction item 2). | DESIGN + draft migration. Soak-safe. |

### 5.2 What already exists toward Track E (the harness is a head start)

The C3-perp harness built across Tracks 4b–11 is **already futures-native** and reusable:
- Real Binance **USDT-M perp** 1h klines + **real funding-rate history** applied per 8h settlement (`run_c3_perp_funded_oos.py`).
- Binance perp **VIP-0 maker/taker fee model** (`MakerTakerFeeModel`, 2/5 bps).
- NT **MARGIN account** (`AccountType.MARGIN`) — currently `margin_init=0`/`margin_maint=0` (the B2 prototype just turns these on).
- The **graduation gate** (G1–G7) and **3 regime-gate versions** — reusable for any perp-native strategy.

So Track E does NOT start from zero. F.1 is "harden + spec the foundation that already half-exists," not "build futures from scratch."

### 5.3 F.1 — concrete first-task breakdown (all offline, soak-safe)

1. **F.1.a — Write the canonical Track E/F spec** (`docs/decisions/2026-05-30_track_f_futures_spec.md`): formalize F.1–F.7, lock the rename, list the 4 prereq blockers with exit criteria. *(0.5 session — the missing artifact the brief assumed existed.)*
2. **F.1.b — Margin/liquidation prototype in the harness** (B2): set `margin_init`/`margin_maint` to realistic Binance USDT-M tiers, track liquidation price per open long, and re-run the current-window C3-perp to measure whether its drawdown (G3) survives a maintenance-margin model. *Pure NT harness; no box.* *(1 session.)*
3. **F.1.c — Futures state-schema design** (B4): draft the `paper_trades` columns + a `funding_ledger` / `margin_state` schema (Decimal-as-TEXT per NT extraction item 2). Spec + draft migration script, **not** applied to any live DB. *(0.5 session.)*
4. **F.1.d — Broker-adapter interface borrow** (B3): document NT's `ExecutionClient`/`DataClient`/`InstrumentProvider` interface as the canonical futures-order vocabulary (reduce-only, post-only, OCO, `TRAILING_STOP_MARKET`). Design doc only. *(0.5 session.)*
5. **F.1.e — Doctrine-amendment draft** (B1): write the spot-only→futures-allowed amendment for operator review, including the leverage cap, per-trade liquidation-distance floor, and tranche gates. **Operator enacts; Claude only drafts.** *(0.5 session.)*

**The open strategy problem (must be said plainly):** Track 11 just proved there is **no both-window-robust futures edge today** — C3-perp is current-window-only PARTIAL and the gating attack is exhausted. Track E's infra/F.1 work is necessary but **not sufficient**: a live perp also requires a *new* perp-native edge that graduates on both windows. Candidates not yet exhausted: perp-native momentum/carry at different time scales, funding-harvest with a real hedge sizing fix (C7 failed only on notional, not direction — memory `aaats-2026-05-28-c7-funding-arb-verdict`), or market-making on majors. F.1 builds the runway; finding the edge is a parallel, still-open research line.

### 5.4 Gating-criteria checklist before ANY live perp (operator must clear)

- [ ] **B1** Doctrine amendment signed by operator (spot-only lock explicitly lifted, leverage cap + liquidation-distance floor set).
- [ ] **Edge** A perp-native strategy PASSes the graduation gate (G1–G7) on **both** independent 6mo windows — robust, not window-specific. *(C3-perp does NOT meet this.)*
- [ ] **B2** Liquidation + margin risk engine shipped and PF5-style stress-tested (add a "PF5.9 forced-liquidation" scenario — currently excluded as out-of-doctrine).
- [ ] **B4** Futures state schema migrated; funding/margin/liq-price recorded with Decimal precision; ledger-divergence (L5) extended to margin.
- [ ] **B3** Futures broker adapter built + DRY-RUN reconciled vs paper signal (the Track A.2 analog) within the pinned slippage tolerance.
- [ ] **Track C unchanged** — all C.1–C.7 live-flip gates (incl. C.7 profitability gate and the 30-day soak) still apply to the futures book; Track E adds requirements, removes none.
- [ ] **Tranche** First live perp ≤ $25 notional, lowest leverage (≤2×), per the doctrine's escalation gates.

---

## 6. Reproduce

```
.venv-nt/Scripts/python.exe tools/nautilus/regime_gate.py                          # self-test (v1/v2/v3)
.venv-nt/Scripts/python.exe tools/nautilus/run_c3_perp_v3_gated_both_windows.py     # both-window v3 run
```
Reports land in `data/graduation/C3_perp_gated_v3_{current,earlier}_<today>.json`.
