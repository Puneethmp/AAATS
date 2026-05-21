"""scripts/evaluate_live_readiness.py -- thin wrapper over the gatekeeper.

Invoked by docs/runbooks/2026-05-22_live_capital_go.md PF1 and by
scripts/run_pre_flights.py to produce a single ``allowed: bool +
readiness_score: float`` JSON line that the live-flip gate parses.

The underlying logic lives in
``production_readiness.deployment_gatekeeper.DeploymentGatekeeper``.

Usage::

    docker exec aaats-paper-crypto python -m scripts.evaluate_live_readiness

Exit codes:
    0  -> ``allowed: true``
    1  -> ``allowed: false`` (or any failure inside the gate)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from production_readiness.deployment_gatekeeper import DeploymentGatekeeper


def main() -> int:
    gate = DeploymentGatekeeper(data_dir="data")
    decision = gate.check_deployment_allowed()

    payload = asdict(decision)
    print(json.dumps(payload, indent=2))

    # Also emit a single line in the legacy "key: value" form that older
    # runbook greps (and scripts/run_pre_flights.py) match against.
    print(f"allowed: {str(decision.allowed).lower()}")
    print(f"readiness_score: {decision.readiness_score:.1f}")
    if decision.blockers:
        print("blockers:")
        for b in decision.blockers:
            print(f"  - {b}")

    return 0 if decision.allowed else 1


if __name__ == "__main__":
    sys.exit(main())
