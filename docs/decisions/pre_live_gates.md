# Pre-live-capital gates

Items that are tolerable in paper mode but must be resolved before any move to
live capital. New entries append here as they're discovered.

## Gates

### G1 — `halt_on_critical=False` in intracycle reconciler call

- **Status**: ACTIVE in paper mode (2026-05-15).
- **Call-site**: [trading/live_paper_runner.py:1696](../../trading/live_paper_runner.py#L1696).
- **Detail**: [docs/known_issues/2026-05-15_halt_on_critical_false.md](../known_issues/2026-05-15_halt_on_critical_false.md).
- **Why it gates live**: a real position-drift event would not auto-halt the
  runner; only the drawdown engine in [risk/engine.py](../../risk/engine.py)
  would stop trading, and only after the loss has already accumulated. In live
  mode the drift signal must be load-bearing.
- **Exit criteria**: see "Conditions under which the flag MUST be flipped back
  to `True`" in the known-issues doc.

### G2 — Scanner-pipeline support modules not in `origin/main`

- **Status**: CLOSED 2026-05-15 — the six modules are now committed to `origin/main` as part of the scanner-first chain commit ("feat(markets): scanner-first C3/C6 universe + sentiment pipeline").
- **Files**: `markets/crypto/{universe,scanner,allocator,correlation_guard,sentiment,confidence_scorer}.py`.
- **Original problem**: deployed on Contabo box via paramiko, but UNTRACKED locally and missing from `origin/main` until the closure commit. A fresh clone of `origin/main` could not reproduce the running container — the scanner pipeline silently fell back to hardcoded SYMBOLS (per `except` block at [trading/live_paper_runner.py:1581](../../trading/live_paper_runner.py#L1581)).
- **Validation**: a clean clone + import sweep now resolves all six modules without `ModuleNotFoundError`; the runner's scanner branch logs `[scanner] universe size=...` rather than the fallback log line.

### G3 — Image built from a partial host build context

- **Status**: OPEN 2026-05-15. Forensic audit at [docs/decisions/2026-05-15_box_repo_audit.md](2026-05-15_box_repo_audit.md). Verdict: **FAIL**.
- **Finding**: 278 files tracked in `origin/main` are absent from the running container's image (`7051c405c75a…`). The HOST build context at `/home/aaats/aaats/` itself is missing 16 top-level directories — `analytics/`, `backtesting/`, `compliance/`, `engine/`, `infrastructure/`, `intelligence/`, `learning/`, `portfolio/`, `production_readiness/`, `research/`, `safety/`, `strategies/`, `streamlit_app/`, `tools/`, `v6-stack/`, `validation/` — plus root files (`kill.py`, `autodriver.sh`, `requirements.in`, `docker-compose.engine.yml`, `.pre-commit-config.yaml`, `config/settings.py`).
- **Root cause**: the paramiko SCP deploy ships individual files. The addition of an entirely new directory to `origin/main` is not accompanied by any per-file SCP, so new top-level directories never propagate to `/home/aaats/aaats/`. The image is built faithfully from the partial host tree.
- **Why it gates live**: a fresh rebuild of the image (e.g., after a host crash, or an unrelated container restart that forces a rebuild) would produce a container whose contents materially differ from `origin/main`. Code paths that depend on currently-absent modules (`config/settings.py` is imported by `foundation/health_monitor.py`, which is on box; `streamlit_app/*` is consumed by the dashboard service from the same image; any future code that imports from `strategies/`, `engine/`, `portfolio/`, `intelligence/`, etc.) would either crash on startup or silently take a fallback path. `origin/main` cannot currently serve as canonical for "what is running" — a non-negotiable property for live capital.
- **Exit criteria**:
  1. Host build context resynced to `origin/main` (rsync mirror) with rollback baseline captured at `.rollback/<date>_audit_rebuild/`.
  2. Image rebuilt, container replaced, audit re-run produces 0 mismatches in categories (a) and (b) — or each remaining entry has an explicit, captured exception.
  3. New-dir parity check added to the deploy-dirty-guard (commit `ae24d2c`) so this drift mode cannot silently recur.
  4. Root `.dockerignore` added so the rebuilt image excludes `docs/`, `.rollback/`, `.claude/`, `.github/`, runtime artifacts.

## How to add a gate

Append a new `### G<n> — <short title>` section above. Each entry should state
status, file-references, why it blocks live, and the exit criteria that retire
the gate.
