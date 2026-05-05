"""
Backtest Runner — End-to-End Strategy Evaluation
=================================================
CLI-style script and importable function that wires the full backtest pipeline:
  Raw OHLCV → Feature Engineering → Strategy Signals → Backtest → Validation → Report

Usage (CLI)
-----------
  python -m research.run_backtest \\
      --strategy momentum.ema_crossover \\
      --data path/to/ohlcv.csv \\
      --horizon 5 \\
      --freq daily \\
      --output results/

Usage (Python)
--------------
  from research.run_backtest import run_backtest

  result = run_backtest(
      strategy_module="momentum.ema_crossover",
      df=df_ohlcv,
      forward_horizon=5,
      annualise_factor=252,
  )
  print(result["summary"])
  print(result["validation"].summary())

Supported strategy module paths
--------------------------------
  momentum.ema_crossover
  momentum.breakout
  momentum.relative_strength
  mean_reversion.rsi_exhaustion
  mean_reversion.zscore_reversion
  mean_reversion.vwap_reversion
  regime.adaptive_switcher
  volatility.atr_breakout
  <any strategy module in strategies/ with generate_signals(df, config) function>
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from indicators.features import compute_features, FeaturePipeline
from research.backtester import VectorizedBacktester, WalkForwardValidator
from research.performance import compute_metrics, performance_report, drawdown_analysis
from research.signal_validator import SignalValidator, ValidationResult
from research.tca import TCAAnalyzer, Order
from foundation.logger import get_logger

_log = get_logger("research", "run_backtest")

__all__ = ["run_backtest", "load_strategy", "BacktestReport"]


# ---------------------------------------------------------------------------
# BacktestReport
# ---------------------------------------------------------------------------
class BacktestReport:
    """Full backtest report combining backtest + validation + TCA."""

    def __init__(
        self,
        strategy_name: str,
        bt_result,
        validation: ValidationResult,
        perf: dict,
        tca_summary: dict,
        df_with_signals: pd.DataFrame,
        walk_forward: dict | None = None,
    ):
        self.strategy_name = strategy_name
        self.bt_result = bt_result
        self.validation = validation
        self.perf = perf
        self.tca_summary = tca_summary
        self.df_with_signals = df_with_signals
        self.walk_forward = walk_forward

    def print_report(self) -> None:
        print("\n" + "=" * 70)
        print(f"  BACKTEST REPORT: {self.strategy_name}")
        print("=" * 70)

        # Backtest metrics
        metrics = self.perf.get("metrics", {})
        print(f"\n  PERFORMANCE METRICS")
        print(f"  {'─'*40}")
        print(f"  Sharpe Ratio     : {metrics.get('sharpe_ratio', 0):.3f}")
        print(f"  Sortino Ratio    : {metrics.get('sortino_ratio', 0):.3f}")
        print(f"  Max Drawdown     : {metrics.get('max_drawdown_pct', 0):.2f}%")
        print(f"  Total Return     : {metrics.get('total_return_pct', 0):.2f}%")
        print(f"  Ann. Volatility  : {metrics.get('ann_volatility_pct', 0):.2f}%")
        print(f"  Win Rate         : {metrics.get('win_rate', 0):.2%}")
        print(f"  Profit Factor    : {metrics.get('profit_factor', 0):.3f}")
        print(f"  Total Trades     : {metrics.get('total_trades', 0)}")

        # TCA
        if self.tca_summary:
            print(f"\n  TRANSACTION COST ANALYSIS")
            print(f"  {'─'*40}")
            print(f"  Avg IS (bps)     : {self.tca_summary.get('avg_is_bps', 0):.2f}")
            print(f"  Total Cost ($)   : {self.tca_summary.get('total_cost_usd', 0):.2f}")
            print(f"  Avg Impact (bps) : {self.tca_summary.get('avg_impact_bps', 0):.2f}")

        # Walk-forward
        if self.walk_forward:
            print(f"\n  WALK-FORWARD ANALYSIS")
            print(f"  {'─'*40}")
            print(f"  OOS Sharpe       : {self.walk_forward.get('oos_sharpe', 0):.3f}")
            print(f"  IS Sharpe        : {self.walk_forward.get('is_sharpe', 0):.3f}")
            print(f"  IS/OOS Ratio     : {self.walk_forward.get('is_oos_ratio', 0):.2f}")

        # Validation
        print(f"\n  SIGNAL VALIDATION")
        print(f"  {'─'*40}")
        print(self.validation.summary())

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "validation": {
                "verdict": self.validation.verdict,
                "ic": self.validation.ic,
                "ir": self.validation.ir,
                "dsr": self.validation.dsr,
                "pbo": self.validation.pbo,
                "win_rate": self.validation.win_rate,
            },
            "performance": self.perf.get("metrics", {}),
            "tca": self.tca_summary,
            "walk_forward": self.walk_forward or {},
        }

    def to_json(self, path: str | Path) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Strategy loader
# ---------------------------------------------------------------------------

def load_strategy(module_path: str) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """
    Load a strategy's generate_signals function by module path.

    Examples
    --------
    fn = load_strategy("momentum.ema_crossover")
    fn = load_strategy("mean_reversion.rsi_exhaustion")
    fn = load_strategy("regime.adaptive_switcher")
    """
    # Try full path: strategies.<module>
    for prefix in ["strategies.", ""]:
        full_path = f"{prefix}{module_path}"
        try:
            mod = importlib.import_module(full_path)
            if hasattr(mod, "generate_signals"):
                _log.info(f"Loaded strategy from: {full_path}")
                return mod.generate_signals
        except ImportError:
            continue

    raise ImportError(
        f"Could not find generate_signals in '{module_path}'. "
        "Try: momentum.ema_crossover, mean_reversion.rsi_exhaustion, etc."
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_backtest(
    strategy_module: str | Callable,
    df: pd.DataFrame,
    forward_horizon: int = 5,
    annualise_factor: float = 252.0,
    freq: str = "daily",
    commission_bps: float = 5.0,
    spread_bps: float = 5.0,
    run_walk_forward: bool = True,
    run_validation: bool = True,
    n_strategies_tested: int = 10,
    strategy_config: dict | None = None,
    output_dir: str | Path | None = None,
) -> BacktestReport:
    """
    End-to-end backtest pipeline.

    Parameters
    ----------
    strategy_module     Strategy module path string OR callable(df) → df.
    df                  Raw OHLCV DataFrame (open, high, low, close, volume).
                        Will automatically compute features if not already present.
    forward_horizon     Bars ahead to measure signal quality.
    annualise_factor    Bars/year for volatility annualisation.
    freq                Bar frequency for metric computation ('daily', 'hourly').
    commission_bps      Round-trip commission in bps.
    spread_bps          Bid-ask spread in bps.
    run_walk_forward    Whether to run walk-forward validation (slower).
    run_validation      Whether to run signal validation (IC/IR/DSR/PBO).
    n_strategies_tested Number of strategies tested (for DSR Bonferroni correction).
    strategy_config     Config dict passed to generate_signals(df, config).
    output_dir          If set, saves JSON report here.

    Returns
    -------
    BacktestReport with full results.
    """
    # --- Load strategy ---
    if callable(strategy_module):
        signal_fn = strategy_module
        strategy_name = getattr(strategy_module, "__name__", "custom")
    else:
        signal_fn = load_strategy(strategy_module)
        strategy_name = str(strategy_module)

    _log.info(f"Running backtest: {strategy_name}")

    # --- Feature engineering ---
    feature_cols = {"ema_50", "ema_200", "rsi_14", "atr_14"}
    if not feature_cols.issubset(set(df.columns)):
        _log.info("Computing features from raw OHLCV...")
        df = compute_features(df, annualise_factor=annualise_factor)

    # --- Generate signals ---
    def _signal_fn_wrapped(df_: pd.DataFrame) -> pd.DataFrame:
        return signal_fn(df_, strategy_config)

    sig_df = _signal_fn_wrapped(df)

    # --- Vectorized backtest ---
    bt = VectorizedBacktester(
        commission_bps=commission_bps,
        spread_bps=spread_bps,
        annualise_factor=annualise_factor,
    )
    bt_result = bt.run(df, sig_df)
    bt_summary = bt_result.summary()

    # --- Performance metrics ---
    returns = bt_result.returns.dropna()
    perf = performance_report(returns, freq=freq)

    # --- Walk-forward ---
    wf_dict: dict | None = None
    if run_walk_forward and len(df) >= 300:
        try:
            wfv = WalkForwardValidator(
                n_folds=5,
                signal_fn=lambda d: signal_fn(d, strategy_config),
            )
            wf_result = wfv.run(df)
            wf_summary = wf_result.summary()
            oos_sharpe = float(wf_summary.get("oos_sharpe_ratio", 0.0))
            is_sharpe = float(bt_summary.get("sharpe_ratio", 0.0))
            wf_dict = {
                "oos_sharpe": round(oos_sharpe, 3),
                "is_sharpe": round(is_sharpe, 3),
                "is_oos_ratio": round(is_sharpe / max(abs(oos_sharpe), 0.01), 2),
                "degradation_pct": round(
                    (is_sharpe - oos_sharpe) / max(abs(is_sharpe), 0.01) * 100, 1
                ),
            }
        except Exception as exc:
            _log.warning(f"Walk-forward failed: {exc}")

    # --- TCA summary ---
    tca_summary: dict = {}
    try:
        trade_log = bt_result.trade_log
        if trade_log:
            analyzer = TCAAnalyzer()
            orders = []
            for t in trade_log:
                orders.append(Order(
                    symbol=t.get("symbol", "UNKNOWN"),
                    side=t.get("side", "buy"),
                    quantity=float(t.get("quantity", 1.0)),
                    decision_price=float(t.get("entry_price", 0.0)),
                    execution_price=float(t.get("entry_price", 0.0)),
                ))
            tca_df = pd.DataFrame([
                analyzer.analyze(o).to_dict() for o in orders
            ])
            if not tca_df.empty:
                tca_summary = {
                    "avg_is_bps": round(float(tca_df["implementation_shortfall_bps"].mean()), 2),
                    "total_cost_usd": round(float(tca_df["total_cost_usd"].sum()), 2),
                    "avg_impact_bps": round(
                        float(tca_df["estimated_market_impact_bps"].mean())
                        if "estimated_market_impact_bps" in tca_df else 0.0, 2
                    ),
                    "avg_spread_bps": round(
                        float(tca_df["estimated_spread_cost_bps"].mean())
                        if "estimated_spread_cost_bps" in tca_df else 0.0, 2
                    ),
                }
    except Exception as exc:
        _log.debug(f"TCA summary failed: {exc}")

    # --- Signal validation ---
    validation: ValidationResult
    if run_validation:
        validator = SignalValidator(
            commission_bps=commission_bps,
            spread_bps=spread_bps,
            n_strategies_tested=n_strategies_tested,
        )
        validation = validator.validate(
            signal_fn=_signal_fn_wrapped,
            df=df,
            forward_horizon=forward_horizon,
            strategy_name=strategy_name,
            freq=freq,
        )
    else:
        from research.signal_validator import ValidationResult
        validation = ValidationResult(
            strategy_name=strategy_name,
            n_bars=len(df),
            forward_horizon=forward_horizon,
            verdict="SKIPPED",
        )

    # --- Build report ---
    report = BacktestReport(
        strategy_name=strategy_name,
        bt_result=bt_result,
        validation=validation,
        perf=perf,
        tca_summary=tca_summary,
        df_with_signals=sig_df,
        walk_forward=wf_dict,
    )

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        fname = f"{strategy_name.replace('.', '_')}_backtest.json"
        report.to_json(out / fname)
        _log.info(f"Report saved to {out / fname}")

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="AAATS Strategy Backtester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--strategy", required=True,
                        help="Strategy module path (e.g. momentum.ema_crossover)")
    parser.add_argument("--data", required=True,
                        help="Path to OHLCV CSV file")
    parser.add_argument("--horizon", type=int, default=5,
                        help="Forward return horizon in bars (default: 5)")
    parser.add_argument("--freq", default="daily",
                        help="Bar frequency: daily, hourly (default: daily)")
    parser.add_argument("--commission", type=float, default=5.0,
                        help="Commission in bps round-trip (default: 5)")
    parser.add_argument("--spread", type=float, default=5.0,
                        help="Spread cost in bps (default: 5)")
    parser.add_argument("--no-validation", action="store_true",
                        help="Skip signal validation (faster)")
    parser.add_argument("--no-walk-forward", action="store_true",
                        help="Skip walk-forward CV (faster)")
    parser.add_argument("--output", default=None,
                        help="Directory to save JSON results")
    args = parser.parse_args()

    # Load data
    df = pd.read_csv(args.data, parse_dates=True, index_col=0)
    df.columns = [c.lower() for c in df.columns]

    report = run_backtest(
        strategy_module=args.strategy,
        df=df,
        forward_horizon=args.horizon,
        freq=args.freq,
        commission_bps=args.commission,
        spread_bps=args.spread,
        run_validation=not args.no_validation,
        run_walk_forward=not args.no_walk_forward,
        output_dir=args.output,
    )
    report.print_report()
    sys.exit(0 if report.validation.passed() else 1)


if __name__ == "__main__":
    _cli()
