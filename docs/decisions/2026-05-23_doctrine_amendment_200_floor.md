# Doctrine amendment: paper book floor $100 → $200

**Authored:** 2026-05-23 (Cowork session, operator-approved in-line)
**Amends:** `docs/decisions/aaats_locked_doctrine_2026_05_14.md` (memory `aaats_locked_doctrine_2026_05_14`) — specifically the "$100 initial live floor" line. All other doctrine elements (5 injection gates, kill triggers, $50/mo split, Phase 0 mandatory) unchanged.

**Scope of change:** paper book reset baseline raises from $100 to **$200**. Live-flip first-tranche size **stays $25** per locked doctrine — this amendment does NOT escalate the live tranche. The $200 is the paper soak starting equity for the D.5 30-day no-intervention soak.

## Why this amendment exists

The operator is going out of station from 2026-05-25 for a multi-day period. To run the D.5 30-day soak autonomously while away, the paper book must be reset (current state: -33.4% drawdown from $131.32 peak, $87.45 equity, past portfolio-kill threshold; organic recovery in 3 days is not plausible). The reset is a fresh start; the floor amount is therefore a free parameter.

The operator selected $200 (double the original $100 doctrine floor) on 2026-05-23 to increase the absolute-dollar headroom on per-position notional sizing. At $100 floor, a 10% position size is $10 — close to Binance USDT spot min-lot for several symbols, especially after a 20% drawdown. $200 floor gives a 2x safety margin on tradability.

## Cascade through the system

### Risk thresholds (engine.py absolute values change; percentage thresholds unchanged)

| Threshold | % (unchanged) | Old absolute ($100) | **New absolute ($200)** |
|---|---|---|---|
| Per-trade stop | -2% | -$2.00 | **-$4.00** |
| Per-market kill (HALT_MARKET) | -15% | -$15.00 | **-$30.00** |
| Portfolio kill (HALT_ALL) | -20% | -$20.00 | **-$40.00** |
| Locked-doctrine `-5%` auto-revert | -5% | -$5.00 | **-$10.00** |

No code change required — all thresholds in `risk/engine.py` are percentage-based ([risk/engine.py:38-39](../../risk/engine.py#L38-L39)). The absolute-dollar values are derived at runtime from current equity.

### Position sizing (mechanically scales)

Strategy max position sizes are equity-fractional. At $200 starting equity:

- C3_altcoin_reversion default sizing (currently ~10% per position from B.0 diagnostic): **~$20 per position** vs $10 prior. Comfortably above Binance USDT min-lot.
- C6_bollinger_range similar.
- C1_stat_arb pair sizing: ~30% notional per leg per `trading/stat_arb.py:55-59` default config. **$60 per leg** vs $30 prior. Both legs trade-able.

No code change required.

### Tranche gates G1–G5 (unchanged, but recalibrate against new soak baseline)

The doctrine's tranche escalation gates G1–G5 govern live-flip tranche additions, NOT paper sizing. They remain:

- G1: $25 live tranche (unchanged)
- G2–G5: per locked doctrine, no change

When C.7 evaluates the B.3 4-week soak's "final equity ≥ starting equity" criterion, the comparison is against **$200 (the soak's starting equity)**, not against the original $100 doctrine floor. If B.3 ends at $200 or higher, C.7 passes.

### Watch out — the -5% auto-revert is on LIVE mode only

The locked doctrine's "-5% auto-revert" applies to **live mode only** ("if live tranche drawdown ≥ 5% within first week, return capital"). Paper book hitting -5% from $200 ($190) does NOT trigger any auto-revert — it triggers a normal soft warning at most. The auto-revert is a live-money safety, not a paper safety.

## Operational implications

1. **State reset required.** The current paper book state (peak $131.32, equity $87.45, with frozen open positions) must be wiped and reinitialized to $200 starting equity. Execution path:
   ```bash
   # On box, after session 8 [0] MTM gap fix ships:
   docker compose -f deployment/docker-compose.yml stop aaats-paper-crypto
   docker volume rm deployment_state-crypto-paper
   docker volume create deployment_state-crypto-paper
   # Then update initial-equity config to $200 and start:
   docker compose -f deployment/docker-compose.yml up -d aaats-paper-crypto
   ```
   Exact script will live at `scripts/reset_paper_book_200.py` (paramiko-SCP pattern per CLAUDE.md).

2. **D.5 day-1 trigger fires within ~24h of reset.** The reset gives clean state; first daily digest after reset should report `Action needed: NONE` (assuming no immediate strategy halt or kill-switch fire). That digest = D.5 day-1. The 30-day soak clock starts there.

3. **B.3 4-week soak baseline becomes $200.** The C.7 profitability gate ("final equity ≥ starting equity") compares the B.3 soak's final equity against **$200**, not $100. A bot that ends the 4-week soak at $199 fails C.7. A bot that ends at $201 passes.

4. **Historical paper P&L pre-reset is discarded.** The -$5.63 realized loss on C3, the -$0.13 on C6, and the -33.4% peak-to-trough are wiped. The post-reset book has zero trade history. This is intentional (clean state for the soak) but means strategy diagnostic data from sessions 1-7 no longer reflects the live ledger; it remains valid as historical evidence about strategy behavior.

## Cross-references and supersedence

This document amends — **not replaces** — the locked doctrine. The doctrine memo `aaats_locked_doctrine_2026_05_14.md` should be read with this addendum applied to the "$100 initial live floor" line; all other doctrine elements (5 injection gates, kill triggers, $50/mo split, Phase 0 mandatory, $25 first live tranche, G1–G5 escalation) remain authoritative.

Related work:
- `docs/runbooks/2026-05-23_operator_away_protocol.md` — the umbrella runbook this amendment exists to enable.
- `docs/decisions/2026-05-22_live_flip_rebuild_plan.md` C.7 — profitability gate, now evaluated against $200 baseline.
- `docs/decisions/2026-05-22_b15_backtest_harness.md` — the harness that must run BEFORE the reset to validate the strategy stack has historical edge.
- Memory: `aaats_2026_05_23_doctrine_amendment_200`.

## What this amendment is NOT

- NOT an escalation of the live-flip tranche size. G1 stays $25.
- NOT an authorization to skip the C.7 gate. Profitability validation still required.
- NOT a change to the percentage-based risk thresholds. Only the absolute-dollar values they imply change.
- NOT a green-light to start the D.5 soak. The B.1.5 backtest stress-test (added 2026-05-23) is the gate that decides whether the strategy stack is worth running 30 days on. Backtest first, reset second, soak third.

## Reversibility

Trivial. If after backtest the operator decides $200 is wrong, change the initial-equity config back to $100 (or any other value) before the volume-create + container-start step in the reset script. The amendment is "in effect" only once the state-crypto-paper volume is initialized at $200. Pre-reset, this is paper on paper.
