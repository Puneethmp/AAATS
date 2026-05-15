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

- **Status**: OPEN 2026-05-15 (downgraded same day after triage from "blanket fail" to "blocked on RUNTIME-LATENT dirs + new-dir parity guard"). Forensic audit at [docs/decisions/2026-05-15_box_repo_audit.md](2026-05-15_box_repo_audit.md). Verdict: **FAIL on structural completeness; PASS on per-file SCP fidelity; PASS on live-runtime safety**.
- **Finding**: 278 files tracked in `origin/main` are absent from the running container's image (`7051c405c75a…`). The HOST build context at `/home/aaats/aaats/` itself is missing 16 top-level directories — `analytics/`, `backtesting/`, `compliance/`, `engine/`, `infrastructure/`, `intelligence/`, `learning/`, `portfolio/`, `production_readiness/`, `research/`, `safety/`, `strategies/`, `streamlit_app/`, `tools/`, `v6-stack/`, `validation/` — plus root files (`kill.py`, `autodriver.sh`, `requirements.in`, `docker-compose.engine.yml`, `.pre-commit-config.yaml`, `config/settings.py`).
- **Triage outcome**: classification table in the audit doc shows **zero** RUNTIME-ACTIVE entries. The live runtime (`paper_loop.py --market crypto`, healthcheck `scripts/health_check.py`, daily ML retrain) imports nothing from the 16 missing dirs. The 278-file gap is real but no live code path is currently failing because of it.
- **Three ghost-code commits today** captured files into missing dirs while their messages implied "live" status: `395a6a6` (HMM regime half), `eeb0963` (`_ml_gate.yaml`), `2c69a54` (Grafana alert YAML). The runtime halves of each are deployed; the missing-dir halves are not.
- **Root cause**: the paramiko SCP deploy ships individual files. The addition of an entirely new directory to `origin/main` is not accompanied by any per-file SCP, so new top-level directories never propagate to `/home/aaats/aaats/`. The image is built faithfully from the partial host tree.
- **Why it gates live**: a fresh rebuild of the image (after a host crash, an unrelated restart, or a manual `--build`) would produce a container whose contents materially differ from `origin/main`. Wiring up any of the RUNTIME-LATENT dirs (the obvious next step for HMM regime, ML gate, strategies plug-in, etc.) would silently fail until the parity issue is closed. `origin/main` cannot currently serve as canonical for "what is running" — a non-negotiable property for live capital.
- **Exit criteria** (revised 2026-05-15):
  1. RUNTIME-LATENT dirs rsynced to `/home/aaats/aaats/` (per the audit doc's classification table), image rebuilt, container replaced, audit re-run produces 0 mismatches in RUNTIME bucket.
  2. WORKSTATION-ONLY and PARALLEL-SYSTEM buckets explicitly enumerated in an allow-list at [docs/conventions/deploy_discipline.md](../conventions/deploy_discipline.md); audit re-run treats them as expected absences.
  3. New-dir parity check added to the deploy-dirty-guard (commit `ae24d2c`); recipe at [docs/known_issues/2026-05-15_deploy_newdir_parity.md](../known_issues/2026-05-15_deploy_newdir_parity.md).
  4. Grafana alert YAML (`share_equality.yaml`) deployed to `/srv/aaats/compose/grafana/provisioning/alerting/` so commit `2c69a54`'s alert half catches up to the live runtime half.
  5. Root `.dockerignore` added so the rebuilt image excludes `docs/`, `.rollback/`, `.claude/`, `.github/`, runtime artifacts.

## How to add a gate

Append a new `### G<n> — <short title>` section above. Each entry should state
status, file-references, why it blocks live, and the exit criteria that retire
the gate.
