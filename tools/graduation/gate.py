"""Graduation gate — research→live promotion criteria for AAATS strategies.

A strategy is first validated in a NautilusTrader backtest, which produces a
flat ``metrics`` dict. This module decides whether that strategy has earned the
right to receive live capital. It does so by evaluating SEVEN criteria
(G1..G7), every one of which is computed on OUT-OF-SAMPLE data only — the gate
never inspects in-sample performance except to measure degradation (G6).

The gate is intentionally all-or-nothing: a strategy graduates only if it clears
every criterion. A single failure keeps it paper-only and the returned
``GateResult.failures`` names exactly which criteria failed and why, so the
operator knows precisely what to fix before re-running.

Criteria
--------
G1  net PnL after realistic fees > 0
G2  Sharpe ratio >= 1.0
G3  max drawdown <= 20% (absolute fraction <= 0.20)
G4  closed trade count >= 30        (statistical-significance floor)
G5  profit factor >= 1.3
G6  OOS/IS degradation: OOS Sharpe >= 0.5 * in-sample Sharpe
G7  maker-fill robustness: net PnL > 0 when prob_fill_on_limit drops to 0.5

This module is pure standard library (plus typing) — no third-party deps — so it
can run in any environment, including the box, without an install step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class GateThresholds:
    """The seven thresholds. Defaults are the canonical AAATS values.

    Deliberately conventional; tune once real graduations accumulate.
    """

    min_pnl: float = 0.0  # G1: net PnL after fees must exceed this
    min_sharpe: float = 1.0  # G2: OOS Sharpe floor
    max_drawdown: float = 0.20  # G3: max abs drawdown fraction allowed
    min_trades: int = 30  # G4: closed-trade significance floor
    min_profit_factor: float = 1.3  # G5: gross profit / gross loss floor
    min_oos_is_ratio: float = 0.5  # G6: OOS Sharpe / IS Sharpe floor
    maker_robustness_min_pnl: float = 0.0  # G7: net PnL floor at fill prob 0.5


@dataclass
class GateResult:
    """Verdict plus a full per-criterion breakdown."""

    passed: bool
    failures: List[str] = field(default_factory=list)
    # G1..G7 -> {"passed": bool, "actual": Any, "threshold": Any, "detail": str}
    criteria: Dict[str, Dict[str, Any]] = field(default_factory=dict)


_MISSING = object()  # sentinel distinct from a legitimate None/0 metric value


def _record(
    criteria: Dict[str, Dict[str, Any]],
    failures: List[str],
    key: str,
    passed: bool,
    actual: Any,
    threshold: Any,
    detail: str,
) -> None:
    """Append one criterion's outcome to the breakdown and failure list."""
    criteria[key] = {
        "passed": passed,
        "actual": actual,
        "threshold": threshold,
        "detail": detail,
    }
    if not passed:
        failures.append(f"{key}: {detail}")


def evaluate_gate(
    metrics: Dict[str, Any], thresholds: GateThresholds = GateThresholds()
) -> GateResult:
    """Evaluate all seven graduation criteria against ``metrics``.

    Defensive by design: a missing metric key fails its criterion with the
    detail "metric missing" rather than raising.
    """
    criteria: Dict[str, Dict[str, Any]] = {}
    failures: List[str] = []

    def get(name: str) -> Any:
        return metrics.get(name, _MISSING)

    # --- G1: net PnL after fees > min_pnl --------------------------------
    pnl = get("net_pnl_usd")
    if pnl is _MISSING:
        _record(
            criteria, failures, "G1", False, None, thresholds.min_pnl, "metric missing"
        )
    else:
        ok = pnl > thresholds.min_pnl
        _record(
            criteria,
            failures,
            "G1",
            ok,
            pnl,
            thresholds.min_pnl,
            f"net PnL {pnl:.4f} {'>' if ok else '<='} {thresholds.min_pnl}",
        )

    # --- G2: OOS Sharpe >= min_sharpe ------------------------------------
    sharpe = get("sharpe")
    if sharpe is _MISSING:
        _record(
            criteria,
            failures,
            "G2",
            False,
            None,
            thresholds.min_sharpe,
            "metric missing",
        )
    else:
        ok = sharpe >= thresholds.min_sharpe
        _record(
            criteria,
            failures,
            "G2",
            ok,
            sharpe,
            thresholds.min_sharpe,
            f"Sharpe {sharpe:.4f} {'>=' if ok else '<'} {thresholds.min_sharpe}",
        )

    # --- G3: abs(max drawdown) <= max_drawdown ---------------------------
    dd = get("max_drawdown_pct")
    if dd is _MISSING:
        _record(
            criteria,
            failures,
            "G3",
            False,
            None,
            thresholds.max_drawdown,
            "metric missing",
        )
    else:
        actual_dd = abs(dd)  # accept signed or unsigned input
        ok = actual_dd <= thresholds.max_drawdown
        _record(
            criteria,
            failures,
            "G3",
            ok,
            actual_dd,
            thresholds.max_drawdown,
            f"drawdown {actual_dd:.4f} {'<=' if ok else '>'} {thresholds.max_drawdown}",
        )

    # --- G4: closed trade count >= min_trades ----------------------------
    n = get("n_trades")
    if n is _MISSING:
        _record(
            criteria,
            failures,
            "G4",
            False,
            None,
            thresholds.min_trades,
            "metric missing",
        )
    else:
        ok = n >= thresholds.min_trades
        _record(
            criteria,
            failures,
            "G4",
            ok,
            n,
            thresholds.min_trades,
            f"{n} trades {'>=' if ok else '<'} {thresholds.min_trades} (significance floor)",
        )

    # --- G5: profit factor >= min_profit_factor --------------------------
    pf = get("profit_factor")
    if pf is _MISSING:
        _record(
            criteria,
            failures,
            "G5",
            False,
            None,
            thresholds.min_profit_factor,
            "metric missing",
        )
    else:
        ok = pf >= thresholds.min_profit_factor
        _record(
            criteria,
            failures,
            "G5",
            ok,
            pf,
            thresholds.min_profit_factor,
            f"profit factor {pf:.4f} {'>=' if ok else '<'} {thresholds.min_profit_factor}",
        )

    # --- G6: OOS/IS degradation ------------------------------------------
    is_sharpe = get("in_sample_sharpe")
    oos_sharpe = get("oos_sharpe")
    if is_sharpe is _MISSING or oos_sharpe is _MISSING:
        _record(
            criteria,
            failures,
            "G6",
            False,
            None,
            thresholds.min_oos_is_ratio,
            "metric missing",
        )
    elif is_sharpe <= 0:
        # No positive in-sample edge to degrade from: pass only if OOS is
        # non-negative. Avoids dividing by / comparing against <=0 IS Sharpe.
        ok = oos_sharpe >= 0
        _record(
            criteria,
            failures,
            "G6",
            ok,
            oos_sharpe,
            0.0,
            f"IS Sharpe {is_sharpe:.4f} <= 0; OOS Sharpe {oos_sharpe:.4f} "
            f"{'>=' if ok else '<'} 0",
        )
    else:
        required = thresholds.min_oos_is_ratio * is_sharpe
        ok = oos_sharpe >= required
        _record(
            criteria,
            failures,
            "G6",
            ok,
            oos_sharpe,
            required,
            f"OOS Sharpe {oos_sharpe:.4f} {'>=' if ok else '<'} "
            f"{thresholds.min_oos_is_ratio}*IS({is_sharpe:.4f})={required:.4f}",
        )

    # --- G7: maker-fill robustness at prob_fill_on_limit=0.5 -------------
    pnl_05 = get("pnl_at_maker_0_5")
    if pnl_05 is _MISSING:
        _record(
            criteria,
            failures,
            "G7",
            False,
            None,
            thresholds.maker_robustness_min_pnl,
            "metric missing",
        )
    else:
        ok = pnl_05 > thresholds.maker_robustness_min_pnl
        _record(
            criteria,
            failures,
            "G7",
            ok,
            pnl_05,
            thresholds.maker_robustness_min_pnl,
            f"PnL@fill=0.5 {pnl_05:.4f} {'>' if ok else '<='} "
            f"{thresholds.maker_robustness_min_pnl}",
        )

    return GateResult(passed=len(failures) == 0, failures=failures, criteria=criteria)


def emit_report(
    strategy: str,
    metrics: Dict[str, Any],
    result: GateResult,
    out_dir: str = "data/graduation",
) -> str:
    """Write a JSON graduation report and return its path.

    The PASS report is the single artifact that authorizes a live-flip
    decision; the FAIL report documents exactly what blocked promotion.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{strategy}_{date.today().isoformat()}.json"
    payload = {
        "strategy": strategy,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS" if result.passed else "FAIL",
        "metrics": metrics,
        "criteria": result.criteria,
        "failures": result.failures,
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(path)


if __name__ == "__main__":
    # Self-test: one clearly-passing strategy and one clearly-failing one.
    passing = {
        "net_pnl_usd": 412.50,
        "sharpe": 1.62,
        "max_drawdown_pct": 0.11,
        "n_trades": 84,
        "profit_factor": 1.55,
        "in_sample_sharpe": 1.90,
        "oos_sharpe": 1.62,
        "pnl_at_maker_0_5": 210.0,
    }
    failing = {
        "net_pnl_usd": -55.0,  # G1 fail
        "sharpe": 0.40,  # G2 fail
        "max_drawdown_pct": 0.34,  # G3 fail
        "n_trades": 12,  # G4 fail (C6-style small sample)
        "profit_factor": 0.95,  # G5 fail
        "in_sample_sharpe": 8.41,  # huge IS edge...
        "oos_sharpe": -0.8,  # ...that evaporates OOS -> G6 fail
        # pnl_at_maker_0_5 deliberately omitted -> G7 "metric missing"
    }

    for name, m in (("SAMPLE_PASS", passing), ("SAMPLE_FAIL", failing)):
        res = evaluate_gate(m)
        print(f"\n=== {name}: {'PASS' if res.passed else 'FAIL'} ===")
        for gkey in sorted(res.criteria):
            c = res.criteria[gkey]
            mark = "ok " if c["passed"] else "XX "
            print(f"  {mark}{gkey}: {c['detail']}")
        if res.failures:
            print(f"  failures -> {res.failures}")
