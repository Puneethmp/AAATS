# Strategy activity audit (2026-05-18)

- **Audit valid as of**: 2026-05-18T12:10Z (UTC).
- **Container image**: `aaats-paper-crypto` running `sha256:1a06f1a3de03…`
  (per `CLAUDE.md`); Up 2 days (healthy); RestartCount=0; started
  `2026-05-16T05:21:36Z`.
- **`origin/main` HEAD**: `4a54c7f` (operator scripts wrap Prometheus
  queries in `docker exec`).
- **Session**: read-only. No code/config changed on the box.
- **Verdict**: **partial coverage of the design strategy set**. Five of the
  seven designed strategies (C1, C2, C4, C5a, C5b) contribute zero trades
  over the entire DB lifetime. Two strategies (C4, C5a) lack source files
  entirely. Two follow-ups raise data-integrity concerns
  (`corr14d=0.000`, HALT/equity mismatch).

## Why this audit ran

The 48h sprint and post-sprint patches (`project_aaats_48h_sprint.md`,
`project_aaats_grafana_v2.md`, `project_aaats_share_assertion.md`) focused
on plumbing and tooling. This audit measures whether the strategies
themselves are firing as designed, by cross-referencing
`data/paper_trades.db` against the runner/strategy logs and the design
intent (BTC+ETH stat-arb for C1, HMM=BULL momentum breakouts for C2,
scanner-driven alt reversion for C3, new-listing flips for C4, directional
perps for C5a, range-bound bollinger for C6; C5b funding-arb HALTED).

## P0 — Sanity

- `docker ps`: `aaats-paper-crypto` Up 2 days (healthy).
- `docker inspect`: `RestartCount=0`, `State=running`,
  `StartedAt=2026-05-16T05:21:36Z`.
- `data/state/risk_engine_state.json`:
  `peak=110.0, last_equity=103.057` → drawdown **-6.31%** (deeper than the
  -4.2% snapshot quoted in the audit brief, but inside the design halt
  band).
- Cycle log: latest is cycle 220, `done in 13.3s — sleeping 887s` ⇒ **15-min
  cadence intact** (design 900s).

## P1 — Trade activity by strategy

Schema in use: `paper_trades(timestamp TEXT, strategy TEXT, action TEXT, …)`.
Total rows: **54**.

### Last 24h

| Strategy | Action | Count |
|---|---|---|
| C3_altcoin_reversion | BUY | 3 |

All three are scanner-driven (`BCH/USDT`, `LAYER/USDT`, `CHIP/USDT`); no
SELLs.

### Last 7 days

| Strategy | Action | Count |
|---|---|---|
| C3_altcoin_reversion | BUY | 29 |
| C3_altcoin_reversion | SELL | 21 |
| C6_bollinger_range | BUY | 2 |
| C6_bollinger_range | SELL | 2 |

Net **+8 open C3 positions** accumulated over 7 days. No SELL fired in
the last 48h (last C3 SELL: `2026-05-16T12:37:12Z`).

### Most recent trade per strategy

| Strategy | Last trade | Rows |
|---|---|---|
| C3_altcoin_reversion | 2026-05-18T12:07:17Z | 50 |
| C6_bollinger_range   | 2026-05-15T08:09:38Z | 4 |
| C1_stat_arb          | — | 0 |
| C2_momentum_breakout | — | 0 |
| C4_new_listing       | — | 0 |
| C5a_directional_perps | — | 0 |
| C5b_funding_arb      | — | 0 |

## P2 — Scanner pipeline status

Scanner is **firing every cycle** (15-min cadence) and the dynamic universe
is wired into C3:

```
[universe] kept=19  rejected_by={quote:2923, low:511, leveraged:52, crashing:33, denylist:24}
[scanner] universe=19 fetched=19 skipped=0  candidates: c3=4, c6=1
[scanner] c3 top3: BCH/USDT(-2.942), LAYER/USDT(-2.054), CHIP/USDT(-1.925)
[allocator] c3 picks (top 3): BCH/USDT, LAYER/USDT, CHIP/USDT
[sentiment] F&G=28 (Fear)
[scanner] final plan: c3=[BCH, LAYER, CHIP]  c6=None  fg=28  skip_c3=False  skip_c6=False
```

- No `Exception` / `fallback` / `falling back to SYMBOLS` lines in 24h logs.
- C3 trades match scanner picks 1-for-1 (no hardcoded SOL/LINK/AVAX
  fallback observed).
- F&G=28 (Fear) → neither `skip_c3` nor `skip_c6` triggered.
- For C6 the scanner picks (ONDO/ARB/APT/CHIP) are **rejected downstream**:
  - `correlation_guard` skips with `c6 skip ONDO/USDT (cluster OTHER already at cap)`;
  - `bollinger_range` rejects survivors with `volume below floor — skip`
    or `trade size $3.73 < min $5.00 — skip`.
  - Then the strategy iterates a **hardcoded BTC/ETH/SOL** set (last
    cycle: %B=0.498/0.513/0.454, RSI=38.8/35.1/38.9 — nowhere near the
    extremes Bollinger requires).

## P3 — Cycle timing and HMM regime

- Cycle interval: ~887–890s sleep + ~10–13s exec = **15-min cadence**, as
  designed.
- HMM regime mix is heterogeneous per-coin. Cycle 220 (2026-05-18T12:07Z)
  voted `regime=BEAR_TREND(1.00) → HOLD` for 5 of 7 coins, with one
  `RANGE_BOUND` and one `BEAR_TREND(0.84)` flipping to BUY votes but the
  aggregate vote was HOLD (conf 0.49–0.80).
- C3 trade records carry `regime=RANGE_OR_BULL` — i.e. C3's own gate
  (not the per-coin HMM) is what permitted entry.

## P4 — Design intent vs actual behaviour

| Strategy | Designed-for | Actually firing on | Gate respected? | Notes |
|---|---|---|---|---|
| C1 stat_arb | BTC, ETH pair-trade | Instrumented every cycle; **0 trades all-time**. z-score reached **+4.74** at 2026-05-17T23:52Z. | Health gate blocks: `eg_p=0.6867 corr14d=0.000`. | `corr14d=0.000` is **suspect**: realised 14-day BTC/ETH correlation is ~0.8. Likely upstream data-feed bug (empty/short series). |
| C2 momentum_breakout | BTC, ETH on HMM=BULL | **0 invocations** in 48h logs. Module exists at `/app/trading/momentum_breakout.py`. | Cannot test — strategy never runs. | Runner does not appear to call C2; investigate `live_paper_runner.py` wiring. |
| C3 altcoin_reversion | scanner-driven alts, regime ≠ BEAR | BCH, LAYER, CHIP, XPL, LTC, FET, SPK, TRX, ONDO, … (scanner-driven). 29 BUY / 21 SELL in 7d. | `regime=RANGE_OR_BULL` tag present on each trade. | **Asymmetry**: 8 net unclosed positions accumulating; no SELL in last 48h. Worth checking the C3 exit conditions vs. price action. |
| C4 new_listing | new Binance listings | **0 — module does not exist** in `/app/trading/`. | n/a | `ls /app/trading/` returns: `altcoin_reversion, bollinger_range, funding_arb, momentum_breakout, stat_arb` only. |
| C5a directional_perps | perps directional | **0 — module does not exist** in `/app/trading/`. | n/a | Same `ls` evidence as C4. |
| C5b funding_arb | perps funding-rate | **0** | HALT respected ✓. | Module file present but never logged in 7d. |
| C6 bollinger_range | TRX (range_bound) or scanner picks | BTC, ETH, SOL (hardcoded) — never trips. Scanner picks (ONDO/ARB/APT/CHIP) blocked by correlation_guard + volume floor. | Mixed per-coin regime. | Last trade 2026-05-15. Scanner→C6 path is structurally OK but every cycle the picks get filtered out before reaching the strategy. |

## P-extra — Two follow-ups worth opening

### 1. HALT CRYPTO logged 479x in 24h while trades still execute

`risk.engine` emitted `HALT CRYPTO — CRYPTO drawdown -19.5% breached -15% halt threshold`
**479 times** in the last 24 hours, yet all 3 C3 BUYs in that window were
recorded with `risk_action=ALLOW`. Two issues:

- **Drawdown disagreement**: the risk engine reports -19.5%, but
  `risk_engine_state.json` shows `peak=110, last_equity=103.06` (= -6.31%).
  These two numbers should not diverge.
- **HALT not enforced**: matches the known `halt_on_critical=False`
  band-aid (memory `project_aaats_48h_sprint.md`). Trades go through
  regardless. Acceptable as a known band-aid, but the engine spamming
  ERROR-level lines that don't reflect the state file is noise.

Not for this session, but worth its own ticket.

### 2. `stat_arb` health gate: `corr14d=0.000` is almost certainly wrong

`SKIP ENTRY BTC/USDT_ETH/USDT: health gate failed (eg_p=0.6867 corr14d=0.000)`
on every cycle for ~12h. A 14-day BTC/ETH correlation of exactly zero is
not physically plausible — usually 0.7–0.9. The Engle-Granger p-value
(0.69 > 0.05) might be a legitimate breakdown of cointegration during a
risk-off move, but a literal zero correlation reads as a data plumbing
bug (likely empty/short price series for one leg).

If corr14d is fixed and the pair re-cointegrates, C1 has a sitting signal
(z=+4.74 reached overnight) ready to fire. **Worth a dedicated session.**

## Done criteria — outcomes

1. ✓ P0 sanity confirmed container healthy, peak=$110, equity=$103.06.
2. ✓ P1 activity tables surfaced (24h + 7d + most-recent-per-strategy +
   all-time).
3. ✓ P2 scanner status: firing normally, C3 path consuming picks, C6 path
   structurally OK but downstream guards eat every pick.
4. ✓ P3 cycle interval = 15 min as designed; HMM mostly BEAR/HOLD.
5. ✓ P4 design-vs-actual table delivered.
6. ✓ Audit doc filed (this file). Follow-up tickets recommended on the
   HALT/equity mismatch and on the `corr14d=0` data bug.

## What was NOT changed

This was a read-only session. No code, container, or `paper_trades.db`
edits. C5b confirmed HALT-effective (zero rows). No deploys, no kills.
