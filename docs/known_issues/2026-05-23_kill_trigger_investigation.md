# 2026-05-23 — Kill-trigger investigation (paper-crypto, -33.4% drawdown)

**Status:** CLOSED. Verdict primarily **(d)** with secondary findings (a partial **(c)**). Two derivative fixes shipped in [0b]; design documented; digest wording corrected.
**Trigger:** Cowork review 2026-05-23 noted halt_state.json showed `crypto:false` while the digest reported -33.4% drawdown. The session-6 prompt asked whether the -15% market kill at [risk/engine.py:39](../../risk/engine.py#L39) is actually firing.

## TL;DR

The -15% market kill **is firing as designed** on every cycle. It is a **new-entry size gate**, not a liquidation kill. The doctrine wording in earlier docs and the digest's "near kill threshold" string both glossed this distinction. The persistent `data/halt_state.json` (per-market boolean, written only by `foundation/kill_switch.halt()`) is unrelated to the risk-engine's in-memory `_halted_markets` set; the two state stores were never meant to be synced. Two adjacent gaps were noted and are addressed below: (1) `run_crypto` has no top-of-cycle short-circuit equivalent to `run_india`'s `is_halted("crypto")` check, and (2) `C1_stat_arb` standalone bypasses the kill gate (already filed as B.1 deferred work).

## Four hypotheses, in order

### (a) `update_market("crypto", ...)` is never called from the runner → **REFUTED**

[trading/live_paper_runner.py:967-971](../../trading/live_paper_runner.py#L967-L971) defines `apply_kill_switch_gate` which calls `engine.update_market(market, market_equity)` on every order attempt. [trading/live_paper_runner.py:1003-1007](../../trading/live_paper_runner.py#L1003-L1007) calls it at the top of every `execute()`. The standalone strategies route through this too: `bollinger_range.py:256` (C6) and `altcoin_reversion.py:508` (C3) both import and call `apply_kill_switch_gate`. So `update_market` IS being called.

### (b) Runner ignores `HALT_MARKET` return → **REFUTED**

[trading/live_paper_runner.py:972-976](../../trading/live_paper_runner.py#L972-L976) sees the `HALT_MARKET` decision, logs `🛑 RISK HALT [crypto]`, sends a Telegram alert, and returns `(False, reason)`. `execute()` at [trading/live_paper_runner.py:1006-1007](../../trading/live_paper_runner.py#L1006-L1007) returns immediately when the gate denies. The HALT response is honored.

### (c) `_halted_markets` set ≠ `halt_state.json` (two state stores) → **PARTIAL**

These two files track different concepts:

| File | Writer | Schema | Meaning |
|---|---|---|---|
| `data/halt_state.json` | [foundation/kill_switch.py:51-89](../../foundation/kill_switch.py#L51-L89) `halt()` | `{us: bool, india: bool, crypto: bool}` | **Operator/CLI/external** halt — set via `kill.py` or drawdown_guardian explicit call |
| `RiskEngine._halted_markets` (set) | [risk/engine.py:262](../../risk/engine.py#L262) | in-memory `set[str]` | **Per-process** halt set by the engine when it observes a drawdown breach |
| `data/strategy_halt_state.json` | [risk/strategy_halt.py:73-95](../../risk/strategy_halt.py#L73-L95) | `{strategy_id: {halted, reason, halted_at, ...}}` | **Per-strategy** halt set by `strategy_isolation` on 3 consecutive cycle exceptions |

These three were designed as parallel, not synchronized, channels. The risk-engine kill loops `_halted_markets` in-memory per process; the persistent peak (`risk_engine_state.paper.json`) survives restarts so the next cycle re-derives the HALT_MARKET on first `update_market` call. The persistent peak is the source of truth, not the in-memory set. **Sync gap is by design** — but the documentation never made that clear, which is the bug.

The misleading observation in the session-4 review was: "halt_state.json shows `crypto:false`, therefore the kill is not firing." That conclusion was wrong because `halt_state.json` is the **operator/CLI** channel, and the engine never writes to it. The engine has its own (in-memory) halt set that re-derives every cycle.

### (d) Kill applies to new-entry SIZING only; existing positions bleed → **VERDICT (PRIMARY)**

Confirmed by reading both [risk/engine.py:267-270](../../risk/engine.py#L267-L270) (HALT_MARKET decision sets `allowed_fraction=0.0`) and the runner's response: the HALT short-circuits `execute()` before `check_new_order` is reached, so no new order is placed. But there is **no liquidation path** in `RiskEngine` — the kill only prevents new entries. Open positions continue to mark-to-market.

`allowed_fraction` is consumed at exactly one place in the runner: [trading/live_paper_runner.py:1037](../../trading/live_paper_runner.py#L1037) `shares *= gate.allowed_fraction` (only on `REDUCE` action; on `HALT_MARKET` the runner returns before reaching this line). So `allowed_fraction=0.0` from the engine's HALT_MARKET response is effectively dead code — but harmlessly so, because the runner's earlier early-return covers the same outcome.

**Practical behavior at -33.4% paper-crypto drawdown:**
- Every cycle: `apply_kill_switch_gate` → `update_market("crypto", $87.45)` → drawdown (87.45-131.32)/131.32 = -33.4% ≤ -15% → returns HALT_MARKET → `execute()` returns → **no new BUY placed**.
- C3 / C6 standalone strategies: same path via their own `apply_kill_switch_gate` import.
- C1_stat_arb standalone: **NOT GATED** ([trading/stat_arb.py:478](../../trading/stat_arb.py#L478) — apply_kill_switch_gate wire deferred per B.1 triage table).
- Existing open C3 positions: continue to bleed mark-to-market because nothing in the engine liquidates.

So the kill IS firing — just not the way the prompt's "near kill threshold" string implied. We're past the threshold; the threshold prevents new entries; the bleed is from existing positions.

## Secondary findings

1. **`run_crypto` has no `is_halted("crypto")` top-of-cycle check.** [trading/live_paper_runner.py:1473-1481](../../trading/live_paper_runner.py#L1473-L1481) (run_india) imports `is_halted` and short-circuits the entire cycle on a kill-switch flag. [trading/live_paper_runner.py:1574-1581](../../trading/live_paper_runner.py#L1574-L1581) (run_crypto) does not. Effect: an operator-set `halt_state.json` `crypto:true` would not stop the crypto cycle from running (it would just stop each individual order via `apply_kill_switch_gate` if the engine ALSO sees drawdown). This is asymmetric with India and a latent bug for the operator-kill path. **Fixed in [0b].**

2. **`C1_stat_arb` standalone bypasses the kill gate.** B.1 triage table noted this as deferred to "session 3 B.2". Today C1 is honestly skipping on `z<entry_z`, so the bypass is latent. But once C1 starts firing again, it would open positions while paper-crypto is in HALT. **NOT FIXED THIS SESSION** — left as queued; risk is bounded because C1 entry-z gate is gating it anyway. Filed as a separate item for the next session if B.2 finds C1 wants to fire.

3. **Digest wording.** Action-needed line says "drawdown -33.4% near kill threshold (-15%)" which suggests the kill hasn't fired yet. Better: "past market-kill threshold (-15%); new entries blocked, open positions continue to mark-to-market". **Fixed in [0b].**

## Remediation (shipped in [0b])

1. `trading/live_paper_runner.py:run_crypto` — short-circuit on `is_halted("crypto")` at top of cycle (parity with `run_india`). One-file patch.
2. `monitoring/daily_digest.py:compute_action_needed` — drawdown wording now distinguishes three bands: `> -10%` no trigger (existing), `-10% to -15%` "near", `-15% to -20%` "past market-kill (new entries blocked)", `≤ -20%` "past portfolio-kill (all new entries blocked)".
3. Tests: `tests/test_kill_trigger_paths.py` covers: (a) the engine's HALT_MARKET path is hit at -16% market drawdown, (b) the runner's run_crypto early-returns on `is_halted("crypto")`, (c) digest wording switches across the four bands.
4. Doctrine: `CLAUDE.md` annotated under a new "Kill switch semantics" subsection so future sessions don't re-litigate.

## What is NOT changed

- The engine still does NOT call `foundation/kill_switch.halt()` when it observes a market-DD breach. The two halt channels are intentionally separate: the engine kill is per-process (regenerates from persisted peak on every restart) and re-tests each cycle. Adding a `foundation.halt()` call would surface every -15% breach as an operator alert from the audit trail layer, which is desirable for live mode but noisy for paper mode where the bot is intentionally allowed to bleed below -15% until it recovers or is manually intervened. Revisit before live flip in Track A.3.
- The C1_stat_arb standalone kill-gate wire-up is still deferred to B.2.
- The engine does not liquidate open positions on HALT_MARKET. This is by design (per-trade stop at -2% handles per-position liquidation; market-level kill is for new entries). Changing this is a doctrine-level decision and requires operator sign-off.

## How this changes B.3 soak premise

The session-5 prompt's premise was: "B.3 soak is the drawdown-fix path because the kill is firing on new entries, so the only way the bot recovers is open-position mean-reversion or further losses bringing the portfolio to -20% all-halt." That premise is CORRECT given the verdict (d). B.3 still measures whether the strategies' mean-reversion thesis holds.

What is FALSE is the implicit assumption that "kill at -15% protects new entries." That's true for `execute()` and C3/C6 standalone, but **false for C1_stat_arb standalone**. If C1 starts firing again during the soak window, it will open positions while crypto is in HALT. B.2 measurement should account for this (or B.2 should wire the C1 gate first).
