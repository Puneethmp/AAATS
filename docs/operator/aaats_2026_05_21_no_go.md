---
name: aaats-2026-05-21-no-go
description: AAATS 2026-05-22 first-tranche $25 live flip NO-GO. Live-flip mechanism is non-functional by design — system is paper-only. Rebuild sprint is the prerequisite to any live capital deployment.
type: project
snapshot_from_cowork_memory: 2026-05-21
---

NO-GO declared 2026-05-21 evening on the 2026-05-22 first-tranche $25 live flip. Cause: mid-pre-flight investigation revealed the live-flip mechanism (`scripts/deploy_live_flip.py` + the `PAPER_MODE` env toggle path described in the original runbook) is theatre — nothing in the trade loop consumes `PAPER_MODE`, and the actual mode-switch path doesn't exist end-to-end. The system is paper-only by deliberate design as of this commit.

**Why:** Four independent gaps surfaced as a single architectural finding (full evidence in `docs/known_issues/2026-05-21_live_flip_mechanism_gaps.md`):
1. **Risk-state inheritance** — `risk/engine.py:44-46` keys `STATE_FILE` with no paper/live discriminator; named volume `state-crypto` survives container recreation; current peak=$116.53, drawdown -13.06% (peak-to-equity including unrealized), only 1.9pp from the -15% market kill.
2. **`PAPER_MODE` env is unused** — grep returns no consumer in `trading/paper_loop.py`. The `.env` toggle is dead code.
3. **`SYSTEM__TRADING_MODE` is compose-hardcoded** — pinned to `paper` at three places in `deployment/docker-compose.yml` (lines 12, 45, 78); `deployment/scripts/validate_env.py:77-82` is a startup gate that explicitly errors if mode != paper; `AUTO_APPROVAL_RULES.md:139` forbids auto-modifying it.
4. **No live trade loop** — container CMD is hardcoded `python trading/paper_loop.py --market crypto`; no `trading/live_loop.py` exists; no live-broker adapter is wired in.

**Reframing as of 2026-05-21 evening (post-diagnostic):** Realized 9d paper P&L is -$5.76 (not the -13.1% drawdown figure earlier in this memo — that was peak-to-equity including unrealized). Loss is concentrated: C3_altcoin_reversion = -$5.63 (98%), C6_bollinger_range = -$0.13. C3 loss is itself 78% concentrated in 5 names (OP, ARB, PUMP, FET, LUNC of 32). The bot isn't structurally unprofitable — it has one strategy leaking in five symbols.

**How to apply:**
- Any future "live flip" prompt or doc referencing `PAPER_MODE=False` or `deploy_live_flip.py` as-shipped is referencing vapor — treat as obsolete until the rebuild lands.
- The shipped `scripts/live_flip_*.py` files from `2f7aaba` are retained for reference but will be rewritten in the rebuild sprint.
- Workstreams A (docs), B1/B2/B3 (unified ledger schema/migration/strategy wiring behind `USE_UNIFIED_LEDGER=False`), C (live-flip scripts) all SHIPPED on 2026-05-21 and remain valid foundation work — do not revert.
- Plan doc: `docs/decisions/2026-05-22_live_flip_rebuild_plan.md` (commit 4ab3085) — Track A (live infra), Track B (strategy profitability), Track C (the gate requiring both).

**Sign-offs still locked** (do not re-litigate):
- $25 first tranche size when the rebuild lands
- Ledger Q1-Q4 = A/A/A/A
- Two human gates at flip: Telegram receipt at PF3, typed `FLIP TO LIVE $25` at deploy
- See `docs/operator/aaats_locked_doctrine_2026_05_14.md` for $50/mo split + $100 live floor doctrine

**Display-only PF1 blockers** found during this investigation (deferred, folded into Track A.3):
- `risk/operational_validator.py:325-326` — unclamped score (790% display)
- `monitoring/metrics_aggregator.py:127-136` — dollar/percent mix produces -781% display drawdown
- `monitoring/heartbeat_monitor.py` vs `execution/live_paper_runner.py` — heartbeat schema mismatch (flat write, nested read)

All three have zero downstream consumers (verified by grep across `trading/`, `execution/`, `risk/` on 2026-05-21).
