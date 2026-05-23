"""PF5.8 — Flash-crash HALT_ALL fires (Phase 2 [P2.3]).

Synthetic injection of a portfolio mark drop to 0.79 * peak (i.e.
-21% drawdown, just past the -20% portfolio-kill threshold) via the
risk/engine.RiskEngine.update_portfolio() seam. Confirms the engine's
HALT_ALL path fires and that the operator-channel halt
(data/halt_state.json) is NOT crossed (per CLAUDE.md kill-switch
semantics — engine kill is a per-process new-entry gate, not a global
operator halt).

The test uses a FRESH RiskEngine instance seeded from the persisted
peak file, so it does not perturb the runner's live engine state.
After confirming HALT_ALL, we verify a subsequent update with a
non-breaching value still returns HALT_ALL (engine's _all_halted is
sticky within the process; reset_all() is the explicit clear path).

Skips unless AAATS_BOX_SMOKE=1.
"""
from __future__ import annotations

import json
import os
import pathlib as _pl
from typing import Any

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("AAATS_BOX_SMOKE") != "1",
    reason="PF5.8 hits the live Contabo box; set AAATS_BOX_SMOKE=1 to run.",
)


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = _pl.Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().split("#")[0].strip()
    return env


def _ssh_client() -> Any:
    import paramiko
    env = _load_env()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        env["CONTABO__TAILSCALE_IP"], port=22,
        username=env["CONTABO__SSH_USER"],
        password=env["CONTABO__SSH_PASSWORD"],
        timeout=30,
    )
    return client


def _run(client: Any, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    return rc, out, err


# The injection script — copied into the container and executed.
# Uses a fresh RiskEngine instance so the runner's engine isn't perturbed.
INJECTION_SCRIPT = '''
import json, sys
from risk.engine import RiskEngine

# Seed the test engine at $200 (post-reset baseline). The persisted
# peak file (state-paper/risk_engine_state.paper.json) will also be
# loaded if present — __post_init__ uses max(initial, persisted).
eng = RiskEngine(initial_portfolio=200.0)
peak = eng._portfolio_peak

# Make sure peak is observed first so the breach calculation is
# well-defined under the doctrine "max(initial, persisted, current)"
# semantics.
if peak <= 0:
    eng.update_portfolio(200.0)
    peak = eng._portfolio_peak

# Inject 0.79 * peak (-21% drawdown, just past -20% portfolio-kill).
breach_value = round(peak * 0.79, 4)
decision = eng.update_portfolio(breach_value)

# Check operator halt channel is UNCROSSED (it should be — the engine
# halt is per-process, not the operator JSON channel).
try:
    with open("/app/data/halt_state.json") as f:
        op_halt = json.load(f)
except (OSError, ValueError):
    op_halt = {}

# Subsequent new-entry check must be blocked while _all_halted is True
# (this is the "all new entries blocked next 3 cycles" guarantee from
# the operator-away protocol). check_new_order is the path strategies
# actually go through.
halted_after_breach = eng.is_all_halted()
new_entry_decision = eng.check_new_order(
    market="crypto", entry_price=100.0, shares=1.0, capital=200.0,
)

# Cleanup: reset the engine so subsequent runs don't inherit halt.
eng.reset_all()

print(json.dumps({
    "peak": peak,
    "breach_value": breach_value,
    "decision_action": decision.action,
    "decision_reason": decision.reason,
    "is_all_halted_after_breach": halted_after_breach,
    "new_entry_action_after_breach": new_entry_decision.action,
    "is_all_halted_after_reset": eng.is_all_halted(),
    "operator_halt_crypto": bool(op_halt.get("crypto", False)),
}, indent=2))
'''


def test_pf5_8_engine_halt_all_fires_on_synthetic_crash() -> None:
    client = _ssh_client()
    try:
        # Copy the injection script into the container and run it.
        sftp = client.open_sftp()
        try:
            with sftp.open("/tmp/pf5_8_inject.py", "w") as fh:
                fh.write(INJECTION_SCRIPT)
        finally:
            sftp.close()

        rc, _, _ = _run(client,
            "docker cp /tmp/pf5_8_inject.py aaats-paper-crypto:/tmp/pf5_8_inject.py")
        assert rc == 0, "docker cp of injection script failed"

        rc, out, err = _run(client,
            "docker exec aaats-paper-crypto python /tmp/pf5_8_inject.py 2>&1",
            timeout=60)
        assert rc == 0, f"injection script failed rc={rc} err={err} out={out}"

        # Extract the JSON payload (script may also print log lines first).
        try:
            payload_start = out.index("{")
            payload_end = out.rindex("}") + 1
            payload = json.loads(out[payload_start:payload_end])
        except (ValueError, json.JSONDecodeError) as exc:
            raise AssertionError(
                f"could not parse injection script output as JSON: {out!r} ({exc})"
            )

        # Primary gate: HALT_ALL fired on the breach.
        assert payload["decision_action"] == "HALT_ALL", (
            f"engine did not return HALT_ALL on -21% synthetic drawdown; "
            f"action={payload['decision_action']}, reason={payload['decision_reason']}. "
            "Per the operator-away protocol this is a PAGER-LEVEL failure — "
            "engine kill is broken and the soak cannot start safely."
        )

        # Operator channel must be uncrossed.
        assert payload["operator_halt_crypto"] is False, (
            "engine HALT_ALL must NOT cross the operator halt_state.json "
            "channel — they are intentionally separate (per CLAUDE.md "
            "kill-switch semantics)."
        )

        # Sticky-halt check: new-entry path must be blocked while
        # _all_halted is set. This is the "all new entries blocked
        # next 3 cycles" guarantee from the operator-away protocol —
        # strategies go through check_new_order, not update_portfolio,
        # so HALT_ALL must propagate to that path.
        assert payload["is_all_halted_after_breach"] is True, (
            "is_all_halted() should be True immediately after the breach"
        )
        assert payload["new_entry_action_after_breach"] == "HALT_ALL", (
            f"check_new_order should refuse new entries while engine is "
            f"halted; got action="
            f"{payload['new_entry_action_after_breach']!r}"
        )

        # After reset_all the engine clears.
        assert payload["is_all_halted_after_reset"] is False, (
            "reset_all should clear the engine halt flag"
        )

    finally:
        client.close()
