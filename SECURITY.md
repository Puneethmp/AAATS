# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in AAATS, please report it privately.

**Do NOT open a public issue for security problems.**

Instead, email the maintainer at the address on the GitHub profile, or open a
private security advisory via GitHub's "Security" → "Report a vulnerability"
flow on this repository. Include:

- A description of the vulnerability and its impact.
- Steps to reproduce (a minimal proof-of-concept is ideal).
- Any suggested remediation.

You can expect an initial acknowledgement within 72 hours. We aim to triage
critical issues within 7 days and ship a fix or mitigation within 30 days,
depending on severity and complexity.

## Scope

In scope:

- Authentication / authorization bypasses on any deploy script or runtime
  surface.
- Remote code execution, command injection, or path traversal in any module
  that handles external input (broker adapters, web dashboards, scheduled
  task runners).
- Secret leakage in source, build artifacts, container images, or logs.
- Risk-engine bypasses that allow trades larger than configured caps or in
  a halted market.
- Dependency CVEs affecting any path imported by production code.

Out of scope:

- Issues that require physical access to the operator's workstation.
- Self-DoS via misconfiguration on a fork.
- Vulnerabilities in third-party services we depend on (please report to
  those projects directly).
- Strategy-edge concerns (P&L performance is not a security issue).

## Supported versions

This is a single-deployment internal project. Only the latest `main` is
supported. Older commits are kept for audit and rollback but are not patched.

## Defensive baselines (operator commitments)

The project maintains these baselines; deviations are treated as bugs:

- **No secrets in source.** Credentials are loaded from environment variables
  (see [`.env.example`](.env.example)). The repo has a `gitleaks` pre-commit
  hook ([`.pre-commit-config.yaml`](.pre-commit-config.yaml)) that blocks
  commits containing common secret patterns.
- **State-file schema validation.** Every JSON state file the runner reads
  has a pydantic schema at [`state/schemas.py`](state/schemas.py). Schema
  mismatches fail the container at boot rather than silently corrupting
  downstream readers.
- **Per-strategy isolation.** A strategy raising an exception is isolated to
  that strategy and auto-halted after three consecutive failures; see
  [`trading/strategy_isolation.py`](trading/strategy_isolation.py).
- **Live-trading mode gated by explicit operator action.** `SYSTEM__TRADING_MODE`
  must be set to `live`, AND the operator must run the live-flip script with
  a typed confirmation. Paper builds reject any `live` mode at startup via
  `deployment/scripts/validate_env.py`.
- **Risk caps hard-coded.** Per-trade max loss, per-market drawdown halt,
  and portfolio drawdown halt are constants in [`risk/engine.py`](risk/engine.py)
  and cannot be overridden by config alone.

## Acknowledgements

We will credit reporters who responsibly disclose vulnerabilities (with their
permission) in the release notes for the patch.
