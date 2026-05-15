# Watcher JSON-parse error on delta-compute

**Filed**: 2026-05-15 (low priority — informational only)
**Watcher**: [scripts/watch_first_sell.py](../../scripts/watch_first_sell.py) (now deprecated; see header banner)

## Observation

During the first post-deploy SELL on 2026-05-15 (C3 ICP/USDT @ $2.6810 × 1.024218 shares), the watcher's delta-compute step emitted:

```
[delta] could not compute delta: Expecting value: line 1 column 1 (char 0)
```

The error is a `json.JSONDecodeError` thrown when the watcher tried to parse an empty (or whitespace-only) payload from its delta source.

## Why this is non-blocking

The share-equality assertion path is independent of the delta-compute path. The same SELL emitted `share-assertion: NO WARN — equality holds on first SELL.` — the critical signal we cared about. The delta-compute is an informational sub-step that did not block the assertion result.

## Repro (one-liner)

Re-run the watcher pointing at a fresh container where the delta source file does not yet exist. The exception happens at `json.loads(...)` on the empty/missing payload.

## Why not fix

1. The watcher is **deprecated** — superseded by the `aaats_share_equality_mismatch_total` Prometheus counter + Grafana alert with Telegram routing. It is kept only for historical reference; nobody should be running it.
2. The delta-compute output was advisory, not load-bearing — the share-assertion was the contract.

Filed for completeness so a future reader who finds the line in old logs can trace it here rather than re-investigate. Action: none.
