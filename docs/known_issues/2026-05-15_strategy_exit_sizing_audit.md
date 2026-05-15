# Strategy Exit-Sizing Audit — Blast-Radius Scan

**Filed:** 2026-05-15
**Scope:** scoping-pass only; no patches applied.
**Trigger:** TON/FET reconcile divergence (2026-05-15) traced to C3 exit-sizing bug — SELL shares computed as `size_usd / exit_price` instead of selling exact entry shares. Audit determines whether other live strategies carry the same pattern before the unified positions ledger lands.
**Related:** [unified_positions_ledger.md](../specs/unified_positions_ledger.md), [project_aaats_drift_diagnosis](../../../../.claude/projects/c--Users-udaym-OneDrive-Desktop-Puneeth/memory/project_aaats_drift_diagnosis.md) (operator-local memory).

## 1. Code grep — per-strategy classification

The bug pattern: a SELL/close path computes `shares` from `size_usd / <some price>` rather than the actual entry quantity. The cleanest tell is a shared `_record` helper used for both BUY and SELL that always recomputes shares from the *current* price.

| Strategy | File | SELL call site | Pattern | Verdict |
|---|---|---|---|---|
| C1 stat_arb | [trading/stat_arb.py:193](trading/stat_arb.py#L193) | `record_trade(... shares=shares ...)` where `shares = position["shares_a"/"shares_b"]` (stored at entry) | uses stored entry quantity | **CLEAN** |
| C2 momentum_breakout | [trading/momentum_breakout.py:276](trading/momentum_breakout.py#L276) | `action="SELL", shares=size / entry` where `entry` = `pos["entry_price"]` and `size` = `pos["size_usd"]` | divides by **entry_price**, so equals original BUY shares | **CLEAN** |
| C3 altcoin_reversion | [trading/altcoin_reversion.py:367](trading/altcoin_reversion.py#L367) (via `_record` from line 466) | `shares=round(size_usd / max(price, 1e-9), 8)` where `price=current_price` at SELL | divides by **exit_price** → bug | **BUGGY (confirmed)** |
| C5b funding_arb | [trading/funding_arb.py:195](trading/funding_arb.py#L195) | `shares=size_usd / 1.0, price=1.0` (delta-neutral synthetic row) | not real position; reconciler explicitly excludes `C5b_funding_arb` | **N/A** |
| C6 bollinger_range | [trading/bollinger_range.py:184](trading/bollinger_range.py#L184) (via `_record` from line 284) | `shares=round(size_usd / max(price, 1e-9), 8)` where `price=price` (current) at SELL | divides by **exit_price** → bug | **BUGGY (latent — not yet observed in DB)** |
| live_paper_runner SELL | [trading/live_paper_runner.py:946](trading/live_paper_runner.py#L946), [:1286](trading/live_paper_runner.py#L1286) | `action="SELL", shares=sh, price=fill` where `sh = pos["shares"]` | uses stored entry shares | **CLEAN** |
| paper_loop | [trading/paper_loop.py:208](trading/paper_loop.py#L208) | `action="SELL", shares=pos.shares` | uses stored entry shares | **CLEAN** |

Two strategies share the same broken `_record` helper signature (`shares = size_usd / current_price`): C3 and C6. The fix is the same in both — sell exactly the original entry shares. The unified ledger spec does this by construction; until then, both `_record` helpers need an `entry_shares` argument and to drop the divide-by-price arithmetic.

## 2. DB drift evidence — per-symbol residual table

Per-symbol residual = `|state-file expected − DB SUM(BUY shares) − SUM(SELL shares)|`, with residual notional = residual × last_price. Run inside `aaats-paper-crypto` against `data/paper_trades.db` and `data/*_state.json`.

| Market | Symbol | Expected (state) | DB net | Residual (sh) | Last px | Residual $ | Source | Reconciler treatment (post-hotfix) |
|---|---|---|---|---|---|---|---|---|
| crypto | LUNC/USDT | 0 | -6838.62 | 6838.62 | 0.000079 | **$0.5370** | (db-only, no state) | skipped by deny-list (precedes dust filter) |
| crypto | PENGU/USDT | 0 | -20.46 | 20.46 | 0.009641 | **$0.1973** | (db-only) | skipped by deny-list |
| crypto | TON/USDT | 1.51314025 | 1.44080613 | 0.0723 | 2.078 | **$0.1503** | altcoin_reversion (C3) | silenced by $0.25 dust filter (was HALT × 4/cycle) |
| crypto | FET/USDT | 45.41966427 | 44.83257649 | 0.5871 | 0.2085 | **$0.1224** | altcoin_reversion (C3) | silenced by $0.25 dust filter (was WARN × 4/cycle) |
| crypto | ETH/USDT | 0 | -2.479e-5 | 2.479e-5 | 2284.60 | $0.0566 | (db-only) | silenced (was already silenced at $0.10) |
| crypto | TAO/USDT | 0.00991710 | 0.00980353 | 1.14e-4 | 305.50 | $0.0347 | altcoin_reversion | silenced |
| crypto | EUR/USDT | 0 | -0.01461117 | 0.01461 | 1.1752 | $0.0172 | (db-only) | silenced |
| crypto | SOL/USDT | 0 | -9.216e-5 | 9.22e-5 | 92.23 | $0.0085 | (db-only) | silenced |
| crypto | ARB, BCH, CHIP, ENA, ICP, ONDO, OP, PUMP, TRX | matched | matched | <1e-8 | various | $0.00 | altcoin_reversion / bollinger | not flagged |

The TON/FET residual signature is exactly what the C3 exit-sizing bug predicts: SELL shares = `size_usd / exit_price`, and because the exit was a losing trade, `exit_price < entry_price` → SELL shares > BUY shares → DB ends up with a permanent phantom-short residual that ratchets each round-trip. The static, identical-to-8-decimals nature of the drift across 24h cycles rules out feed noise.

C6 (bollinger_range, TRX) has **zero** residual today because its only open symbol (TRX) has not completed a losing round-trip yet. The bug is dormant but present in code.

## 3. Bump silencing list — symbols newly hidden by $0.10 → $0.25

Symbols whose residual notional falls in the new silencing band `[$0.10, $0.25)`:

| Symbol | Residual $ | Source strategy | Why silenced is acceptable |
|---|---|---|---|
| TON/USDT | $0.1503 | C3 altcoin_reversion | Documented bug; tracked in this audit; revert threshold once unified ledger lands. Intended target of bump. |
| FET/USDT | $0.1224 | C3 altcoin_reversion | Same as TON. |
| PENGU/USDT | $0.1973 | (db-only, deny-listed) | Already silenced by deny-list precedence; bump has no incremental effect. |

Three symbols total. Active (non-deny-listed) silenced: **2** (TON, FET). Within the operator-set 2–3 ceiling. **No unknown strategy bugs are being hidden** by the bump — the only active silenced symbols are the two whose root cause is already understood.

LUNC/USDT residual ($0.5370) exceeds the bump but is deny-listed and never reaches the dust filter — flagged here for completeness, not as a bump consequence.

## Recommendation (not a patch — operator decision)

- Keep the $0.25 bump in place as a band-aid for C3 residuals.
- Do **not** raise the threshold further. If a third active symbol crosses $0.10, treat it as a new bug to investigate, not a tuning knob.
- Patch C3 and C6 `_record` helpers to take `entry_shares` once the unified ledger spec is approved — the migration script restocks `entry_shares` from BUY-row history, retroactively zeroing TON/FET drift, and the threshold can revert to $0.10.
- Block any new strategy PR that uses the `shares = size_usd / price` SELL pattern.
