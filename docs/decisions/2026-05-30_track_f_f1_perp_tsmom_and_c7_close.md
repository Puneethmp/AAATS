# Track F (futures/perps) F.1 — perp data complete, C7 closed, TSMOM trialed → ESCALATE

**Status:** DECISION — verdicts locked. Offline backtest/data work only; D.5 soak untouched, no box edits, no deploy, no execution infra built.
**Authored:** 2026-05-30 (Claude Code session; machine clock 2026-05-29 so artifact filenames carry the 2026-05-29 stamp).
**Reads with:** [2026-05-29 Track 11](2026-05-29_b17_track11_drift_gate_and_track_e_entry.md). Memories `aaats-2026-05-28-c7-funding-arb-verdict`, `aaats-2026-05-29-track11-drift-gate`.

---

## TL;DR

EDGE-FIRST (operator decision 2026-05-29): no execution infra until a perp-native edge graduates G1–G7 on **both** independent 6mo windows.

1. **F.1.b perp data — COMPLETE.** Fetched ETH earlier-window perp klines+funding (the one gap); the Binance `fapi` pipeline works from this box. Perp dataset is now all 6 symbols × both windows.
2. **C7 funding-arb — CLOSED analytically (NO-GO).** The brief's "hedge-notional-sizing bug" does not exist: the hedge is balanced by construction and directional PnL ≈ $0. C7's killer is fee economics (~30bps round-trip vs ~1bps/8h funding), structural on any asset. No spot fetcher built. One future-case preserved.
3. **TSMOM momentum — FAILS both windows.** Current FAILs outright (net −$5.16, DD 28.7%); earlier is *profitable* (+$20.30, PF 1.42) but FAILs on OOS Sharpe (−0.92) — the trend decays out-of-sample in **both** windows. Window-complementary to C3-perp.
4. **2nd distinct perp edge class to fail → ESCALATE (§5).** Three classes (reversion, carry, momentum) each work in one regime and fail the other. The bottleneck looks like the **method** (single-strategy dual-window graduation demands regime-robustness a single-factor strategy can't give), not the next strategy. Operator decision requested; **no 3rd candidate auto-queued.**

---

## 1. F.1.b — perp data pipeline completed (the shared long-pole)

`tools/backtest/fetch_perp_data.py`: added ETH to `SYMBOLS_EARLIER` ([:42-43](../../tools/backtest/fetch_perp_data.py#L42-L43)) and fetched `--window earlier`. Result: `ETH_USDT_1h_perp_earlier.parquet` (4344 bars) + `ETH_USDT_funding_earlier.parquet` (543 events, mean +0.583 bps/8h). The 4 alts were already cached. **Perp coverage is now complete: BTC/ETH/SOL/LINK/AVAX/DOT × {current, earlier}.** The public `fapi.binance.com` endpoints are reachable from this workstation (no auth, gentle rate-limit) — the data long-pole is not blocked.

**Spot data is NOT fetched** and there is **no spot fetcher**: `fetch_perp_data.py` is perp-only, and no `*_1h_earlier.parquet` (spot) exists for any symbol. This blocks any spot+perp strategy (C7) on the earlier window and is why C7 was closed analytically rather than re-run (operator decision: do not build the spot fetcher this session).

## 2. C7 funding-arb — analytical close (NO-GO as an absolute edge)

**The "hedge-notional-sizing bug" does not exist — correcting the record.** The Track-11 next-session prompt and this session's brief framed C7 as having "failed on notional, not direction" with a "hedge sizing fix" available. That is a **misreading** of memory `aaats-2026-05-28-c7-funding-arb-verdict`, whose verified finding is the opposite: the delta-neutral hedge **worked**. Evidence:
- Both legs are sized to the same dollar notional by construction: `LEG_NOTIONAL = 25.0` ([run_c7_funding_arb_oos.py:86](../../tools/nautilus/run_c7_funding_arb_oos.py#L86)); `spot_qty = LEG_NOTIONAL/spot_px`, `perp_qty = LEG_NOTIONAL/perp_px` ([:343-344](../../tools/nautilus/run_c7_funding_arb_oos.py#L343-L344)). Equal dollar exposure ⇒ delta-neutral for a same-asset spot/perp pair (beta ≈ 1).
- The Track-6 run measured directional gross PnL ≈ **+$0.002** across 24 pairs — empirically non-directional. An unbalanced hedge would show large directional PnL; it didn't.
- The C5b asymmetric-recording bug ($25 vs $50) **cannot occur here** — each leg is its own NT position ([:18,261-263](../../tools/nautilus/run_c7_funding_arb_oos.py#L18)).

There is therefore no sizing fix to apply; changing the leg ratio would only *re-introduce* directional risk.

**The real killer (structural, any asset):** round-trip fees ≈ 30bps (spot 10bps×2 taker + perp 5bps×2 taker) vs Binance majors funding capped at 1bps/8h, hitting the cap only ~15–18/540 settlements and decaying below 0.5bps within ~19.5h avg hold. Funding income ~$0.003/pair vs ~$0.075 fees → fees dwarf funding ~22×. Net −$1.72, PF 0.00, 24 trades (Track 6, `data/graduation/C7_delta_neutral_funding_arb_2026-05-28.json`).

**Why the alt-perp "remedy" is not worth a spot fetcher:** the binding quantity is the funding/fee *ratio*, not the funding level. Alts have higher funding but also wider spreads / higher slippage and the same 20bps spot-taker round-trip (Binance spot VIP-0 maker==taker==10bps, no maker relief). The spot leg's 20bps is the structural floor on every asset, so higher alt funding is offset by higher alt execution cost — the ratio does not reliably improve. Confirming this empirically would cost a spot-klines fetcher + earlier-window spot fetches for marginal information. **Not built.**

**Verdict: C7 = NO-GO as a standalone edge.** One future-case preserved (from the lost 2026-05-25 spec §22): C7 as a **minimal-turnover bear-market carry diversifier** (hold the short-perp carry through a sustained positive-funding regime, amortizing the one-time fee over many settlements) — reconsider **iff** a spot fetcher already exists for another reason **and** a low-turnover variant is cheap to test. Do not build infra for C7.

## 3. TSMOM (perp-native time-series momentum) — graduation trial

Operator's Option-B candidate: long/short 14d-momentum on the 6 perps, **no spot leg** (sidesteps C7's spot-fee killer; shorting the downtrend is genuinely perp-native). Harness: [run_perp_tsmom_oos.py](../../tools/nautilus/run_perp_tsmom_oos.py). One a-priori parameterization, **not swept**.

**Lookback chosen a priori from trend-persistence, not PnL** ([measure_perp_trend_persistence.py](../../tools/backtest/measure_perp_trend_persistence.py), current-window in-sample only):

```
lookback_h |  pred_coef(sign·fwd) | hit_rate
   24       |        +0.000312     |  49.4%
   48       |        -0.004311     |  44.7%
   72       |        -0.002901     |  46.3%
  120..240  |     negative/≈0      |  ~50%
  336 (14d) |        +0.002120     |  55.5%   <- strongest positive persistence
  504 (21d) |        +0.000751     |  52.7%
  720 (30d) |        -0.001114     |  50.9%
```

The universe is **mean-reverting at most daily-cadence horizons**; only 14d shows positive momentum persistence. `L = 336h` fixed; position = `sign(close[t]/close[t−L]−1)`, daily rebalance, pure sign (no threshold), $15/symbol. Economics matched to the C3-perp family (perp VIP-0 taker 5bps/maker 2bps, fills at bar close, 0 slippage, real funding per 8h). Direct auditable backtest (market-order rule ⇒ no limit-fill probability to model); G7 = maker-fee rerun (generous lower-fee bound for a trend-chaser). Method difference from the NT engine documented in the harness header, not silent.

### Results — G1..G7 both windows (gate UNCHANGED)

```
window  | n_tr | L/S   |    net | OOS Shrp |  PF  | maxDD | maker_pnl | verdict
current |  126 | 63/63 | -5.16  |  -5.20   | 0.89 | 0.287 |  -4.03    | FAIL
earlier |  104 | 53/51 | +20.30 |  -0.92   | 1.42 | 0.125 | +21.23    | FAIL
```

| Gate | current | earlier |
|---|---|---|
| G1 net PnL > 0 | FAIL (−5.16) | PASS (+20.30) |
| G2 OOS Sharpe ≥ 1.0 | FAIL (−5.20) | **FAIL (−0.92)** |
| G3 maxDD ≤ 20% | FAIL (28.7%) | PASS (12.5%) |
| G4 trades ≥ 30 | PASS (126) | PASS (104) |
| G5 PF ≥ 1.3 | FAIL (0.89) | PASS (1.42) |
| G6 OOS ≥ 0.5·IS | FAIL (OOS −5.20 vs IS +0.62) | **FAIL (OOS −0.92 vs IS +1.83)** |
| G7 maker PnL > 0 | FAIL (−4.03) | PASS (+21.23) |
| **Verdict** | **FAIL** | **FAIL** |

### Honest assessment

Momentum **fails both windows, but for opposite reasons** — and that is the informative part. In the *current* window it simply loses (net −$5.16, PF 0.89, 28.7% drawdown breaching G3): the BTC-down/choppy regime whipsaws a trend follower. In the *earlier* window it is genuinely **profitable** (+$20.30 = +20% on $100, PF 1.42, passes G1/G3/G4/G5/G7) — the BTC-up/alts-trending regime is a trend follower's friend — **yet it still FAILs**, purely on the two OOS-Sharpe gates (G2, G6), because the OOS slice (last 2 months, Mar–May 2025) reversed: in-sample Sharpe +1.83 collapses to OOS −0.92. Critically, **OOS Sharpe is negative in *both* windows** — the last ~2 months of each window are mean-reverting/choppy, so the 14d trend signal whipsaws out-of-sample regardless of regime. Momentum has no *robust* OOS edge here; its earlier-window profit is an in-sample, regime-specific artifact, consistent with the a-priori finding that this universe mean-reverts at most horizons. No parameter was swept and the gate was not re-tuned; this is the honest verdict.

## 4. Decision

| Item | Verdict |
|---|---|
| F.1.b perp data | COMPLETE (6×2); pipeline verified |
| C7 funding-arb (standalone) | NO-GO (fee-bound; no sizing bug; one bear-carry future-case preserved) |
| TSMOM momentum | FAIL both windows (current outright; earlier on OOS-Sharpe) |
| Both-window perp edge found? | **NO** |
| Next | **ESCALATE — operator decision (§5)** |

No infra built (no B2 margin/liq engine, no B3 broker adapter, no spot fetcher). B4 schema design skipped (no graduated edge to account for; revisit when one exists).

## 5. ESCALATION — is the edge-discovery *method* the bottleneck?

Per the operator's decision rule, TSMOM is the **2nd distinct perp edge class** to fail the dual-window gate. Surfacing the strategic question explicitly; **no 3rd candidate queued.**

**The pattern across every candidate is regime-complementarity, not random failure:**

| Class | Mechanism | current window | earlier window |
|---|---|---|---|
| C3 mean-reversion (alt/BTC) | price reversion | **PASS** (gated PF 1.49) | FAIL (PF 0.69) |
| C7 funding-carry | funding rent | FAIL (fee-bound) | (fee-bound, structural) |
| TSMOM momentum | trend persistence | FAIL (loses, DD breach) | **profitable** PF 1.42 (fails only on OOS-Sharpe) |

C3 (reversion) and TSMOM (momentum) are **opposite bets that succeed in opposite windows**. The two test windows are themselves opposite regimes (earlier: BTC-up / alts-bleed / trending; current: BTC-down / choppy / reverting). A *single-factor* strategy is, by definition, a bet on one regime, so the dual-window gate — which demands G1–G7 on **both** opposite regimes — is structurally unpassable by any single directional or reversion strategy. Three classes failing this way is evidence the **method** is the bottleneck, not the strategy roster.

**Strategic options for operator decision (not auto-selected):**

- **A (lead recommendation) — regime-conditional ensemble at the allocator.** Stop seeking a single both-window strategy; run C3 (reversion) **and** TSMOM (momentum) together with an allocator that tilts capital by detected regime, and graduate the *ensemble* on both windows. The data already shows the two are profitable in complementary windows — exactly what an ensemble monetizes. Uses the regime signal at the allocator per the locked 2026-05-27 doctrine ([[feedback-regime-filtering-at-allocator]]), not inside a strategy (Track 11 showed in-strategy regime gates over-filter). This is the natural synthesis of Tracks 8–11 + F.1.
- **B — change the graduation frame.** The dual-opposite-window gate may be too adversarial for single strategies. Consider walk-forward across many regime-tagged sub-periods with a deploy-time regime detector, instead of "both 6mo windows must pass." (Caveat: still needs a robustness criterion that isn't just curve-fitting.)
- **C — different edge class needing new data/infra.** Majors market-making / liquidity provision is less directional but needs order-book microstructure data AAATS doesn't have, and different infra. Larger commitment.
- **D — question the loop economically.** At $25 tranches with 30bps round-trip fees, the fee floor may dominate any small-notional edge regardless of signal; the constraint may be capital/fees, not signal discovery.

**Recommendation:** pursue **A** next session (it reuses both existing harnesses and the gate, and directly tests the complementarity this session surfaced), but the choice is the operator's — this is the method-level pivot the escalation clause reserved for operator decision.

## 6. Reproduce

```
python tools/backtest/fetch_perp_data.py --window earlier            # idempotent; ETH gap
python tools/backtest/measure_perp_trend_persistence.py              # a-priori L choice
python tools/nautilus/run_perp_tsmom_oos.py                          # dual-window G1-G7
```
Reports: `data/graduation/Perp_TSMOM_{current,earlier}_2026-05-29.json`.
