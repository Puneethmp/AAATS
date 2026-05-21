# Ledger Spec Q1–Q4 — Recommendations Pack

**Author:** Claude operator-assistant session, 2026-05-21
**Status:** awaiting user sign-off; each Q has a recommended answer + alternatives + commit-or-reject prompt at the end
**Source doc:** [docs/specs/unified_positions_ledger.md](../specs/unified_positions_ledger.md)
**Why this exists:** Q1–Q4 have been the operator-blocked item across multiple sessions. This pack converts them into decisions you can accept/reject in one read.

---

## Decision summary (TL;DR)

| Q | Question | Recommended answer | Rationale (one line) |
|---|----------|--------------------|---------------------|
| Q1 | DB location for `positions` table | **Same DB** (`paper_trades.db`) | Atomic txn across BUY row + positions row eliminates a class of half-write divergence — same root cause we're trying to kill. |
| Q2 | Cash ledger unification scope | **Follow-up, not blocking** — add a separate `cash_ledger` table to the same DB in a P2 sprint. | Cash divergence hasn't bitten us yet; positions ledger is the load-bearing fix for the TON/FET class of bug. |
| Q3 | Metadata schema | **Opaque `metadata_json` TEXT now, JSON1 virtual columns later if a query path emerges.** | Ship faster; SQLite's `json_extract()` lets you add typed indexes/columns without a migration. |
| Q4 | Migration / flag flip | **Drain-cycle gate via `USE_UNIFIED_LEDGER` flag + a "no open positions" precondition check.** | A flag flip while positions are open is the dual-write pathology we're trying to kill, in miniature. Precondition makes it impossible by construction. |

If you accept all four as-is, the implementation prompt at the bottom is ready to paste into Claude Code on the workstation.

---

## Q1 — DB location: same DB vs separate

**The question:** Should the new `positions` table live in `paper_trades.db` alongside trade rows, or in a separate `positions.db`?

### Option A (RECOMMENDED) — same DB, `paper_trades.db`

**For:**
- Atomic transaction across `paper_trades` BUY insert + `positions` row insert. The reconciler false-positive surface we keep tripping over is fundamentally about half-writes: trade row landed, state file didn't (or vice versa). A single SQLite transaction makes this class of bug **structurally impossible**, not merely well-tested-against.
- One backup target. One file to copy in the rollback baselines (`.rollback/<date>_<change>/paper_trades.db.pre`).
- One file to migrate when the schema evolves. No "did I run migrations on both DBs?" footgun.
- SQLite handles single-file multi-table workloads at the volume this system produces (orders of magnitude headroom) without performance concerns.

**Against:**
- Slightly more careful schema versioning needed — but the spec already proposes auto-migration which handles this.
- Coupling: a corrupt `paper_trades.db` takes both ledgers down. **Mitigation:** existing rollback baselines + the `state-crypto` Docker volume persistence already address this.

### Option B — separate `positions.db`

**For:**
- Clean separation of concerns: trades = audit log, positions = state.
- Could in theory be backed by a different store later (Postgres, Redis) without disturbing the trade log.

**Against:**
- **Loses atomicity** — the exact property the unified ledger exists to provide. SQLite cross-DB ATTACH is not as atomic as same-DB transactions, especially under WAL.
- Two files to back up, migrate, restore. More operator surface to fumble.
- "Could move it to Postgres later" is YAGNI — the bot runs on a single box at <$200/mo budget; the day Postgres is needed is the day this whole architecture changes.

### Recommended commit
**Q1 = same DB (`paper_trades.db`).** Add `positions` table via auto-migration in the existing `paper_trades.db` schema.

---

## Q2 — Cash ledger: bundle with positions ledger or follow-up?

**The question:** `paper_portfolio.json` is to cash what `*_state.json` is to positions — a derived view with no single source of truth. Should the unified-ledger work also collapse cash into the DB now, or defer?

### Option A (RECOMMENDED) — Follow-up sprint, P2 priority

**For:**
- Positions ledger is the load-bearing fix for the **bug class actually biting**: TON/FET residuals, C5b dual-leg asymmetry, exit-sizing class of bugs. Cash divergence hasn't surfaced as a concrete incident in the audit trail.
- Bundling cash into the same sprint inflates the change surface ~2x — more LoC, more migration paths, more rollback complexity, more time-to-ship. The longer the ledger spec sits unimplemented, the longer C5b stays halted and strategy #13 stays blocked.
- The reconciler's job after positions-ledger lands is "positions table vs DB-derived shares" — a separable concern from "cash in JSON vs DB-derived cash." Tackling them serially is cleaner than in parallel.

**Against:**
- The dual-cash-ledger pathology is mathematically guaranteed to bite eventually (same logic as positions). Deferring just shifts the date of the next-near-miss.
- Two migrations is more operator overhead than one.

### Option B — Bundle now

**For:**
- One migration, one rollback baseline, one cycle of integration tests.
- Cash is simpler in structure than positions (no strategy private metadata) — adding it costs less LoC than its share of the test surface.

**Against:**
- Scope creep on a spec that has been operator-blocked for a week. **Each day of delay = one more day of C5b halted, dust threshold at $0.25, strategy #13 deferred.**
- A bad cash-ledger migration could corrupt portfolio accounting in a way the positions ledger wouldn't — different failure mode, separate test budget.

### Recommended commit
**Q2 = Follow-up.** File `docs/specs/unified_cash_ledger.md` as a P2 stub in the same commit that lands the positions ledger. Ship positions first, cash next sprint.

---

## Q3 — Metadata schema: opaque blob vs typed

**The question:** Strategy-private fields (`entry_z`, `max_z`, `entry_pct_b`, `symbol_vol`, etc.) need to ride along with each position row. Store as opaque `metadata_json` TEXT, or define typed sub-schemas per strategy?

### Option A (RECOMMENDED) — Opaque `metadata_json` TEXT now, JSON1 virtual columns later

**For:**
- **Ships immediately.** No schema versioning per strategy; no migration when a strategy adds a new private field.
- Strategy code becomes `position.metadata["entry_z"]` — same ergonomics as today's `state["entry_z"]`. Near-zero refactor friction.
- SQLite's JSON1 extension (built-in since 3.38) lets you add a typed VIRTUAL column or a partial index over `json_extract(metadata_json, '$.entry_z')` LATER if a query path actually needs it. **Migration-free upgrade path.**
- Most metadata is never queried from outside the owning strategy — it exists to survive container restart. Opaque is sufficient by definition for that use case.

**Against:**
- Cross-strategy queries ("show me all positions with entry_z > 2.0") require `json_extract()` not column access. Slightly less ergonomic for ad-hoc SQL.
- Type errors (strategy writes `"2.0"` string vs `2.0` float) won't be caught at insert time.

### Option B — Typed sub-schemas per strategy

**For:**
- Type safety enforced at the schema layer.
- Faster queryability.
- Cleaner data contract per strategy.

**Against:**
- **Every new strategy = a schema migration.** Defeats half the point of the unified ledger (which is to make strategy onboarding boring).
- More surface for ALTER TABLE in production. The system already has an auto-migration story but adding more migration paths increases the failure surface.
- Most fields are write-only-then-read-by-owner. Type safety pays its weight in code that's queried widely; this code is read by one consumer (the strategy itself).

### Recommended commit
**Q3 = Opaque `metadata_json` TEXT.** Add a pydantic validator (or equivalent) at the API boundary in `foundation/positions.py` so types are at least checked at write time, even if not enforced by the column.

If a future query path emerges (e.g., reconciler wants to see `entry_z` distribution), add a JSON1 virtual column at that time. Migration-free.

---

## Q4 — Migration rollback / flag flip safety

**The question:** The `USE_UNIFIED_LEDGER` env flag toggles strategies between writing state files vs writing the DB. If the flag flips mid-cycle while positions are open, you can double-write to both files AND DB, or write to one source and read from the other. How do we make this safe?

### Option A (RECOMMENDED) — Drain-cycle gate + precondition check

**Mechanism:**
1. On runner start, read `USE_UNIFIED_LEDGER` env flag once. **Do not re-read mid-process.** Flag changes require container restart.
2. Before flipping the flag (in either direction), the operator must run `scripts/drain_positions.py` which:
   - Asserts no open positions in either source (file-based **and** DB-based).
   - If any open positions exist: prints a list, refuses to proceed, exits non-zero.
   - If clean: writes a `data/ledger_flag_history.json` audit entry and returns success.
3. The deploy script (`scripts/deploy_ledger_flag.py`) refuses to swap the flag unless `drain_positions.py` exited zero in the last 10 minutes.

**For:**
- Makes the dual-write pathology **structurally impossible**: the only window where the flag can flip is when there are no open positions to disagree on.
- Audit trail of every flip in `ledger_flag_history.json` — debuggable.
- Same atomic-deploy pattern already in use (`.tmp + mv -f`) — consistent with deploy_discipline.md.

**Against:**
- Requires waiting for all open positions to close before flipping. In practice this is a non-issue for a 5-strategy book; could be hours on a positions-heavy day.
- One more script in `scripts/`. Manageable.

### Option B — Always dual-write during transition window

**Mechanism:** For a 7-day window after the flag flip, write to **both** state files and DB. Reconciler compares the two sources and warns on divergence. After window expires, state files become read-only.

**For:**
- No drain wait.
- "Compare two sources" generates real signal about whether the migration is clean.

**Against:**
- **You just rebuilt the exact pathology you're trying to kill.** Two writers, no single source of truth, divergence inevitable. The reconciler will trip on every minor timing difference between the two writes.
- Dual-write code path adds complexity to every strategy.
- 7-day window means 7 more days of the bug class staying alive.

### Option C — Big-bang flip, accept risk

**Mechanism:** Flip the flag, restart, hope.

**For:** Simple.

**Against:** This is how the C5b $25/leg asymmetry shipped. Cargo-cult flip-and-hope is the failure mode the doctrine exists to prevent.

### Recommended commit
**Q4 = Drain-cycle gate + precondition check (Option A).** Ship `scripts/drain_positions.py` and `scripts/deploy_ledger_flag.py` as part of the same PR that adds the `positions` table.

---

## Implementation prompt (ready to paste into Claude Code on the workstation)

If you sign off on Q1–Q4 above, this is the prompt for Claude Code on `C:\Users\udaym\OneDrive\Desktop\Puneeth`:

```
Implement the unified positions ledger per docs/specs/unified_positions_ledger.md
with the Q1-Q4 decisions in docs/decisions/2026-05-21_ledger_spec_recommendations.md.

Scope this implementation in three commits, each atomic:

COMMIT 1 — schema + API + tests (no strategy changes yet)
- Add `positions` table to data/paper_trades.db schema (auto-migration path).
- Implement foundation/positions.py with open_position / close_position / get_position / list_positions.
- Pydantic validator at API boundary for metadata_json typing.
- Tests under tests/foundation/test_positions.py: open/close roundtrip, metadata opaque preservation, composite-key collision, list filters. All must pass under existing pytest harness.
- DO NOT touch any strategy file yet. DO NOT add USE_UNIFIED_LEDGER references yet.

COMMIT 2 — migration + flag-flip safety
- scripts/migrate_positions_to_db.py per spec section "Migration plan".
- scripts/drain_positions.py implementing the precondition check from Q4 Option A.
- scripts/deploy_ledger_flag.py refusing flip unless drain_positions.py exited 0 in last 10min.
- data/ledger_flag_history.json schema + initialization.
- Tests for the migration script using a fixture paper_trades.db with known state files.

COMMIT 3 — strategy wiring behind flag (no behavior change with flag OFF)
- trading/altcoin_reversion.py, trading/bollinger_range.py, trading/stat_arb.py, trading/momentum_breakout.py:
  read USE_UNIFIED_LEDGER once at module import; route _load_state / _save_state through positions API when ON, untouched fallback when OFF.
- Flag stays OFF in production after this commit lands. Flag flip is a separate operator action.
- Tests: each strategy's test suite runs with flag OFF (regression) and with flag ON (forward).

Rollback baseline before each commit: copy paper_trades.db and each touched file
to .rollback/2026-05-XX_ledger_commitN/ with MANIFEST.txt per deploy_discipline.md.

After commit 3 lands locally, push to origin/main, do NOT deploy to box. Box
deploy is a separate operator action with explicit go-ahead.

Hard constraints:
- USE_UNIFIED_LEDGER stays OFF in production through this entire change set. We
  do not flip the flag in the same change that introduces it.
- C5b funding_arb stays halted at source — do not modify trading/funding_arb.py.
- Tests must pass before each push.
- No edits to scripts/reconcile_intracycle.py in this PR — reconciler swap to
  Source-A=positions table is a follow-up commit after the strategy migration
  has soaked for at least 48h with flag OFF.
```

---

## What this unblocks once shipped

- **C5b funding_arb** can be re-enabled because dual-leg accounting will have a canonical positions row per leg (with metadata distinguishing the leg).
- **Dust threshold** can revert from $0.25 back to $0.10 because residuals from exit-sizing bugs are healed by the migration script's reconstruction from paper_trades.
- **Strategy #13** stops being blocked — new strategies use the positions API and don't add a new `*_state.json` shape for the reconciler to learn about.
- **Reconciler complexity** drops: no more union-over-N-files, just `SELECT FROM positions`.

## What still gates live capital after this lands

- Trade-count gate from `data/deployment_decision.json` (17/50 — see `docs/decisions/2026-05-22_live_readiness.md`).
- 48h soak of the new ledger with flag ON before strategy migration is treated as canonical.

---

## Sign-off

Paste back one of:

- **"Q1=A, Q2=A, Q3=A, Q4=A — ship the prompt"** (the recommended path)
- **"Q1=A, Q2=B, Q3=A, Q4=A"** (or any other combination — I'll regenerate the prompt for that mix)
- **"Reject — here's what I'd change: ..."** (and I'll iterate)
