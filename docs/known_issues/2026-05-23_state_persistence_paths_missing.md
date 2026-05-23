# Known issue: state persistence paths missing inside aaats-paper-crypto

**Discovered:** 2026-05-23 session 9 [0b] (read-only probe after session-8 deploy).
**Severity:** UNKNOWN — read-only probe only, no behavior-impact investigation.
**Will be resolved by:** Session 11 reset (per Track E.4 plan); state-crypto-paper
volume gets wiped + reinitialized as part of the $200-floor reset.

## Observation

Inside the container after the session-9 deploy (image
`sha256:1d3a7ffadd385c…`), the following paths are ALL absent:

| Path inside container | Status |
| --- | --- |
| `/app/data/risk_engine_state.paper.json` | absent |
| `/app/data/portfolio_state.paper.json` | absent |
| `/app/data/equity_curve.json` | absent |
| `/app/data/state/risk_engine_state.json` | absent |
| `/app/data/state/risk_engine_state.paper.json` | absent |
| `/app/data/state/portfolio_state.json` | absent |
| `/app/data/state/portfolio_state.paper.json` | absent |
| `/app/data/state/equity_curve.json` | absent |

`/app/data/state/` directory itself does not exist either.

The runner is nonetheless re-deriving portfolio state every cycle ("HALT ALL
MARKETS / Portfolio drawdown -33.4% breached -20%" continues to fire), so
the in-memory portfolio object is being reconstructed from the trades table
(`data/paper_trades.db`) on each cycle. Engine state is similarly being
re-derived rather than loaded.

## Why filed not fixed

Session 9's job is to ship the operator-halt MTM gap fix and run the B.1.5
backtest. The reset in session 11 (Track E.4) will:

1. Stop aaats-paper-crypto.
2. `docker volume rm deployment_state-crypto-paper`.
3. Recreate the volume with the $200-floor seed.
4. Start aaats-paper-crypto fresh.

Any persistence-path anomaly is wiped by that reset. Investigating now
would burn session-9 time that the backtest critical path needs, and the
fix would be discarded by session 11's volume rm anyway.

## Post-soak investigation hooks

If the reset proceeds and the new run STILL has empty/missing state files
after 24h of cycles, the question becomes: did the engine ever learn to
write to `/app/data/state/`, or is the write path silently failing? Likely
suspects:

- `state-crypto-paper` volume mount config in `deployment/docker-compose.yml`
  — does it bind to `/app/data/state/` or `/app/data/`?
- `risk/engine._persist_*` calls (or whatever the per-cycle save path is).
- Per session-7 doctrine note in CLAUDE.md: "data/state/risk_engine_state.json
  does exist per session-7 doctrine" — somewhere between session 7 and now,
  the file disappeared. Could be volume re-creation, could be write-path
  regression, could be that the path was renamed in code.

## What is NOT broken

- Trade history is intact (`data/paper_trades.db` still has rows; cycle
  reports cite -$0.04 realized / +$0.05 unrealized, equity $87.45).
- Drawdown calculation is still correct (-33.4% vs $131.32 peak).
- Halt logic is functional (HALT_ALL + HALT_CRYPTO both firing on every cycle).

The system is operating without persistent state files, just re-deriving
each cycle. That's slower but not broken — the gap matters only if a
crash mid-cycle would lose accumulated state, and right now there's no
accumulated state to lose anyway (zero open positions, all halts hold).
