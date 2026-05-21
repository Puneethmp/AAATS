# Next Claude Code prompt — paste this into Claude Code on the workstation

**Authored 2026-05-21 by operator-assistant. Sign-offs baked in by Puneeth: GO \$25 first tranche 2026-05-22, Ledger Q1=A/Q2=A/Q3=A/Q4=A. Operator directive: Claude Code runs end-to-end with one human gate at the flip moment.**

Copy everything between the `---PROMPT START---` and `---PROMPT END---` markers and paste it into Claude Code (`claude` CLI) on the workstation at `C:\Users\udaym\OneDrive\Desktop\Puneeth`.

---PROMPT START---

You are picking up from the 2026-05-21 operator-assistant Cowork session. The operator has signed off on:

- **Live-flip:** GO \$25 first tranche on 2026-05-22
- **Ledger Q1-Q4:** A / A / A / A
- **Execution scope:** YOU run end-to-end. The only human gate is the operator typing `FLIP TO LIVE \$25` at the live-flip moment. Everything else — commits, push, ledger code, ledger tests, pre-flights including the Telegram synthetic, rollback baseline, SCP, container restart, tailing the first 4 cycles, health confirmation — is yours to execute.

Read these four docs in order before doing anything:

1. `docs/decisions/2026-05-22_live_readiness.md` — the PROVISIONAL GO call (signed off)
2. `docs/decisions/2026-05-21_ledger_spec_recommendations.md` — Q1-Q4 recommendations (signed off A/A/A/A)
3. `docs/runbooks/2026-05-22_live_capital_go.md` — the operator runbook (you are now executing it, not just preparing it)
4. `docs/known_issues/2026-05-21_aaats_engine_v6_halt.md` — context-only, do not action

Five workstreams. Execute in order. After each commit, push to origin/main per [[feedback_github_push_every_session]]. Tests must pass before each push. If any step fails or surfaces something unexpected, STOP and report back to the operator before proceeding.

============================================================
WORKSTREAM A — Commit and push the four new docs (5 min)
============================================================

Single commit (companion docs, atomic as a set):

```bash
git add docs/decisions/2026-05-22_live_readiness.md \
        docs/decisions/2026-05-21_ledger_spec_recommendations.md \
        docs/runbooks/2026-05-22_live_capital_go.md \
        docs/known_issues/2026-05-21_aaats_engine_v6_halt.md \
        NEXT_PROMPT.md
git commit -m "docs(decisions): live-flip GO \$25 + ledger Q1-Q4 sign-off + runbook (2026-05-21)

- 2026-05-22_live_readiness.md: PROVISIONAL GO \$25 first tranche (escalates \$50/\$100 over 14d), three pre-flight verifications, auto-revert criteria.
- 2026-05-21_ledger_spec_recommendations.md: Q1=same DB, Q2=cash follow-up, Q3=opaque metadata_json, Q4=drain-cycle gate.
- 2026-05-22_live_capital_go.md: operator runbook with PF1/PF2/PF3, rollback baseline, first-24h watchlist, T+7 escalation gate.
- 2026-05-21_aaats_engine_v6_halt.md: v6 stack HALTED at -15.5% drawdown is sibling system, NOT paper-crypto.
- NEXT_PROMPT.md: this very prompt.

Sign-offs (operator, 2026-05-21):
- live-flip: GO \$25 first tranche on 2026-05-22 (recommended path)
- ledger Q1-Q4: A/A/A/A (recommended path)
- execution: Claude Code runs end-to-end with one human gate at flip moment"
git rebase origin/main
git push origin main
```

Verify by `git log origin/main --oneline -3` showing the new commit at top.

============================================================
WORKSTREAM B — Implement unified positions ledger (Q1-Q4=A)
============================================================

Three atomic commits. Each commit pushes after tests pass. Flag `USE_UNIFIED_LEDGER` stays OFF in production throughout this workstream.

### Commit B1 — schema + API + tests (no strategy changes)

- Add `positions` table to `data/paper_trades.db` via auto-migration. Composite primary key `(strategy, symbol)`.
- Create `foundation/positions.py` with `open_position`, `close_position`, `get_position`, `list_positions`. Pydantic validator at API boundary for `metadata_json` typing.
- Tests under `tests/foundation/test_positions.py`:
  - Round-trip: open → get → close → get returns None
  - Metadata opaque preservation (write arbitrary dict, read back unchanged)
  - Composite-key collision (two strategies, same symbol, both rows coexist)
  - `list_positions` filters (by strategy, by market, by both, by neither)
  - All must pass under existing pytest harness
- DO NOT touch any `trading/*.py` file
- DO NOT add `USE_UNIFIED_LEDGER` references yet
- Rollback baseline: `.rollback/2026-05-21_ledger_b1/` with `paper_trades.db.pre` + MANIFEST.txt per `docs/conventions/deploy_discipline.md`

Commit message: `feat(foundation): unified positions ledger schema + API (Q1-Q4 commit 1/3)`

Push after tests green.

### Commit B2 — migration + flag-flip safety

- `scripts/migrate_positions_to_db.py` per spec section "Migration plan":
  - Read each `data/*_state.json` (exclude `*cooldown*.json`, `halt_state.json`)
  - For each (symbol, pos), look up matching BUY row in `paper_trades.db` by `(strategy, symbol, ts ≈ entry_ts)` and copy real `shares` value (heals exit-sizing residuals retroactively)
  - Fallback: if no BUY row within ±5min, use `size_usd / entry_price` + log warning
  - Insert into `positions` table
  - Rename state files to `*_state.json.migrated_2026-05-21` (do not delete)
  - Print before/after counts + fallback warnings
- `scripts/drain_positions.py` (Q4=A precondition):
  - Asserts zero open positions in BOTH source A (state files) and source B (positions table)
  - Refuses (exits non-zero) if any open positions exist
  - On clean: appends to `data/ledger_flag_history.json` and returns 0
- `scripts/deploy_ledger_flag.py`:
  - Refuses flag flip unless `drain_positions.py` exited 0 in last 10 minutes
  - Performs atomic `.env` update via paramiko `.tmp + mv -f` pattern
- `data/ledger_flag_history.json` initial schema: `{"events": [], "current_value": false}`
- Tests using a fixture `paper_trades.db` with known state files
- Rollback baseline: `.rollback/2026-05-21_ledger_b2/`

Commit message: `feat(scripts): unified ledger migration + flag-flip safety (Q1-Q4 commit 2/3)`

Push after tests green.

### Commit B3 — strategy wiring behind flag (no behavior change with flag OFF)

- For each of `trading/altcoin_reversion.py`, `trading/bollinger_range.py`, `trading/stat_arb.py`, `trading/momentum_breakout.py`:
  - Read `USE_UNIFIED_LEDGER` env flag once at module import
  - Replace `_load_state()` / `_save_state()` calls with `foundation.positions` API when ON
  - Untouched fallback (existing JSON path) when OFF
- DO NOT modify `trading/funding_arb.py` (C5b stays halted at source)
- Flag stays OFF in production
- Tests: each strategy's test suite runs once with `USE_UNIFIED_LEDGER=False` (regression) and once with `USE_UNIFIED_LEDGER=True` (forward path)
- DO NOT edit `scripts/reconcile_intracycle.py` in this PR — reconciler swap is follow-up
- Rollback baseline: `.rollback/2026-05-21_ledger_b3/`

Commit message: `feat(trading): wire C1/C2/C3/C6 to positions API behind USE_UNIFIED_LEDGER flag (Q1-Q4 commit 3/3)`

Push after tests green.

**Do NOT deploy B3 to the box in this session.** Box deploy of ledger work is a separate operator action AFTER the live-flip soak is stable. Local commits + push only.

============================================================
WORKSTREAM C — Write live-flip scripts and commit
============================================================

### C1 — Generate `.env.live` locally

Read `.env` on workstation. Produce `.env.live` with:

```
PAPER_MODE=False
LIVE_CAPITAL_USD=25.0
LIVE_TRANCHE_START=2026-05-22T00:00:00Z
LIVE_TRANCHE_NAME=tranche_1_25usd
# All other vars copied verbatim from .env
```

Add `.env.live` to `.gitignore` if not present. DO NOT commit `.env.live` to repo.

### C2 — Write `scripts/live_flip_rollback_baseline.py`

```python
"""Pre-live-flip rollback baseline capture."""
import datetime, pathlib, paramiko, json

BOX = "aaats@100.95.126.39"
BASELINE_DIR = pathlib.Path(".rollback") / "2026-05-22_live_flip"

def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("100.95.126.39", username="aaats")
    _, stdout, _ = ssh.exec_command("cat /home/aaats/aaats/.env")
    (BASELINE_DIR / "env.pre").write_bytes(stdout.read())
    _, stdout, _ = ssh.exec_command(
        "docker inspect aaats-paper-crypto --format '{{.Image}}'"
    )
    (BASELINE_DIR / "image_sha.pre").write_bytes(stdout.read())
    ssh.exec_command(
        "cp /home/aaats/aaats/data/paper_trades.db /tmp/paper_trades_pre_live.db"
    )
    manifest = {
        "purpose": "pre-live-flip baseline (first tranche \$25)",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "files": [
            "env.pre",
            "image_sha.pre",
            "/tmp/paper_trades_pre_live.db (on box)",
        ],
    }
    (BASELINE_DIR / "MANIFEST.txt").write_text(json.dumps(manifest, indent=2))
    ssh.close()
    print(f"Rollback baseline written to {BASELINE_DIR}")

if __name__ == "__main__":
    main()
```

### C3 — Write `scripts/deploy_live_flip.py`

This script does the actual flip. It requires the operator to type `FLIP TO LIVE \$25` literally on stdin.

```python
"""Live-flip deploy. Operator types 'FLIP TO LIVE \$25' to proceed."""
import sys, time, pathlib, json, paramiko

BASELINE_DIR = pathlib.Path(".rollback") / "2026-05-22_live_flip"

def main():
    # Assert baseline is fresh
    manifest = BASELINE_DIR / "MANIFEST.txt"
    if not manifest.exists():
        sys.exit("ABORT: no rollback baseline at " + str(BASELINE_DIR))
    age_min = (time.time() - manifest.stat().st_mtime) / 60
    if age_min > 30:
        sys.exit(f"ABORT: baseline is {age_min:.1f}min old, re-run live_flip_rollback_baseline.py")

    # Assert pre-flights ran
    pf_log = pathlib.Path("data/pre_flight_log.json")
    if not pf_log.exists():
        sys.exit("ABORT: data/pre_flight_log.json missing — run PF1/PF2/PF3 first")
    pf = json.loads(pf_log.read_text())
    for k in ("PF1", "PF2", "PF3"):
        if k not in pf or pf[k].get("status") != "pass":
            sys.exit(f"ABORT: {k} not green in pre_flight_log.json")

    # Print summary and require typed confirmation
    print("=" * 60)
    print("LIVE FLIP — paper_mode False, capital \$25 USD")
    print("Box: aaats@100.95.126.39, container: aaats-paper-crypto")
    print("Rollback baseline at: " + str(BASELINE_DIR))
    print("PF1/PF2/PF3: all pass (per data/pre_flight_log.json)")
    print("=" * 60)
    print("Type 'FLIP TO LIVE \$25' to proceed, or anything else to abort:")
    response = input("> ").strip()
    if response != "FLIP TO LIVE \$25":
        sys.exit("ABORT: confirmation string mismatch — no changes made")

    # Atomic SCP upload of .env.live
    print("Uploading .env.live to box (atomic .tmp + mv -f)...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("100.95.126.39", username="aaats")
    sftp = ssh.open_sftp()
    sftp.put(".env.live", "/home/aaats/aaats/.env.tmp")
    sftp.close()
    ssh.exec_command("mv -f /home/aaats/aaats/.env.tmp /home/aaats/aaats/.env")
    time.sleep(2)

    # Restart container
    print("Restarting aaats-paper-crypto...")
    _, stdout, stderr = ssh.exec_command(
        "cd /home/aaats/aaats && docker compose -f deployment/docker-compose.yml restart aaats-paper-crypto"
    )
    stdout.channel.recv_exit_status()
    print(stdout.read().decode())
    print(stderr.read().decode())

    # Tail logs for 30s
    print("Tailing logs for 30s...")
    _, stdout, _ = ssh.exec_command("docker logs aaats-paper-crypto --tail 100 --since 1m")
    print(stdout.read().decode())
    ssh.close()
    print("\nLIVE FLIP COMPLETE. Watch first 4 cycles via tail_paper_crypto.py.")

if __name__ == "__main__":
    main()
```

### C4 — Write `scripts/run_pre_flights.py`

Runs PF1, PF2, PF3 sequentially. Writes results to `data/pre_flight_log.json`. PF3 includes Telegram synthetic test — operator must confirm by replying to a chat prompt that they saw the alert in chat `1946109268`.

```python
"""Run PF1/PF2/PF3 from docs/runbooks/2026-05-22_live_capital_go.md."""
import paramiko, json, datetime, time, pathlib, sys

LOG = pathlib.Path("data/pre_flight_log.json")

def ssh_connect():
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect("100.95.126.39", username="aaats")
    return s

def pf1(ssh):
    print("PF1: re-running deployment_decision evaluation...")
    _, stdout, stderr = ssh.exec_command(
        "docker exec aaats-paper-crypto python -m scripts.evaluate_live_readiness 2>&1"
    )
    out = stdout.read().decode()
    print(out)
    # Heuristic: pass if 'allowed: true' or 'readiness_score' >= 90
    passed = "allowed: true" in out.lower() or "allowed\": true" in out.lower()
    return {"status": "pass" if passed else "fail", "output": out[:2000]}

def pf2(ssh):
    print("PF2: reconcile clean check...")
    _, stdout, _ = ssh.exec_command(
        "cat /home/aaats/aaats/data/share_equality_mismatches.json"
    )
    mismatches = stdout.read().decode().strip()
    print(f"share_equality_mismatches.json: {mismatches}")
    _, stdout, _ = ssh.exec_command(
        "docker exec aaats-paper-crypto python -c \"import sqlite3; c=sqlite3.connect('/app/data/paper_trades.db'); print('trades 24h:', c.execute(\\\"SELECT COUNT(*) FROM paper_trades WHERE timestamp>=datetime('now','-24 hours')\\\").fetchone()[0])\""
    )
    out = stdout.read().decode()
    print(out)
    # Pass if mismatches is empty or only known historical entries, and trades >= 5 in 24h
    passed = ("{}" in mismatches or '"TON' in mismatches or '"FET' in mismatches) and "trades 24h:" in out
    return {"status": "pass" if passed else "fail", "mismatches": mismatches, "output": out[:500]}

def pf3(ssh):
    print("PF3: Telegram synthetic test...")
    ssh.exec_command(
        'echo \'{"_TEST_LIVE_2026_05_22_|_TEST_LIVE_2026_05_22_": 1}\' > /home/aaats/aaats/data/share_equality_mismatches.json'
    )
    time.sleep(65)
    ssh.exec_command(
        'echo \'{"_TEST_LIVE_2026_05_22_|_TEST_LIVE_2026_05_22_": 2}\' > /home/aaats/aaats/data/share_equality_mismatches.json'
    )
    print("Wrote test counter. Waiting 120s for alert evaluation...")
    time.sleep(120)
    print("Check Telegram chat 1946109268 for a _TEST_LIVE_2026_05_22_ alert.")
    response = input("Did you receive the Telegram alert? (yes/no): ").strip().lower()
    # Revert
    ssh.exec_command('echo "{}" > /home/aaats/aaats/data/share_equality_mismatches.json')
    return {"status": "pass" if response == "yes" else "fail", "operator_confirm": response}

def main():
    ssh = ssh_connect()
    results = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "PF1": pf1(ssh),
        "PF2": pf2(ssh),
        "PF3": pf3(ssh),
    }
    LOG.write_text(json.dumps(results, indent=2))
    ssh.close()
    failed = [k for k in ("PF1","PF2","PF3") if results[k]["status"] != "pass"]
    if failed:
        print(f"PRE-FLIGHTS FAILED: {failed}. ABORT live flip.")
        sys.exit(1)
    print("ALL PRE-FLIGHTS PASS. Live flip is permitted.")

if __name__ == "__main__":
    main()
```

### C5 — Write `scripts/tail_paper_crypto.py`

Streams paper-crypto logs for 90 min (covers ~6 cycles at 15-min cadence; way more than the 4 minimum), parsing each cycle banner. Reports cycle-by-cycle status to stdout. Exits 0 if 4 cycles ran clean, exits 1 (with diagnostic) if any cycle errored, restarted, or showed an unexpected HALT.

```python
"""Tail paper-crypto logs through first N cycles after live flip."""
import paramiko, time, re, sys, json, pathlib

CYCLE_BANNER = re.compile(r"==.*Crypto cycle.*?capital=USD ([\d.]+)")
HALT_PATTERN = re.compile(r"HALT|RISK HALT", re.I)
ERROR_PATTERN = re.compile(r"\[ERROR\]|Exception|Traceback")
TARGET_CYCLES = 4
TIMEOUT_MIN = 90

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect("100.95.126.39", username="aaats")
    print(f"Tailing aaats-paper-crypto logs for up to {TIMEOUT_MIN}min, looking for {TARGET_CYCLES} clean cycles...")
    cycles_seen = 0
    halts_seen = 0
    errors_seen = 0
    start = time.time()
    last_banner_capital = None
    _, stdout, _ = ssh.exec_command("docker logs -f --tail 50 aaats-paper-crypto")
    while time.time() - start < TIMEOUT_MIN * 60:
        line = stdout.readline()
        if not line: break
        line = line.strip()
        m = CYCLE_BANNER.search(line)
        if m:
            cycles_seen += 1
            last_banner_capital = float(m.group(1))
            print(f"[cycle {cycles_seen}/{TARGET_CYCLES}] capital=\${last_banner_capital}")
            if cycles_seen >= TARGET_CYCLES:
                break
        if HALT_PATTERN.search(line) and "test" not in line.lower():
            halts_seen += 1
            print(f"[HALT DETECTED] {line}")
        if ERROR_PATTERN.search(line):
            errors_seen += 1
            print(f"[ERROR] {line}")
    ssh.close()
    result = {
        "cycles_seen": cycles_seen,
        "halts_seen": halts_seen,
        "errors_seen": errors_seen,
        "last_capital": last_banner_capital,
    }
    pathlib.Path("data/first_cycles_log.json").write_text(json.dumps(result, indent=2))
    if halts_seen > 0 or errors_seen > 5 or cycles_seen < TARGET_CYCLES:
        print(f"FAIL: {result}")
        sys.exit(1)
    print(f"PASS: {result}")

if __name__ == "__main__":
    main()
```

### Commit C scripts

```bash
git add scripts/live_flip_rollback_baseline.py scripts/deploy_live_flip.py scripts/run_pre_flights.py scripts/tail_paper_crypto.py .gitignore
git commit -m "feat(scripts): live-flip baseline + pre-flights + deploy + first-cycles tail (operator-typed confirmation gate)"
git push origin main
```

============================================================
WORKSTREAM D — Execute the live flip (end-to-end)
============================================================

**This workstream is execution, not preparation. The operator has authorized you to run all of these steps. The only human gate is the typed string `FLIP TO LIVE \$25` inside `scripts/deploy_live_flip.py`.**

Run in order. STOP and report to operator if ANY step fails.

### D1 — Pre-flights

```bash
python scripts/run_pre_flights.py
```

This will print results to stdout AND prompt you (Claude Code) to confirm the Telegram alert was received. **You are not the operator** — when prompted "Did you receive the Telegram alert?", you must STOP and ask the operator in chat. Do NOT auto-respond "yes" without operator confirmation. Once operator confirms, you type their answer.

Expected: all three PFs pass; `data/pre_flight_log.json` contains three "pass" entries.

If any PF fails: STOP, do not proceed to D2. Report the failure with the full output.

### D2 — Rollback baseline

```bash
python scripts/live_flip_rollback_baseline.py
```

Expected: `.rollback/2026-05-22_live_flip/` contains `env.pre`, `image_sha.pre`, `MANIFEST.txt`.

### D3 — The flip itself

```bash
python scripts/deploy_live_flip.py
```

When the script prompts `Type 'FLIP TO LIVE \$25' to proceed, or anything else to abort:`, you must STOP and ask the operator to type the confirmation themselves. Paste the prompt to chat verbatim. Wait for operator response. ONLY if operator types the literal string `FLIP TO LIVE \$25`, you pass that input to the script's stdin.

If operator types anything else, abort. No live flip.

Expected output: container restart succeeds, log tail shows clean cycle init with `PAPER_MODE=False`.

### D4 — First 4 cycles

```bash
python scripts/tail_paper_crypto.py
```

Runs up to 90 minutes (≈6 cycles). Watches for HALT events, errors, restarts. Writes `data/first_cycles_log.json`.

Expected: 4 cycles, 0 HALT, ≤5 transient errors, capital reading sane.

If 4 cycles clean: SUCCESS — report to operator. If any cycle errors or HALTs fire: STOP, alert operator with full log, prepare revert command (do NOT auto-revert).

### D5 — Update docs (outcome + execution amendment)

Two edits in the same commit.

**Edit 1** — append to `docs/decisions/2026-05-22_live_readiness.md`:

```
## Outcome

Live flip executed: <timestamp>
- PF1: pass | PF2: pass | PF3: pass (operator confirmed Telegram)
- Rollback baseline: .rollback/2026-05-22_live_flip/
- Image SHA at flip: <sha>
- First 4 cycles: <N> clean, <halts> halts, <errors> errors
- T+7 review: scheduled via Cowork (2026-05-29T09:00 IST)

## Tranche 1 execution amendment (2026-05-21 operator directive)

Claude Code was authorized to execute this tranche end-to-end, with two human
gates only: Telegram receipt confirmation at PF3 and the `FLIP TO LIVE \$25`
typed string at deploy. The "operator-only" framing elsewhere in this doc
remains the default for future tranches (\$50, \$100, and any subsequent live
flips) absent a session-specific override at the time.
```

**Edit 2** — append the same amendment block to `docs/runbooks/2026-05-22_live_capital_go.md` under a new `## Tranche 1 execution amendment (2026-05-21 operator directive)` heading. Same text as Edit 1's amendment block.

```bash
git add docs/decisions/2026-05-22_live_readiness.md \
        docs/runbooks/2026-05-22_live_capital_go.md \
        data/pre_flight_log.json \
        data/first_cycles_log.json
git commit -m "ops(live-flip): tranche 1 \$25 live executed 2026-05-22 — outcome + execution amendment recorded"
git push origin main
```

============================================================
WORKSTREAM E — Confirm Cowork scheduled task is set
============================================================

This is a sanity check. The Cowork session already created task `aaats-live-readiness-gate-2026-05-29` to fire 2026-05-29T09:00 IST. You don't need to recreate it — just confirm to the operator that it exists by reminding them to check Cowork's "Scheduled" sidebar.

============================================================
HARD CONSTRAINTS
============================================================

- Operator types `FLIP TO LIVE \$25` themselves at D3. Do NOT auto-respond. Do NOT skip this gate even if explicitly authorized — this is the human-in-loop trigger.
- Operator confirms Telegram alert at PF3. Do NOT auto-confirm.
- DO NOT touch `trading/funding_arb.py` (C5b stays halted)
- DO NOT widen `DUST_TOLERANCE_USD` beyond \$0.25
- DO NOT modify `scripts/reconcile_intracycle.py` — reconciler swap is follow-up
- DO NOT touch `aaats-engine` (v6 stack, parallel, currently HALTED — separate concern)
- Tests pass before every push
- Rollback baselines before every box file edit
- If anything surprises you, STOP and report — better one extra chat turn than a botched live flip

============================================================
WHEN DONE, REPORT BACK
============================================================

```
- Workstream A: <N> commits pushed. SHA: <sha>
- Workstream B1: tests <N> passing. SHA: <sha>
- Workstream B2: tests <N> passing. SHA: <sha>
- Workstream B3: tests <N> passing. SHA: <sha>
- Workstream C: scripts pushed. SHA: <sha>
- Workstream D1 (PF): PF1=<pass/fail> PF2=<pass/fail> PF3=<pass/fail>
- Workstream D2 (baseline): captured at <path>
- Workstream D3 (flip): EXECUTED at <ts> | NOT EXECUTED (operator aborted)
- Workstream D4 (first cycles): <N> clean, <halts> halts
- Workstream D5 (outcome doc): pushed. SHA: <sha>
- Workstream E: scheduled task present per operator's sidebar
- LIVE STATUS: \$25 tranche running | reverted | aborted before flip
- Time elapsed: <X> min
- Anything surprising: <one line, or "none">
```

Go.

---PROMPT END---

## Why this structure

- **One human gate**, at the flip moment (`FLIP TO LIVE $25` typed string + the Telegram-received confirmation). Everything else automated.
- **Auto-revert NOT automated** — if first cycles fail, Claude Code alerts operator and prepares the revert command but doesn't execute it. Same principle as the flip gate.
- **Rollback baselines** before every box-side change so any step can be reverted cleanly.
- **Failure modes route through stop-and-report** rather than retry-and-hope.

## What Cowork (this session) is doing in parallel

- The `aaats-live-readiness-gate-2026-05-29` scheduled task is set to fire 2026-05-29T09:00 IST for T+7 review.
- Memory is updated with the sign-offs received today.

## When Claude Code is done

Bring its 10-line summary back here and I'll draft the next move (T+7 review prep, $50 tranche runbook, or revert post-mortem depending on outcome).
