# L6 reconciler posture during D.5 paper soak

**Status:** VERIFIED IN PLACE (no change shipped; documenting current posture)
**Authored:** 2026-05-24 (operator-departure content-correctness sprint)
**Supersedes:** the L6 description in the operator's pre-departure sprint prompt
  (which assumed Path A had not landed)

## Background

The 2026-05-24 pre-departure sprint prompt called for L6 to mute reconciler
HALT cascades caused by C1_stat_arb pair-strategy false positives. The
prescribed action was:

> Find the C1 stat_arb config: halt_on_critical: True → halt_on_critical: False

This action would **regress** the system. Path A from
[`docs/known_issues/2026-05-23_btc_eth_ledger_drift.md`](2026-05-23_btc_eth_ledger_drift.md)
landed in session 5 on 2026-05-23 with both:

1. C1 added to the Source-B SQL exclusion in `scripts/reconcile_intracycle.py:330`:
   ```python
   WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb')
   ```
2. `trading/live_paper_runner.py:2013` flipped back to:
   ```python
   _rec = reconcile_now(markets=_markets_to_check, halt_on_critical=True)
   ```

Setting `halt_on_critical=False` now would lose the post-cycle catastrophic-
drift gate without addressing any real problem. The C1 pair-strategy
blind spot it was meant to mute is already gone.

## Current verified posture (2026-05-24 on box `aaats@100.95.126.39`)

```
$ grep -n 'halt_on_critical\|NOT IN' \
    /home/aaats/aaats/trading/live_paper_runner.py \
    /home/aaats/aaats/scripts/reconcile_intracycle.py | head
trading/live_paper_runner.py:2013:                _rec = reconcile_now(markets=_markets_to_check, halt_on_critical=True)
scripts/reconcile_intracycle.py:330:            "WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb') "
```

This is the Path A state. It is what should remain through the soak.

## Why L5 does not duplicate this

L5 (ledger divergence detector, shipped 2026-05-24 — see
[`execution/paper_trader.py`](../../execution/paper_trader.py) at
`compute_ledger_divergence` / `assert_ledger_consistency_or_halt`) runs
PRE-cycle at the per-strategy granularity. The intracycle reconciler runs
POST-cycle at the per-symbol granularity. They are complementary:

| Layer | When | Granularity | Halt level | Pair-strategy view |
|---|---|---|---|---|
| reconciler (Path A) | end of cycle | (market, symbol) | whole runner (operator halt) | excluded from Source B |
| L5 divergence detector | start of cycle | strategy | per-strategy (strategy_halt) | state-side pass-through; effectively skipped |

Both currently skip C1 / C5b pair strategies for divergence detection.
Full pair-strategy divergence detection is Path C (unified ledger sprint),
deferred to post-operator-return work per the original memo's recommendation.

## Why this matters for the 30-day soak

If a future session sees this memo and is tempted to:

- Flip `halt_on_critical` back to `False` — DON'T. That regresses the
  catastrophic-drift gate that has been live since session 5.
- Add C1 / C5b to L5's divergence detection — that's Path B / Path C work
  per the original memo. Both require a refactor large enough to need
  operator approval; do not attempt during the soak.

## Re-enable acceptance criterion (full pair-strategy detection)

To re-instate full C1 / C5b divergence detection (closing Bug A from the
original memo):

1. Implement the unified-ledger writer (Path C) so both pair strategies
   write per-leg position records into a single positions table.
2. Update `_read_db_notional` in `execution/paper_trader.py` to derive
   pair-strategy notional from the unified table rather than passing the
   state value through.
3. Update `scripts/reconcile_intracycle.py` Source A to recognise the
   pair schema (Path B), then remove the C1 / C5b exclusion in Source B.
4. Re-run the L5 adversarial test suite with synthetic pair-leg drift to
   confirm halt fires correctly.

## Calendar reminder

When operator returns from soak (~2026-06-24), revisit this memo as part
of the [PHASE 0 verification](../runbooks/operator_return_resume_procedure.md)
and decide whether to schedule the unified-ledger sprint.
