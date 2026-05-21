# Autonomy contract — AAATS rebuild sprint

**Authored:** 2026-05-21
**Status:** ACTIVE. Survives across Claude Code + Cowork sessions until operator revises.
**Trigger:** Operator chose "Full technical autonomy" in Cowork session 2026-05-21 evening, citing 15-day rebuild-loop fatigue: "I want my bot to be completely independent on its work. I don't want to be keep on checking each and every time."

## The principle

The decision fatigue is the bug. If every implementation choice (library, retry policy, schema field name, log format, test scaffolding) requires operator sign-off, the rebuild sprint will take 15+ days again. This contract draws the line: technical scope = Claude decides; product scope = operator decides.

## What Claude decides autonomously (no approval required)

**Implementation choices**
- Library / dependency picks (e.g., pydantic vs dataclasses for `state/schemas.py`).
- File structure and module organization within existing trees (`monitoring/`, `risk/`, `health/`, `trading/`).
- Function signatures, class names, internal APIs.
- Error handling: retry counts, backoff curves, timeout values.
- Log format, log levels, structured-logging field names.
- Test framework choice, test data structure, fixture organization.
- Docker image base, Dockerfile structure, compose service names (within the existing project layouts `deployment` and `aaats-base`).
- Schema field names + types for internal state files (writers/readers must agree — that agreement is Claude's job).

**Routine technical decisions**
- Whether a fix needs a unit test, integration test, or both.
- Which `docs/known_issues/` entries are now resolved vs still open after a fix.
- Refactors strictly internal to a module (no public surface change).
- Choice between near-equivalent algorithms (e.g., dict vs Counter, list comp vs filter+map).
- Bumping a Python/Docker dependency for security or compatibility.

**Reporting cadence**
- Claude decides what goes in the session report at the end of each Claude Code session: shipped, tested, known limitations, what's next.
- The daily digest format is **locked** by [`2026-05-21_track_d_reliability_addendum.md`](2026-05-21_track_d_reliability_addendum.md) Appendix A. Format changes require operator sign-off.

## What requires operator approval (Claude proposes, operator decides)

**Money, risk, market access**
- Live capital amounts — initial tranche size, escalation amounts, total exposure.
- Live broker selection (Binance, Bybit, Kraken, CoinDCX, etc.) — surfaced as a deferred decision in the parent plan.
- Adding a new symbol universe (e.g., turning on N1–N7 NSE).
- Changing any of the 5 doctrine injection gates (G1–G5).
- Changing kill triggers (-15% market, drawdown thresholds).
- Flipping `mode=paper` to `mode=live` for any container.

**Doctrine + governance**
- Any amendment to [`aaats_locked_doctrine_2026_05_14`](../../../AppData/Roaming/Claude/local-agent-mode-sessions/c79c8dda-373b-4212-84ad-30ce7dce12c1/898b291b-54cc-4133-bea1-a2dc257833fa/spaces/44c9f0dc-bfb2-42a0-b1df-fa4afe7217ce/memory/aaats_locked_doctrine_2026_05_14.md).
- `AUTO_APPROVAL_RULES.md` changes.
- Modifying any of the five Track C gate criteria (C.1–C.6).
- The two human gates at flip moment (Telegram receipt, typed `FLIP TO LIVE $25`).

**Scope changes**
- Adding new tracks beyond A/B/C/D.
- Adding new strategies to the universe (Claude can triage/halt/tune existing; not add).
- Changing the 30-day soak length in D.5.
- Decommissioning a service entirely (e.g., shutting down Grafana).

**Things that touch the operator's local machine outside this repo**
- Anything outside `C:\Users\udaym\OneDrive\Desktop\Puneeth\`.
- Installing software on the operator's workstation.
- Changing Tailscale / Contabo billing.

## Reporting cadence (the inverse of approval)

Claude reports — operator does not need to read until the report says "action needed":

- **End of each Claude Code session:** session report appended to the relevant decision doc's "Status log" section (the parent rebuild plan already has this pattern).
- **Daily, while D.5 soak runs:** the daily digest per Appendix A. If `Action needed: NONE`, operator does not need to read further.
- **Weekly Friday:** Cowork session reviews Track A + Track B + Track D status. Reads the Status logs, no fresh investigation needed unless something flagged.
- **On unblock-needed:** Claude pings operator with the specific decision needed, the recommended option, and "I'll proceed with the recommendation in 24h unless told otherwise." Default is forward motion.

## How conflicts resolve

If Claude is uncertain whether a decision is technical or product:

1. Read this contract. If the decision matches a listed item, follow it.
2. If not listed: classify by impact. **Affects money, risk, or doctrine → operator. Everything else → Claude proceeds and reports.**
3. If still unclear after 1+2: Claude proceeds with the option that is **most reversible**, ships it behind a feature flag if possible, and flags the decision in the session report for retroactive operator confirmation.

The bias is always toward forward motion. A reversible decision made wrong is recoverable. A 15-day stall is not.

## What this contract is NOT

- Not a license to bypass [`feedback_scp_deploy_clean_tree`](../../../AppData/Roaming/Claude/local-agent-mode-sessions/c79c8dda-373b-4212-84ad-30ce7dce12c1/898b291b-54cc-4133-bea1-a2dc257833fa/spaces/44c9f0dc-bfb2-42a0-b1df-fa4afe7217ce/memory/feedback_scp_deploy_clean_tree.md) — every SCP deploy still requires a clean tree.
- Not a license to skip [`feedback_github_push_every_session`](../../../AppData/Roaming/Claude/local-agent-mode-sessions/c79c8dda-373b-4212-84ad-30ce7dce12c1/898b291b-54cc-4133-bea1-a2dc257833fa/spaces/44c9f0dc-bfb2-42a0-b1df-fa4afe7217ce/memory/feedback_github_push_every_session.md) — every session still ends with rebase + push.
- Not a license to write the operator's name on a brokerage account or move money on their behalf.

## Revision

Operator can revoke or narrow this contract at any time by writing "autonomy contract revoked" or "narrow autonomy: <area>" in any Cowork chat. Claude will read this doc at the start of each session and treat the latest version as canonical.
