"""
Stress testing engine for AAATS.

Simulates portfolio behavior under historical and hypothetical stress scenarios:
  - 2020 COVID crash (-35%)
  - 2022 Crypto bear (-70%)
  - 2008 Financial crisis (-50%)
  - Custom user-defined scenarios

Usage:
    from analytics.stress_tester import StressTester
    st = StressTester(capital=500_000.0)
    results = st.run_all_scenarios(open_positions)
    st.print_report(results)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("analytics", "stress_tester")

_SCENARIOS = {
    "covid_crash_2020": {"description": "COVID-19 crash (Feb-Mar 2020)", "market_drop": -0.35, "duration_days": 30, "recovery_days": 120},
    "crypto_bear_2022": {"description": "Crypto bear market 2022", "market_drop": -0.70, "duration_days": 180, "recovery_days": 400},
    "financial_crisis_2008": {"description": "2008 Global financial crisis", "market_drop": -0.50, "duration_days": 90, "recovery_days": 730},
    "india_flash_crash": {"description": "India market flash crash (-15%)", "market_drop": -0.15, "duration_days": 2, "recovery_days": 30},
    "mild_correction": {"description": "Normal market correction (-10%)", "market_drop": -0.10, "duration_days": 20, "recovery_days": 45},
    "extreme_stress": {"description": "Extreme scenario (-80%)", "market_drop": -0.80, "duration_days": 365, "recovery_days": 1460},
}


@dataclass
class StressResult:
    scenario: str
    description: str
    market_drop: float
    portfolio_loss: float
    portfolio_loss_pct: float
    time_to_recovery_days: int
    survivable: bool  # True if portfolio survives (doesn't go to zero)


class StressTester:
    """
    Tests portfolio resilience under stress scenarios.

    Args:
        capital:       Total portfolio capital.
        max_loss_pct:  Maximum acceptable loss before "not survivable" (default 50%).
    """

    def __init__(self, capital: float, max_loss_pct: float = 0.50) -> None:
        self._capital = capital
        self._max_loss = max_loss_pct

    def run_scenario(
        self,
        scenario_name: str,
        open_positions: list[dict],
        custom_drop: float | None = None,
    ) -> StressResult:
        """Run a single stress scenario. Returns result."""
        if scenario_name not in _SCENARIOS and custom_drop is None:
            raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(_SCENARIOS)}")

        sc = _SCENARIOS.get(scenario_name, {
            "description": f"Custom scenario {custom_drop:.0%} drop",
            "market_drop": custom_drop or -0.20,
            "duration_days": 30,
            "recovery_days": 90,
        })

        drop = sc["market_drop"]
        total_exposure = sum(p.get("entry_price", 0) * p.get("shares", 0) for p in open_positions)
        portfolio_loss = total_exposure * abs(drop)
        portfolio_loss_pct = portfolio_loss / max(self._capital, 1e-9)
        survivable = portfolio_loss_pct < self._max_loss

        _log.info(
            f"Stress test [{scenario_name}]: drop={drop:.0%} | "
            f"exposure={total_exposure:.0f} | loss={portfolio_loss:.0f} ({portfolio_loss_pct:.1%}) | "
            f"{'SURVIVABLE' if survivable else 'CATASTROPHIC'}"
        )

        return StressResult(
            scenario=scenario_name,
            description=sc["description"],
            market_drop=drop,
            portfolio_loss=round(portfolio_loss, 2),
            portfolio_loss_pct=round(portfolio_loss_pct, 4),
            time_to_recovery_days=sc["recovery_days"],
            survivable=survivable,
        )

    def run_all_scenarios(self, open_positions: list[dict]) -> list[StressResult]:
        """Run all built-in scenarios. Returns list of results."""
        results = []
        for name in _SCENARIOS:
            try:
                results.append(self.run_scenario(name, open_positions))
            except Exception as exc:
                _log.error(f"Stress test failed for {name}: {exc}")
        return results

    def print_report(self, results: list[StressResult]) -> None:
        """Print a formatted stress test report."""
        print("\n" + "=" * 60)
        print("STRESS TEST REPORT")
        print("=" * 60)
        for r in results:
            icon = "✅" if r.survivable else "🔴"
            print(f"\n{icon} {r.description}")
            print(f"   Market drop: {r.market_drop:.0%}")
            print(f"   Portfolio loss: {r.portfolio_loss:,.0f} ({r.portfolio_loss_pct:.1%})")
            print(f"   Recovery time: ~{r.time_to_recovery_days} days")
            print(f"   Outcome: {'SURVIVABLE' if r.survivable else 'CATASTROPHIC'}")
        print("\n" + "=" * 60)

    def save_report(self, results: list[StressResult], output_path: Path | None = None) -> Path:
        out = output_path or Path("reports/stress_test_report.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(r) for r in results], indent=2))
        return out
