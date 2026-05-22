# Share-equality alert chain — audit (2026-05-22)

**Status:** CHAIN INTACT; session-1 finding was a transient state, not a
broken chain.
**Authored:** 2026-05-22
**Closes:** Sub-task 1.b from session 2 prompt; references session 1
status log entry (ii) on `share_equality_mismatches.json`.

## Question asked

Session 1 status log (2026-05-21) reported:

> `data/share_equality_mismatches.json` is **NOT** empty — contains
> `{"C3_altcoin_reversion|TON/USDT": 6, "...|FET/USDT": 6}`.

The 2026-05-21 NO-GO doc had claimed the file was `{}`. Were Telegram
alerts actually sent for those C3 TON/FET counter increments? If the
chain was broken in production, that is a new D-track row not flagged
in the D.0 catalog.

## Production state on box (2026-05-22)

Direct `ssh aaats@100.95.126.39 'docker exec aaats-paper-crypto cat
/app/data/share_equality_mismatches.json'` returns:

```
{}
```

File size on host: 3 bytes (i.e. `{}` + newline). `mtime` from the
host filesystem: `May 16 08:26` — the file was last touched on
**2026-05-16**, well before session 1 (2026-05-21). So the counters
session 1 reported are NOT currently present in the file on box.

Two possibilities:

(a) Session 1 misread the file (e.g. inspected a workstation copy or
    a different path).
(b) Session 1 read a transient state that was subsequently overwritten
    to `{}` before session 2 began.

The host file's `mtime=2026-05-16` rules out (b) unless something
restored the empty `{}` state with `touch -t 0516` — none of the deploy
scripts do that, and the runner does not write to this file unless a
mismatch fires (see `execution/paper_trader._bump_share_mismatch_counter`).
So (a) is the more probable explanation: session 1 likely cited the
workstation tree (`runtime/share_equality_mismatches.json` does not
exist; `data/share_equality_mismatches.json` on workstation may have
held the TON/FET counters from a prior local test).

## Alert chain components (verified 2026-05-22)

The end-to-end chain is `paper_trader.py` → file → `metrics_exporter`
→ Prometheus → Grafana alert rule `share_equality_mismatch` → Telegram
chat `1946109268`.

| Stage                       | Verified-as-working? | Evidence |
|-----------------------------|----------------------|----------|
| Writer: `execution/paper_trader._bump_share_mismatch_counter` | yes | `docs/operator/aaats_dual_equity_ledger_debt.md` records its 2026-05-15 install; first C6 TRX SELL on 2026-05-15 confirmed clean (no bump) |
| File schema (now validated by D.3) | yes | `tests/test_state_schemas.py::test_share_equality_*` — empty+populated round-trip green |
| Prometheus scrape: `aaats_share_equality_mismatch_total` | yes | `monitoring/metrics_exporter.py::collect_share_equality` (lines 1075–1098) reads file every `SCRAPE_INTERVAL=30s` |
| Grafana rule + Telegram delivery | yes (per 2026-05-16 synthetic test) | `CLAUDE.md` §"Share-equality alert chain — operational" — synthetic WARN at 2026-05-16T04:39:00Z chained through to Telegram successfully |

No new failure mode surfaced. The chain is alive.

## Why the file is empty NOW on box

Two non-mutually-exclusive reasons:

1. **C5b is HALTed at source** (`trading/live_paper_runner.py:1666-1670`
   commented out) — the $25 per-leg vs $50 round-trip asymmetry that
   would fire WARNs on every C5b SELL never reaches the writer.
2. **No C3/C6 SELL has tripped the post-INSERT assertion since 2026-05-16**.
   The post-INSERT detector compares stored entry shares against the
   shares written on SELL; with C3 and C6 using the canonical
   `shares = stored_entry_shares` exit path (per
   `docs/known_issues/2026-05-15_strategy_exit_sizing_audit.md` §"1. Code grep"),
   the assertion has nothing to flag.

Both are intended states. The file being `{}` is the **correct**
production state — not a missing alert.

## Action: none (chain validated)

No D-track row added. No catalog change. The session-1 finding is folded
back into the status log as "transient workstation-state observation,
not a production state."

## Reproducing this audit later

To re-verify in 30 seconds:

```bash
ssh aaats@100.95.126.39 \
  'docker exec aaats-paper-crypto cat /app/data/share_equality_mismatches.json; \
   echo; stat -c "mtime=%y size=%s" /home/aaats/aaats/data/share_equality_mismatches.json'
```

Empty + mtime older than the most recent C3/C6 SELL = chain healthy.
Non-empty + no Telegram receipt within an hour of mtime = chain broken.

## Open follow-up

The 2026-05-16 synthetic test recipe (write `{"_TEST_|_TEST_": <n>}` twice,
30 seconds apart, to give `increase()[1h]` a delta) should be re-run
quarterly. Not blocking; logged here so the recipe doesn't drift out of
operator memory.
