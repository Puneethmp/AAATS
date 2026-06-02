# DB-FREEZE false-positive alerts — SQLite WAL not folded before snapshot

**Date:** 2026-06-02
**Status:** FIXED (autopush patched + deployed)
**Severity:** noise (alert-fatigue) + data-staleness — bot itself never affected

## Symptom

`aaats-autopush.sh` fired the `DB-FREEZE: paper_trades.db unchanged N ticks`
Telegram alert repeatedly. Log scan on 2026-06-02 showed **695 in-log
detections → 152 Telegram alerts sent** between 2026-05-26 and 2026-06-02.
The bot was healthy throughout (cycle 611, trade count climbing 279→280, fresh
C6 PAPER BUY TON/USDT at 16:31:55Z) — so every one of those alerts was a false
positive.

## Root cause

The paper trader opens `paper_trades.db` in **SQLite WAL mode**. New trades are
written to `paper_trades.db-wal`; the main `.db` file's bytes (and therefore
its `sha256`) do **not** change until a checkpoint folds the WAL back in. The
WAL had grown to ~4.1 MB (last main-file write 14:01, WAL writes at 16:31) —
i.e. auto-checkpoint was being held off, most likely by a long-lived reader
connection (e.g. `aaats-metrics`) blocking the passive checkpoint.

The autopush DB-freshness check (added in the 2026-05-26 structural fix)
`docker cp`s **only the main `.db` file** then hashes it. Because the main file
was frozen, the hash looked unchanged for 10+ ticks and tripped the freeze
detector. Two consequences:

1. **Alert noise** — 152 spurious Telegram alerts.
2. **Stale origin snapshot** — `runtime/paper_trades.db` on origin/main was
   missing the last ~2.5h of trades each time. Anything reading the DB from
   origin (notably the **L7 activity-floor monitor** on GitHub) worked off
   stale data — and could in principle mask a *genuine* stall.

## Fix

`scripts/box/aaats-autopush-v3.sh` (deployed to `/home/aaats/bin/aaats-autopush.sh`):
force a `PRAGMA wal_checkpoint(TRUNCATE)` inside the container **before** the
`docker cp` of `paper_trades.db`. This makes the cp'd file current and the
freshness hash meaningful. Idempotent — if a reader holds the write lock the
checkpoint is a no-op and retries next tick (15 min cadence keeps WAL bounded
regardless).

```bash
timeout 10 docker exec aaats-paper-crypto python3 -c \
  "import sqlite3; sqlite3.connect('/app/data/paper_trades.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')" || true
```

## Verification (2026-06-02)

- One-shot manual checkpoint: WAL 4.1 MB → 0 bytes, main `.db` refreshed.
- Reset `/home/aaats/aaats-db-freshness.state` (was `streak=10`).
- Manual run of patched script: `exit=0`, **no `DB FREEZE detected` line**,
  freshness state now `hash=6ce452a4… streak=0` (hash tracks real writes).
- Box backup of prior script: `/home/aaats/bin/aaats-autopush.sh.bak.20260602`.

## Not an issue (checked same session)

- **`L10/DISK: /home at 92%`** fired once historically; disk is currently 32%
  (`/dev/sda1` 23G/72G, 50G free), `.git` 50M with 0 bytes garbage. One-time
  spike (likely docker build layers during 2026-05-26 rebuilds), since cleared.
- **`L10/COMMIT_RATE=0`** and the 2026-05-24 watchdog/TZ-bug stale-heartbeat
  alerts were one-time events tied to a past cron outage; already fixed.
- Old `cp FAILED` lines for soft state files predate the 2026-05-26
  existence-guard and no longer recur.
