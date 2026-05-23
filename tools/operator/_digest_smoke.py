"""
Deploy-time smoke check for the daily-digest pipeline.

Detects the mount-gap drift that bit session 5: the digest container could
build a body but reported ``Equity: N/A`` because the per-mode state volume
wasn't mounted into the watchdog. This helper runs the digest dry-run on the
target box and parses the output, asserting that the Equity / Peak / Drawdown
trio renders to numbers (not "N/A") when the on-disk
``risk_engine_state.<mode>.json`` exists.

Usage (called from deploy scripts after the rebuild+restart step):

    from tools.operator._digest_smoke import assert_digest_renders_equity

    ok, msg = assert_digest_renders_equity(
        ssh_client,
        target_container="aaats-watchdog",
        mode="paper",
    )
    if not ok:
        sys.exit(f"deploy-smoke failed: {msg}")

The check is non-destructive — it executes ``python -m monitoring.daily_digest
--dry-run`` inside the container and ONLY parses stdout. The body is not sent
to Telegram and digest_log.json is not mutated by --dry-run.

Why this exists: a digest that builds successfully but reports N/A equity is
a SILENT failure mode. The operator sees a normal Telegram message with no
errors — the bug is the absence of expected information. The drift check
catches this at deploy time by comparing two source-of-truth files:

  1. The on-disk risk-engine state file (mounted into the trading container).
  2. The digest body produced inside the digest container.

If (1) exists with last_equity but (2) renders "N/A", the volume mount is
broken inside the digest container.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol


# ── Output protocol so the helper is unit-testable without paramiko ─────────


class _ExecResult(Protocol):
    """The shape we need from a remote exec call."""
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[str], _ExecResult]


@dataclass(frozen=True)
class _SmokeResult:
    ok: bool
    message: str
    equity_line: str = ""


# ── Equity-line parser ──────────────────────────────────────────────────────


# The digest's P&L section renders:
#   Equity:     $110.50  (peak $131.32, dd -15.9%)
# or:
#   Equity:     N/A  (peak N/A, dd N/A)
_EQUITY_LINE_RE = re.compile(r"^\s*Equity:\s+(.*)$", re.MULTILINE)


def parse_equity_line(digest_body: str) -> str | None:
    """Return the verbatim Equity line if present, else None."""
    m = _EQUITY_LINE_RE.search(digest_body)
    return m.group(1).strip() if m else None


def equity_line_is_na(equity_line: str) -> bool:
    """True iff the line is the all-N/A pattern produced when the digest can't
    read the risk-engine state file."""
    return "N/A" in equity_line


# ── Top-level smoke assertion ───────────────────────────────────────────────


def assert_digest_renders_equity(
    run: CommandRunner,
    *,
    target_container: str = "aaats-watchdog",
    mode: str = "paper",
    risk_state_path_in_container: str | None = None,
) -> _SmokeResult:
    """Run the digest dry-run inside ``target_container`` and assert that
    its Equity line is NOT all-N/A when the on-disk state file exists.

    Returns a ``_SmokeResult`` with ``ok=True`` and the parsed Equity line
    on success, ``ok=False`` and a diagnostic ``message`` on failure.

    Args:
        run: Callable that executes a shell string on the box and returns
             an object with ``returncode``, ``stdout``, ``stderr``. The
             deploy scripts pass a paramiko-backed runner; tests pass a stub.
        target_container: Name of the container that hosts the digest module.
        mode: ``paper`` or ``live`` — determines the expected
              ``risk_engine_state.<mode>.json`` filename.
        risk_state_path_in_container: Override for the in-container state-file
            path. Defaults to ``/app/data/state-<mode>/risk_engine_state.<mode>.json``.
    """
    state_path = (
        risk_state_path_in_container
        or f"/app/data/state-{mode}/risk_engine_state.{mode}.json"
    )

    # 1. Confirm the state file exists in the container; if it doesn't, the
    #    N/A render is correct and the smoke check passes vacuously.
    probe_cmd = (
        f"docker exec {target_container} test -s {state_path}"
        f" && echo STATE_PRESENT || echo STATE_MISSING"
    )
    probe = run(probe_cmd)
    if probe.returncode not in (0, 1):
        return _SmokeResult(
            ok=False,
            message=(
                f"could not probe state file via docker exec: "
                f"returncode={probe.returncode} stderr={probe.stderr[:200]!r}"
            ),
        )
    if "STATE_MISSING" in probe.stdout:
        return _SmokeResult(
            ok=True,
            message=(
                f"state file {state_path} does not exist inside "
                f"{target_container}; N/A digest render is correct (skipped)"
            ),
        )

    # 2. Run the digest dry-run and capture stdout.
    digest_cmd = (
        f"docker exec {target_container} python -m monitoring.daily_digest --dry-run"
    )
    res = run(digest_cmd)
    if res.returncode != 0:
        return _SmokeResult(
            ok=False,
            message=(
                f"digest dry-run exited non-zero ({res.returncode}). "
                f"stderr={res.stderr[:200]!r}"
            ),
        )

    equity_line = parse_equity_line(res.stdout)
    if equity_line is None:
        return _SmokeResult(
            ok=False,
            message=(
                "could not locate 'Equity:' line in digest body; the digest "
                "module's render format may have changed"
            ),
        )

    if equity_line_is_na(equity_line):
        return _SmokeResult(
            ok=False,
            message=(
                f"state file {state_path} exists inside {target_container} "
                f"but the digest reports Equity: {equity_line!r}. "
                f"This is the session-5 volume-mount-gap drift; check the "
                f"watchdog's volumes block in deployment/docker-compose.yml "
                f"for a 'state-<mode>:/app/data/state-<mode>:ro' mount."
            ),
            equity_line=equity_line,
        )

    return _SmokeResult(
        ok=True,
        message=f"digest renders equity correctly: {equity_line}",
        equity_line=equity_line,
    )
