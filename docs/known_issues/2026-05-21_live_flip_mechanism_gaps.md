# Live-flip mechanism gaps discovered 2026-05-21

## Summary

On the eve of the 2026-05-22 GO $25 first tranche, mid-pre-flight investigation
revealed that the live-flip mechanism described in scripts/deploy_live_flip.py
and docs/runbooks/2026-05-22_live_capital_go.md does not actually flip the
trading container to live mode. The system is currently paper-only by deliberate
design. A real live mechanism is a separate engineering sprint.

## Gap 1 — Risk engine state inherits across mode boundary

- File: risk/engine.py:44-46 — STATE_FILE has no paper/live discriminator
- File: risk/engine.py:97-117 — __post_init__ loads peak unconditionally
- Volume: deployment/docker-compose.yml — state-crypto survives container recreation
- Observed: peak=$116.53, last_equity=$101.31, drawdown=-13.06% as of 2026-05-21T09:24:35Z
- Risk: live tranche would resume from paper book's drawdown; first 2% loss trips -15% market kill on cycle 1

## Gap 2 — PAPER_MODE env variable is unused

- grep PAPER_MODE trading/paper_loop.py returns no matches
- scripts/deploy_live_flip.py writes PAPER_MODE=False but no consumer reads it
- The .env flip is theatre — nothing in the trade loop branches on it

## Gap 3 — SYSTEM__TRADING_MODE is compose-hardcoded and validate-gated

- deployment/docker-compose.yml lines 12, 45, 78 — environment: block pins mode=paper, overrides .env
- deployment/scripts/validate_env.py:77-82 — startup gate explicitly errors if mode != paper
- AUTO_APPROVAL_RULES.md:139 forbids auto-modifying SYSTEM__TRADING_MODE

## Gap 4 — No live trade loop exists

- Container CMD is hardcoded `python trading/paper_loop.py --market crypto`
- No trading/live_loop.py file exists
- No live-broker adapter is wired into the trade-loop entrypoint

## Implications

A real live-flip requires, minimally:

1. Risk-state isolation per mode (separate file, or explicit reset on mode-change)
2. A live trade loop with the same cycle structure as paper_loop.py but live-broker calls
3. Compose changes (or a sibling compose file) that runs the live loop with mode=live
4. validate_env.py carveout for mode=live
5. deploy_live_flip.py rewritten to swap compose/command, not just .env
6. Removal of the AUTO_APPROVAL_RULES.md guardrail (deliberate, audited)

## Out-of-scope for this writeup

- Whether paper book's state-crypto volume should be reset to recover from -13.1% — separate operator decision
- Whether the rebuild sprint targets $25 or larger first tranche — operator framing decision
- Whether engine v6 stack (separate HALT) is in scope of the same sprint — likely no, document separately

## Sequencing for the rebuild sprint

Phase 1: state isolation + a no-op live loop that just heartbeats (testable in shadow)
Phase 2: live-broker adapter + validate_env carveout
Phase 3: deploy_live_flip rewrite + compose surgery
Phase 4: pre-flights against the new path + first-tranche flip

Estimate: 1-2 working sessions per phase, sequential.
