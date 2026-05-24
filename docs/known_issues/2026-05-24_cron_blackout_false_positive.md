# 2026-05-24 — Suspected 15h auto-cron blackout was a stale-fetch illusion

**Status:** FALSE POSITIVE. Root cause: workstation `git log origin/main`
was reading a local cache last updated 2026-05-23T18:15Z. The box pushed
auto-cron commits every 15 min throughout the suspected blackout window.
**Caught by:** Operator inspection while writing the resilience sprint prompt.
**Triggered:** Track D 4-layer resilience build ([`docs/decisions/2026-05-24_auto_cron_resilience.md`](../decisions/2026-05-24_auto_cron_resilience.md)).

## Timeline (UTC)

- **2026-05-23T18:15Z** — Last `git fetch origin` on operator workstation.
  Origin/main at commit `001afc7` "auto: 2026-05-23T18:15:05Z trades + logs"
  (that fetch landed normally).
- **2026-05-23T18:15Z → 2026-05-24T09:30Z** — Box auto-cron continues
  pushing every 15 minutes. Last push at 09:30:10Z to commit `194224a`.
  Workstation does NOT auto-fetch and operator does NOT manually fetch
  during this window.
- **2026-05-24T~05:30Z** — Operator writes Track D resilience prompt,
  citing `git log origin/main` showing `001afc7@18:15Z` as the last
  commit → concludes the box has been silent for 11h.
- **2026-05-24T09:41Z** — Claude Code session opens. SSH to box succeeds,
  `docker ps` shows all containers healthy, `/home/aaats/aaats-autopush.log`
  shows uninterrupted pushes through 09:30:10Z.
- **2026-05-24T~09:44Z** — Workstation `git fetch origin main` returns:
  `001afc7..194224a main -> origin/main`. The "blackout" never happened.

Actual blackout duration: **0 minutes**. Apparent blackout duration:
**15h15m**, purely from stale local refs.

## Why it was easy to mistake

`git log origin/main` queries the local reflog. Without an explicit
`git fetch`, that reflog is whatever was last fetched. There is no
visual indication that the answer is stale — the command outputs exactly
the same way for "fresh" and "15h-old cache". The mental model of
"origin/main = the canonical state on GitHub" is wrong in the local
git ref namespace; canonical is `git fetch && git log origin/main`.

## What's been done

1. The 4-layer resilience build proceeded anyway, because the gaps the
   prompt targeted are real (no external monitor, no heartbeat, no retry,
   no cron-daemon-watchdog). The false positive was the catalyst, not
   the bug.
2. L1 (GitHub Actions liveness monitor) directly closes the blind spot
   that misled the diagnosis: it operates on the canonical origin/main
   state (not a cache) and fires within 30 min of a real outage.
3. L4 (`aaats-diagnose.sh`) returns ground truth from the box in <1s,
   so future triage doesn't depend on workstation-side git state at all.

## What's NOT been done

Nothing — there's no upstream bug to fix. The lesson is operator/Claude
hygiene: when investigating a suspected outage, the first command must
be `git fetch`, not `git log`. The next_session_prompt's Phase 0 now
encodes this as a hard rule.

## How each new layer would have caught a real version of this

If the box really had been silent for 15h:

- **L1 GitHub Actions** would have fired at the 30-minute mark and every
  20 min afterward (Telegram chat 1946109268), removing all ambiguity
  about whether origin/main was receiving pushes.
- **L2 in-cron** is irrelevant — if cron isn't running at all, L2 can't
  fire (it lives inside the cron). The retry+heartbeat helps when cron
  runs but push fails partially; this would not have been the failure
  mode.
- **L3 heartbeat checker** would have detected the heartbeat file going
  stale (>20 min old) and fired within 5 min of crossing the threshold.
  Same caveat as L2: if cron is dead entirely, L3's own cron schedule
  is also dead; L1 is the safety net.
- **L4 diagnose.sh** — would not have alerted, but `ssh aaats@... 'bash
  /home/aaats/bin/aaats-diagnose.sh --quick'` would have returned ground
  truth in under a second.

## Related

- `docs/decisions/2026-05-24_auto_cron_resilience.md` — full design rationale.
- `docs/runbooks/auto_cron_recovery.md` — symptom → fix guide.
- `.rollback/2026-05-24_auto_cron_resilience/MANIFEST.txt` — rollback baselines.
