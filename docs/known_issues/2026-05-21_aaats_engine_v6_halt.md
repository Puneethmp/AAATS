# Known Issue — aaats-engine (v6 stack) crypto market HALTED 2026-05-20

**Filed:** 2026-05-21
**Severity:** observational — does NOT affect aaats-paper-crypto live-readiness path
**Status:** open, no action absent operator direction

## Observation

`runtime/engine.log` (auto-committed by box cron, latest commit `8c8dceb` 2026-05-20T18:00Z) shows:

```
2026-05-20 17:58:51,414 [WARNING]   🛑 RISK HALT [crypto]: CRYPTO drawdown -15.5% breached -15% halt threshold
2026-05-20 17:58:51,611 [INFO] == Crypto cycle done | capital=USD 93.26 ==
2026-05-20 17:58:51,613 [INFO] Cycle #980 done | open=13 (stat_arb=1) | realized_pnl~-93.88 | sleeping 900s
```

The crypto market-specific drawdown breached -15% in `aaats-engine`. Per-market kill switch fired. Container continues to run (`Up 10 days (healthy)` per `runtime/STATUS.md`) but no new BUYs route through.

Concurrent state in `runtime/paper_trades.db` confirms:
- 280 total trade rows (146 BUY / 134 SELL)
- 234 crypto + 46 india
- Realized PnL sum: **-\$93.88** (matches engine.log line)
- Date range: 2026-05-06 → 2026-05-20T17:58Z

## Why this is filed but not actioned

`aaats-engine` is the v6 stack — a parallel research/replay system. The memory file `aaats_next_session_start_here.md` and CLAUDE.md both note: *"`aaats-engine` (v6 stack) runs in parallel on the box — do NOT stop it."* It is **not** the container under live-capital review.

The container under live-capital review is `aaats-paper-crypto` (image `sha256:d5f30630754a…` per 2026-05-20 audit), which:

- Has its own DB at `/app/data/paper_trades.db` on the box (NOT mirrored to workstation)
- Soaked clean post-G1 flip (5 cycles, 0 HALT, 0 exceptions)
- Has share_equality_mismatches empty as of 2026-05-20T17:54Z

The 2026-05-21 audit briefly confused the v6 engine HALT for paper-crypto's state — flagging that here so future sessions don't make the same misread.

## Hazard for future audits

Anyone reading `runtime/STATUS.md` or `runtime/engine.log` or `runtime/paper_trades.db` is looking at the **v6 engine**, not paper-crypto. The naming overlap is unfortunate. The two sources of truth:

| What | Path | Subject |
|------|------|---------|
| `runtime/engine.log` (auto-commit) | workstation, via cron | aaats-engine (v6) |
| `runtime/paper_trades.db` (auto-commit) | workstation, via cron | aaats-engine (v6) |
| Container `aaats-paper-crypto` logs | only on box (`docker logs aaats-paper-crypto`) | the live-readiness path |
| `/app/data/paper_trades.db` inside `aaats-paper-crypto` | only on box | the live-readiness path |
| `data/` on workstation | source-of-truth for SCP deploys to box | feeds INTO paper-crypto's bind mounts |

When asked about paper-crypto state, SSH to the box and `docker exec aaats-paper-crypto` — don't read `runtime/` files.

## Questions worth asking the operator (when time permits)

These are not blocking, but informing:

1. **Is the v6 engine still load-bearing for any research output?** If it's stale-parallel and just bleeding $93 of paper PnL, consider whether it's worth keeping the container running.
2. **Is the v6 engine's -15.5% HALT a known-acceptable failure mode?** It's been HALTED since 2026-05-20T17:58Z (3+ days as of 2026-05-21). No revival attempts visible in logs. If this is fine, fine — but the silence is itself a signal.
3. **Should `runtime/STATUS.md` distinguish the two systems' health?** Currently it lists `aaats-paper-crypto: Up 51 minutes (healthy)` and `aaats-engine: Up 10 days (healthy)` side-by-side without context that the v6 engine is HALTED on per-market kill switch — "healthy" by Docker means "container running," not "trading strategy running."

## What this is NOT

- Not a blocker for 2026-05-22 live flip on `aaats-paper-crypto`
- Not a request for action from Claude — Claude does not touch v6 absent explicit operator direction
- Not an incident — this is a parallel system, not the production trading path

## Cross-references

- Live-readiness decision: `docs/decisions/2026-05-22_live_readiness.md` (architecture section explicitly disambiguates the two containers)
- Doctrine: memory `aaats_locked_doctrine_2026_05_14.md`
- Audit that surfaced this: 2026-05-21 operator-assistant session
