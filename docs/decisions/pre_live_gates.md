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

- **Status**: deployed on Contabo box via paramiko, but UNTRACKED locally and missing from `origin/main` as of 2026-05-15.
- **Files**: `markets/crypto/universe.py`, `scanner.py`, `allocator.py`, `correlation_guard.py`, `sentiment.py`, `confidence_scorer.py`.
- **Why it gates live**: a fresh clone of `origin/main` cannot reproduce the running container — the scanner pipeline silently falls back to hardcoded SYMBOLS (per `except` block at [trading/live_paper_runner.py:1581](../../trading/live_paper_runner.py#L1581)). Reproducibility is a precondition for live audit/rollback.
- **Exit criteria**: commit all six modules to `origin/main` with their own tests; verify a clean clone + `docker compose build` produces a container whose `live_paper_runner.py` cycle log shows `[scanner] universe size=...` rather than the fallback log line.

## How to add a gate

Append a new `### G<n> — <short title>` section above. Each entry should state
status, file-references, why it blocks live, and the exit criteria that retire
the gate.
