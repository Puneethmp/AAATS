# AAATS — Loss Attribution (Phase 0)

> Source: `runtime/paper_trades.db` (canonical), 554 rows, 271 realized-PnL events,
> window **2026-05-23 → 2026-06-09** (~17 days). Starting crypto equity **$110**.
> Read-only audit, 2026-06-10.

## Headline

| Measure | Value | % of $110 equity |
|---|---|---|
| **Gross signal PnL** (as recorded — zero costs) | **−$2.27** | −2.1% |
| Net after realistic **fees** (0.10%/side spot taker) | **−$7.64** | −6.9% |
| Net after **fees + slippage** (0.10%/side each) | **−$13.01** | −11.8% |

The ledger PnL is **gross** for every live strategy (C1/C3/C6 use raw prices — see
`architecture_actual.md §2`). Funding = $0 (instruments are **spot**, not perps).
**Gross PnL is already negative before a single cost is applied.**

## Loss decomposition by strategy (net of full fees+slippage)

| Strategy | n | Gross | Fee cost | Slip+fee cost | Net (full) |
|---|---:|---:|---:|---:|---:|
| C1 stat-arb | 16 | +0.177 | 0.42 | 0.84 | **−0.659** |
| C3 altcoin reversion | 94 | −2.923 | 1.79 | 3.59 | **−6.510** |
| C6 bollinger range | 161 | +0.479 | 3.16 | 6.32 | **−5.838** |
| **TOTAL** | **271** | **−2.267** | 5.37 | 10.74 | **−13.007** |

C3's signal loses money **gross**. C1 and C6 are gross-flat-to-slightly-positive but
do not clear even the most conservative cost (fees alone flip both negative).

## Bucket classification (per realized event, net of full costs)

| Bucket | n | Net PnL | Reading |
|---|---:|---:|---|
| **SIGNAL** (gross < 0, signal wrong) | 122 | −21.62 | dominant driver |
| WIN (net-positive after costs) | 108 | +18.11 | real winners, but outnumbered/outsized by losers |
| **RISK** (stop-out, gross < −$0.30) | 14 | −8.44 | stops *capping* bad signals — see note |
| **COST** (gross ≥ 0 but costs flip it) | 27 | −1.06 | structural; small marginal effect |
| **BUG** | 0 | 0.00 | none found (see below) |

**On the RISK bucket:** these 14 are not a risk-logic *defect*. Every one exited via a
working stop (`z_hard_stop`, `time_stop_24h`, `hard_stop(-x%)`) that **capped** the loss
at ~−$0.5 to −$0.95. There is **no "small loss became big loss" signature** — the opposite,
the rails are doing their job. Economically these are simply SIGNAL losses that the risk
system bounded. Folding them in: **136 of 271 events (50%) are losing signals**, and the
combined SIGNAL+RISK net is **−$30.06**, only partly offset by +$18.11 of winners.

**On the COST bucket:** costs are **not modeled at all** in the live PnL path. This is a
genuine *structural defect* (Phase 2 item #3) — but it flips only 27 marginal winners and
accounts for ~$1 of the swing. It is **not** the reason the book is negative; the signal is.

**On BUG:** no wrong-side, wrong-size, stale-data, or accounting defect surfaced in realized
PnL. C5b (the known $25/$50 asymmetry) is disabled and produced no trades. C1 pair legs
reconcile. The realized ledger is internally consistent. (This does **not** clear latent bugs
in disabled code — only that nothing buggy *traded* in this window.)

### 10 worst trades (net after full costs)

| net | gross | cost | bucket | strategy | symbol | exit reason | when |
|---:|---:|---:|---|---|---|---|---|
| −0.948 | −0.901 | 0.047 | RISK | C3 | POL/USDT | z_hard_stop | 06-05 18:32 |
| −0.933 | −0.894 | 0.039 | RISK | C3 | AVAX/USDT | z_hard_stop | 06-06 04:32 |
| −0.917 | −0.894 | 0.023 | RISK | C3 | TON/USDT | time_stop_24h | 06-05 19:32 |
| −0.822 | −0.802 | 0.020 | RISK | C3 | OPN/USDT | z_hard_stop | 06-06 17:02 |
| −0.789 | −0.731 | 0.059 | SIGNAL | C3 | BNB/USDT | z_trailing | 06-04 02:17 |
| −0.760 | −0.740 | 0.020 | RISK | C3 | EDEN/USDT | time_stop_24h | 05-26 12:12 |
| −0.715 | −0.665 | 0.050 | RISK | C3 | ADA/USDT | z_hard_stop | 06-04 21:47 |
| −0.561 | −0.532 | 0.028 | RISK | C3 | PENDLE/USDT | time_stop_24h | 05-28 18:46 |
| −0.460 | −0.430 | 0.030 | RISK | C3 | ALGO/USDT | z_hard_stop | 06-05 06:32 |
| −0.457 | −0.415 | 0.042 | SIGNAL | C6 | GPS/USDT | hard_stop(−3.99%) | 06-03 18:46 |

The worst trades are **9/10 C3 mean-reversion entries that kept going against the position**
until the stop fired — the textbook failure mode of reversion in a trending/drifting alt
regime (consistent with the prior Track-8/regime-gate findings). Costs are a rounding error
next to the gross moves.

### Losing-exit reason distribution (gross < 0)
`hard_stop` 78 · `z_hard_stop` 24 · `time_stop_24h` 18 · `time_stop` 5 · `regime_flip` 2 ·
`z_trailing` 2 · `z_overshoot` 1 · none(C1 legs) 6 — i.e. losses exit cleanly via rails,
not via runaway.

## Phase 0 decision-gate verdict

**Dominant bucket: SIGNAL.** (SIGNAL 122 + the 14 stop-capped SIGNAL losses = 136/271 = 50%
of events; gross PnL is negative *before any cost*.)

Per the mandate's gate: this is the **SIGNAL-dominates** branch.

> The negative PnL **confirms the prior no-edge finding** (C1/C3/C6 carry no validated
> edge — consistent with the terminally-closed perp-edge program and the maintenance-mode
> status in CLAUDE.md). The 6-month program is therefore a **research harness measuring
> whether the system can correctly choose NOT to trade**, *not* a "make it profitable"
> exercise. The benchmark to beat is the **no-trade baseline** ($0), which currently beats
> every active strategy net of costs.

Secondary (structural, real but not causal): **costs are unmodeled** in the live PnL path —
fix in Phase 2 so future numbers are honest, but understand that doing so makes the book
*more* negative, it does not rescue it.

**Recommendation at the gate:** proceed into Phases 1–4 only as the mandate frames the
SIGNAL branch — prune dead strategies, model costs honestly, stand up the no-trade baseline,
and let the system demote everything that can't beat "do nothing." Do **not** expect or
engineer profitability from C1/C3/C6; the data says they have none.
