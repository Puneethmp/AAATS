# BUY-side share-recording audit (2026-05-15)

## Context

The SELL-side `_record` fix (2026-05-15_record_fix) made C3/C6 SELL rows
carry shares derived from the stored BUY position's `size_usd / entry_price`
rather than `size_usd / exit_price`. The share-equality assertion deployed
on top (2026-05-15_share_assertion) compares `sell.shares` against the
FIFO-matched BUY row's `shares` at INSERT time.

If BUY-side recording itself has a bug — e.g., shares computed from
`size_usd / current_price` where `current_price` is NOT the entry price, or
where BUY shares is a separate computation from SELL shares with no shared
source-of-truth — then the assertion fires falsely and diagnoses the
record fix as broken when the BUY side is the real issue.

This audit classifies every BUY callsite in `trading/`, `strategies/`, and
`execution/`.

## Methodology

Searched for the BUY-recording pattern with:

```
grep -rn -E "_record\(.*['\"]BUY['\"]|record_trade\(.*['\"]BUY['\"]|action.*=.*['\"]BUY['\"]" trading/ strategies/ execution/
grep -rn -E "shares\s*=.*\/.*price|qty\s*=.*\/.*price|shares\s*=.*size_usd|size_usd\s*/.*price" trading/ strategies/ execution/
```

Each callsite was read with surrounding context to determine:

1. How BUY shares is computed at insert time.
2. How the matching SELL recomputes (or reuses) shares.
3. Whether the two paths share an actual source of truth.

## Classification table

| # | Strategy | BUY file:line | BUY shares formula | SELL shares formula | Verdict |
|---|---|---|---|---|---|
| 1 | C1 / C4 generic directional (live_paper_runner) | [live_paper_runner.py:902](trading/live_paper_runner.py#L902) | `shares = sizer(...).shares` (true sized fill quantity, ATR-Kelly with risk-engine + ML scale) — stored in `mkt_pos[symbol]["shares"]` | `sh = pos["shares"]` (the stored BUY quantity) | **Clean** — single source of truth, stored at BUY, reused verbatim at SELL |
| 2 | live_paper_runner ATR trailing exit | n/a (SELL only) | — | `sh = pos["shares"]` | **Clean** |
| 3 | paper_loop generic | [paper_loop.py:174](trading/paper_loop.py#L174) | `actual_shares` (sized + risk-gate-reduced); stored in `Position(shares=actual_shares,...)` | `pos.shares` (stored) | **Clean** |
| 4 | C2 momentum_breakout | [momentum_breakout.py:330](trading/momentum_breakout.py#L330) | `trade_usd / current_price` (current_price IS the entry price, line 318) | `size / entry` where `size=pos["size_usd"]`, `entry=pos["entry_price"]` ([momentum_breakout.py:276](trading/momentum_breakout.py#L276)) | **Clean by reconstruction (fragile)** — separate computations, but inputs are bit-exact-equal preserved state. `trade_usd == state.size_usd` and `current_price == state.entry_price`, so the two divisions yield identical IEEE-754 doubles. Assertion's `delta > 1e-9` margin holds. No SoT — any future drift in either formula breaks invisibly. |
| 5 | C3 altcoin_reversion | [altcoin_reversion.py:557-562](trading/altcoin_reversion.py#L557-L562) via `_record(action="BUY", price=current_price, size_usd=trade_usd, shares=None)` → fallback `round(size_usd/max(price, 1e-9), 8)` ([altcoin_reversion.py:372](trading/altcoin_reversion.py#L372)) | `_record(SELL, shares=round(pos["size_usd"]/max(pos["entry_price"], 1e-9), 8))` ([altcoin_reversion.py:482-484](trading/altcoin_reversion.py#L482-L484)) | **Clean** — both sides use the same rounded(8dp) `size_usd/entry_price` formula. Inputs preserved in state.json. Identical values stored. This is the post-fix state. |
| 6 | C6 bollinger_range | [bollinger_range.py:360-362](trading/bollinger_range.py#L360-L362) via `_record(action="BUY", price=price, size_usd=trade_usd, shares=None)` → fallback `round(size_usd/max(price, 1e-9), 8)` ([bollinger_range.py:188](trading/bollinger_range.py#L188)) | `_record(SELL, shares=round(pos["size_usd"]/max(pos["entry_price"], 1e-9), 8))` ([bollinger_range.py:298-299](trading/bollinger_range.py#L298-L299)) | **Clean** — same pattern as C3. |
| 7 | **C5b funding_arb** | [funding_arb.py:164](trading/funding_arb.py#L164) | `CAPITAL_PER_SYMBOL / 1.0 = 25.0` (placeholder price 1.0 — "delta-neutral notional") | `size_usd / 1.0` where `size_usd = position["capital_per_leg"] * 2 = 50.0` ([funding_arb.py:190,195](trading/funding_arb.py#L190-L195)) | **BUGGY** — BUY records 1× leg notional, SELL records 2× leg notional. **Delta = $25.0 on every close.** See "Active bug — C5b" below. |

## Active bug — C5b funding_arb

### What

`trading/funding_arb.py` records its BUY leg with `shares = CAPITAL_PER_SYMBOL`
($25, the per-leg notional) but the matching SELL leg with
`shares = position["capital_per_leg"] * 2` ($50, the round-trip notional for
the delta-neutral pair).

Every C5b `_close_position` call will write a SELL row whose shares is exactly
2× the matching BUY row's shares. The share-equality assertion deployed today
will WARN with `delta=25.0` on every C5b SELL.

### Severity vs. C3/C6 class

- C3/C6 pre-fix dust: ~$0.10–$0.30 residual per closed position from the
  `size_usd / exit_price` recomputation, dependent on price move.
- C5b: **$25.00 per close** — flat, structural, every close, independent of
  price action. Two orders of magnitude worse.

### Is it live?

Yes. Confirmed by:

- [live_paper_runner.py:1510-1513](trading/live_paper_runner.py#L1510-L1513)
  imports and calls `run_funding_arb_crypto(portfolio["crypto"])` every cycle.
- Banner at [live_paper_runner.py:1634](trading/live_paper_runner.py#L1634):
  `Strategies: C1 stat-arb, C2 momentum, C3 alt-reversion, C5b funding-arb`.
- Independent of the reconciler exclusion path (reconciler skips C5b state
  reconciliation, but the strategy still runs and still writes BUY/SELL rows
  to paper_trades.db).

Whether a C5b `OPEN` has actually fired since deploy depends on funding-rate
thresholds and capital availability; this audit does not query the DB
(see [2026-05-15_state_db_delta_snapshot.md](2026-05-15_state_db_delta_snapshot.md)
for runtime C5b activity).

### What the fix should look like (out of scope this session)

Option A — make BUY and SELL agree on what "shares" means for a delta-neutral
pair: pick a single notional (either 1× per-leg or 2× round-trip) and record
both sides with it. Recommended: 2× round-trip, since that's the real capital
debited/returned per [funding_arb.py:139,181](trading/funding_arb.py#L139).

Option B — don't route C5b through `paper_trader.record_trade` at all. C5b
isn't a directional position; "shares" is a notional placeholder. A separate
`record_funding_event` path that doesn't pretend to be a spot trade would
remove the assertion conflict and clean up Grafana semantics. Higher-effort.

Either way: the share-equality assertion will mis-fire on C5b closes
**as soon as any C5b position closes after this deploy**. If the operator
sees a WARN with `strategy=C5b_funding_arb` and `delta=25.0`, that is THIS
bug, not the C3/C6 fix breaking.

## Legacy / out-of-path BUY callsites (not live, classified for completeness)

The grep also surfaced four BUY callsites that are **not invoked by the live
`aaats-paper-crypto` container**. They are listed so a future grep-and-fix
sweep doesn't mistake them for active strategy code. The live entry chain
is `deployment/docker-compose.yml` → `trading/paper_loop.py` (now a thin
delegator at [paper_loop.py:392](trading/paper_loop.py#L392)) →
`trading/live_paper_runner.main()`.

| # | Callsite | BUY shares formula | Why dead | Risk if resurrected |
|---|---|---|---|---|
| L1 | [execution/crypto_runner.py:153](execution/crypto_runner.py#L153) | `shares = round(size.shares, 6) or round((_CAPITAL_USDT * _POSITION_PCT) / price, 6)`; SELL at [:165](execution/crypto_runner.py#L165) recomputes `round((_CAPITAL_USDT * _POSITION_PCT) / max(entry, 1e-9), 6)` — **6-dp rounding can diverge from BUY rounding** | Invoked only by [execution/orchestrator.py:35](execution/orchestrator.py#L35), [scripts/continuous_runner.py:79](scripts/continuous_runner.py#L79), [scripts/phase1_runner.py:137](scripts/phase1_runner.py#L137). None are in the docker entrypoint. | Resurrecting orchestrator or phase1_runner against the live DB will fire share-equality WARNs on its SELLs because BUY/SELL rounding-precision mismatch. Same bug class as C5b but per-trade $-scale (cents). |
| L2 | [execution/india_runner.py:213](execution/india_runner.py#L213) | Same pattern as L1, 2-dp rounding for India equities | Same orchestrator-only invocation path | Same as L1. |
| L3 | [strategies/us/momentum.py:150](strategies/us/momentum.py#L150), [strategies/us/mean_reversion.py:129](strategies/us/mean_reversion.py#L129) | `shares = int(risk_per_trade / price_risk)` — risk-budget sizing, no record_trade call from these modules | No live runner imports them | n/a — these never write to paper_trades.db. |

## Final classification summary

- **Clean** (single SoT or bit-exact reconstruction): 6 live callsites — C1/C4
  generic, paper_loop generic, ATR exit, C2 momentum, C3 altcoin_reversion,
  C6 bollinger_range.
- **Buggy** (BUY/SELL shares structurally diverge): 1 strategy — **C5b
  funding_arb** ($25.00/close).
- **Uncertain / human review needed**: none.
- **Dead-code, buggy if resurrected**: 2 callsites — crypto_runner, india_runner.

The C3/C6 record fix is correctly anchored. The watcher's first natural
SELL on C3 or C6 should produce no WARN. The first natural SELL on C5b,
if/when it happens, will produce a $25.00 delta WARN unrelated to the C3/C6
fix correctness.

## 2026-05-15 follow-up: dead-code paths deleted

Dead-code paths `execution/crypto_runner.py` and `execution/india_runner.py`
deleted on 2026-05-15, along with the upstream chain that referenced them:
`execution/orchestrator.py`, `scripts/continuous_runner.py`,
`scripts/phase1_runner.py`, `scripts/phase1_local_monitor.py`, and the
top-level `main.py` (Dockerfile default CMD that nothing live invoked —
every compose service overrides `command:`).

Surviving doc/UI references were updated to point at the production
entrypoint `python trading/paper_loop.py --market <market>`; the Dockerfile
CMD was replaced with a fail-fast sentinel so that any future compose
service without an explicit `command:` halts loudly instead of silently
falling back to a resurrected orchestrator.

Recoverable via `git log --diff-filter=D --name-only`.
