---
name: AAATS Architectural Debt — Dual Equity Ledger
description: Equity lives in two places (live_paper_runner positions dict + standalone *_state.json files). Surfaced 2026-05-15 P0/P1 deploy. Must be unified before strategy #13 lands.
type: project
originSessionId: 5eb1cfc5-6cfe-4784-b3fc-d5c6726012ce
snapshot_from_cowork_memory: 2026-05-21
status_2026_05_21: Unified ledger schema/migration/strategy wiring shipped 2026-05-21 (commits 4ee97f3, 61c93e7, 464bf7e) behind USE_UNIFIED_LEDGER=False flag. Dual-ledger drift remains observable in production (paper_positions.json={} while paper_trades.db has 4 open BUYs as of 2026-05-21 diagnostic).
---
The `live_paper_runner` `positions` dict and the standalone strategy state files (`altcoin_reversion_state.json`, etc.) are two independent equity ledgers. The runner doesn't own the state files; each strategy writes its own schema.

**Why this is debt, not a feature:**
- P0.2 near-miss on 2026-05-15: a cash-only `_compute_current_equity` would have reported -62% drawdown and HALT_ALL'd the system immediately because positions dict was empty while ~$64 of book value sat in standalone state files.
- The patch (sum `size_usd` across `data/*_state.json`) works only as long as future strategies use the same key name. A strategy that writes `position_size_usdt` or `notional` is silently invisible to the equity calc → false HALT.
- Same root cause family as the reconciler divergence between broker book and our position state.

**Why:** Two writers, no single source of truth → eventual drift is mathematically guaranteed.

**How to apply:**
- Before merging strategy #13 (or any new strategy that holds positions), promote `positions` to a single owned ledger with explicit schema.
- Strategy state files must write into that ledger via API, not into private JSON books.
- Reconciler's job becomes "broker book vs single ledger" instead of "broker book vs N private ledgers".
- If a PR adds another `*_state.json` with size/notional/position fields, push back — that's the exact pattern we need to stop.

**Concrete instance discovered (2026-05-15):** C3 strategy computes SELL quantity as `size_usd / exit_price`. When price moves between BUY and SELL, the SELL shares ≠ BUY shares, leaving permanent phantom residuals in paper_trades (TON: -0.07233412 sh, FET: -0.58708778 sh). The strategy state file forgets about the prior cycle's residual; the DB doesn't. Unified ledger spec at `docs/specs/unified_positions_ledger.md` makes `entry_shares` (real fill quantity, not derived from price) the canonical field.

**Strategy audit (2026-05-15) results:** the same `_record(... shares = size_usd / current_price ...)` pattern lives in TWO strategy files:
- C3 `trading/altcoin_reversion.py:367` — ACTIVE bug, root cause of observed TON/FET residuals.
- C6 `trading/bollinger_range.py:184` — LATENT. TRX hasn't lost a round-trip yet; will manifest on first losing exit.

**2026-05-21 status:** Unified ledger schema/migration/strategy-wiring shipped in commits 4ee97f3 / 61c93e7 / 464bf7e behind `USE_UNIFIED_LEDGER=False` flag. Production is still on the dual-ledger path. The 2026-05-21 diagnostic confirmed dual-ledger drift is live (paper_positions.json={} while paper_trades.db has 4 open BUYs). Flipping `USE_UNIFIED_LEDGER=True` is a deferred decision in `docs/decisions/2026-05-22_live_flip_rebuild_plan.md`.
