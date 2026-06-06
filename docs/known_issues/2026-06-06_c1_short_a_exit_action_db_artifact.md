# 2026-06-06 — C1 SHORT_A exit rows log wrong `action` → phantom ±$84 ETH/BTC in DB-level net-open

**Status:** benign, record-only. No open position, no cash impact, no code change required (C1 retired).

## Symptom

A DB-level net-open reconciliation of `runtime/paper_trades.db` shows a persistent
**+0.041681 ETH (~$84.05) net-long** and **−0.000566 BTC (~$84.05) net-short** attributed to
`C1_stat_arb`, while `stat_arb_state.json` and `paper_positions.json` are both empty.
L5 ledger-divergence does not fire (pair strategies C1/C5b are deliberately passed through —
see `docs/known_issues/2026-05-24_l6_reconciler_posture_during_soak.md`).

## Root cause (trade-level, verified 2026-06-06 against origin/main de60bc46)

C1 logs the **EXIT row of SHORT_A round trips with the same `action` as the ENTRY row**
instead of the reverse, on both legs:

| Leg | LONG_A entry/exit | SHORT_A entry/exit |
|---|---|---|
| BTC/USDT (leg A) | BUY → SELL ✅ | SELL → **SELL** ❌ (should be BUY) |
| ETH/USDT (leg B, hedge) | SELL → BUY ✅ | BUY → **BUY** ❌ (should be SELL) |

Three SHORT_A round trips (2026-05-26 16:27Z, 2026-05-27 22:01Z, 2026-05-28 03:46Z,
shares 0.006755 / 0.007091 / 0.006994 ETH) each net +2× shares ETH and −2× shares BTC
in the DB. 2 × (0.006755 + 0.007091 + 0.006994) = **0.041680 ETH** — matches the phantom
exactly. Combined BTC+ETH net value across all 32 C1 rows: **$0.0083** (value-neutral pair;
cash and `pnl` columns are correct — only the `action` column is wrong on 3 exit rows).

All 8 ETH round trips are share-matched entry↔exit; C1's internal ledger closed everything
correctly. Last C1 trade 2026-05-28T14:31Z; C1 retired (Phase 3.5), so no new rows will accrue.

## Operational guidance

- Any future DB-level net-open reconciliation must expect this fixed ±$84 ETH/BTC offset in
  `C1_stat_arb` historical rows, or exclude C1 (consistent with the existing reconciler
  `WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb')` posture).
- Do NOT "fix" the 3 historical rows in place — the DB is the immutable trade record;
  this memo is the correction.
- If a pair strategy is ever built again, its trade recorder must derive `action` from the
  leg side at exit, not echo the entry action (add to pre-ship checklist alongside the
  reconciler pair-strategy blind-spot fix paths).

## Verification recipe

```python
# net per symbol for C1 — expect +0.041680 ETH / −0.000566 BTC, combined value ≈ $0.008
SELECT symbol,
  SUM(CASE WHEN action='BUY' THEN shares ELSE -shares END) net_sh,
  SUM(CASE WHEN action='BUY' THEN value ELSE -value END)  net_val
FROM paper_trades WHERE strategy='C1_stat_arb' GROUP BY symbol;
```

Source session: 2026-06-06 Cowork forensic trace (operator-requested). Not yet committed —
commit from next Claude Code session (Cowork sandbox can't clear its own `.git/index.lock`
on the mounted filesystem; avoid git writes from here).
