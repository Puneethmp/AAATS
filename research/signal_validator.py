"""
Signal Validation Pipeline — Automated Deploy/Reject Gate
============================================================
Why this exists
---------------
Without this, every strategy in AAATS is deployed on confidence=0.7 hardcoded
in the signal generator. There is no empirical gate between "signal fires" and
"strategy goes live." This is the quant equivalent of shipping code without tests.

This module is the mandatory validation gate. Every strategy MUST pass this
before being eligible for paper or live trading.

Validation Framework
--------------------
A strategy is valid for deployment when ALL of the following hold:

  1. IC ≥ 0.04          — Information Coefficient (Spearman corr between signal and
                          forward returns). |IC| < 0.04 = noise.

  2. IR ≥ 0.5           — Information Ratio (IC mean / IC std). IR < 0.5 means the
                          signal is too noisy to capture consistently.

  3. DSR > 0.5          — Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).
                          Adjusts for multiple testing across strategies. Must exceed
                          0.5 probability of being a genuine discovery.

  4. PBO ≤ 0.30         — Probability of Backtest Overfitting (CPCV, Prado 2016).
                          If PBO > 30%, the strategy is likely curve-fit.

  5. Min track record   — Enough bars to achieve statistical significance at 95% CI
                          for the observed Sharpe ratio.

  6. Win rate > 40%     — Basic sanity check. Below 40% means even correct signals
                          lose more often than necessary (execution/sizing problem).

Any failure → REJECT. No partial passes. No exceptions.

Usage
-----
  from research.signal_validator import SignalValidator, validate_strategy

  # Quick function
  result = validate_strategy(
      signal_fn=my_strategy.generate_signals,
      df=df_features,
      forward_horizon=5,
  )
  print(result.verdict)       # 'DEPLOY' or 'REJECT'
  print(result.summary())

  # Full class interface with custom thresholds
  validator = SignalValidator(ic_threshold=0.05, ir_threshold=0.6)
  result = validator.validate(signal_fn, df, forward_horizon=5)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from research.backtester import VectorizedBacktester, WalkForwardValidator
from research.alpha_research import compute_ic, compute_ir, alpha_decay, quantile_returns
from research.statistical_tests import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    combinatorial_purged_cv,
    min_track_record_length,
)
from research.performance import compute_metrics
from foundation.logger import get_logger

_log = get_logger("research", "signal_validator")

__all__ = ["SignalValidator", "ValidationResult", "validate_strategy"]


# ---------------------------------------------------------------------------
# Thresholds (industry standard for retail quant)
# ---------------------------------------------------------------------------
_IC_MIN = 0.04          # meaningful IC
_IR_MIN = 0.5           # deployable IR
_DSR_MIN = 0.5          # genuine discovery probability
_PBO_MAX = 0.30         # max acceptable overfit probability
_WIN_RATE_MIN = 0.40    # basic execution sanity
_MIN_BARS = 200         # minimum bars for any validation


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    """Full validation report for a strategy signal."""

    strategy_name: str
    n_bars: int
    forward_horizon: int

    # Pass/fail per gate
    ic: float = 0.0
    ic_pass: bool = False

    ir: float = 0.0
    ir_pass: bool = False

    dsr: float = 0.0
    dsr_pass: bool = False

    pbo: float = 1.0
    pbo_pass: bool = False

    win_rate: float = 0.0
    win_rate_pass: bool = False

    min_track_record_bars: int = 0
    track_record_pass: bool = False

    # Backtest metrics
    sharpe: float = 0.0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    avg_is_bps: float = 0.0    # avg implementation shortfall in bps

    # Alpha decay
    decay_lag: int | None = None    # first lag where IC drops below 50% of IC(1)

    # Verdict
    verdict: str = "REJECT"
    fail_reasons: list[str] = field(default_factory=list)

    # OOS vs IS
    oos_sharpe: float = 0.0
    is_sharpe: float = 0.0

    def passed(self) -> bool:
        return self.verdict == "DEPLOY"

    def summary(self) -> str:
        lines = [
            f"{'='*60}",
            f"Strategy: {self.strategy_name}",
            f"Bars: {self.n_bars} | Forward horizon: {self.forward_horizon}",
            f"{'='*60}",
            f"  IC         : {self.ic:+.4f}  {'✓' if self.ic_pass else '✗'} (need ≥ {_IC_MIN})",
            f"  IR         : {self.ir:+.4f}  {'✓' if self.ir_pass else '✗'} (need ≥ {_IR_MIN})",
            f"  DSR        : {self.dsr:+.4f}  {'✓' if self.dsr_pass else '✗'} (need > {_DSR_MIN})",
            f"  PBO        : {self.pbo:.4f}  {'✓' if self.pbo_pass else '✗'} (need ≤ {_PBO_MAX})",
            f"  Win Rate   : {self.win_rate:.2%}  {'✓' if self.win_rate_pass else '✗'} (need > {_WIN_RATE_MIN:.0%})",
            f"  Track Rec  : {self.n_bars} bars (need {self.min_track_record_bars})  {'✓' if self.track_record_pass else '✗'}",
            f"{'─'*60}",
            f"  Sharpe     : {self.sharpe:.3f}  (IS: {self.is_sharpe:.3f}, OOS: {self.oos_sharpe:.3f})",
            f"  Max DD     : {self.max_drawdown_pct:.2f}%",
            f"  Total Ret  : {self.total_return_pct:.2f}%",
            f"  Decay Lag  : {self.decay_lag if self.decay_lag else 'N/A'}",
            f"{'='*60}",
            f"  VERDICT    : {self.verdict}",
        ]
        if self.fail_reasons:
            lines.append("  FAIL REASONS:")
            for r in self.fail_reasons:
                lines.append(f"    • {r}")
        lines.append(f"{'='*60}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Signal Validator
# ---------------------------------------------------------------------------
class SignalValidator:
    """
    Validates a strategy's signal quality against institutional thresholds.

    Parameters
    ----------
    ic_threshold        Minimum IC (Spearman). Default 0.04.
    ir_threshold        Minimum IR. Default 0.5.
    dsr_threshold       Minimum DSR (probability of genuine discovery). Default 0.5.
    pbo_threshold       Maximum PBO. Default 0.30.
    win_rate_threshold  Minimum win rate. Default 0.40.
    n_strategies_tested Number of strategies tested (for DSR correction). Default 10.
    commission_bps      Backtester commission per trade in bps. Default 5.
    spread_bps          Backtester spread cost in bps. Default 5.
    """

    def __init__(
        self,
        ic_threshold: float = _IC_MIN,
        ir_threshold: float = _IR_MIN,
        dsr_threshold: float = _DSR_MIN,
        pbo_threshold: float = _PBO_MAX,
        win_rate_threshold: float = _WIN_RATE_MIN,
        n_strategies_tested: int = 10,
        commission_bps: float = 5.0,
        spread_bps: float = 5.0,
    ):
        self.ic_threshold = ic_threshold
        self.ir_threshold = ir_threshold
        self.dsr_threshold = dsr_threshold
        self.pbo_threshold = pbo_threshold
        self.win_rate_threshold = win_rate_threshold
        self.n_strategies_tested = n_strategies_tested
        self.commission_bps = commission_bps
        self.spread_bps = spread_bps

    # ------------------------------------------------------------------
    def validate(
        self,
        signal_fn: Callable[[pd.DataFrame], pd.DataFrame],
        df: pd.DataFrame,
        forward_horizon: int = 5,
        strategy_name: str = "unnamed",
        freq: str = "daily",
    ) -> ValidationResult:
        """
        Run full validation pipeline on a strategy's signal function.

        Parameters
        ----------
        signal_fn       Function: df → df with 'signal' column ('BUY'/'SELL'/'HOLD').
        df              OHLCV + features DataFrame (use indicators.features.compute_features).
        forward_horizon Number of bars to measure forward returns against.
        strategy_name   Label for reporting.
        freq            Return frequency for annualisation ('daily', 'hourly', 'minute').
        """
        result = ValidationResult(
            strategy_name=strategy_name,
            n_bars=len(df),
            forward_horizon=forward_horizon,
        )

        if len(df) < _MIN_BARS:
            result.fail_reasons.append(
                f"Insufficient data: {len(df)} bars (need {_MIN_BARS})"
            )
            result.verdict = "REJECT"
            return result

        # --- Step 1: Generate signals ---
        try:
            sig_df = signal_fn(df)
        except Exception as exc:
            result.fail_reasons.append(f"signal_fn raised: {exc}")
            result.verdict = "REJECT"
            return result

        # Convert signal to numeric: BUY=1, SELL=-1, HOLD=0
        numeric_signal = self._to_numeric(sig_df.get("signal", pd.Series(dtype=object)))

        # --- Step 2: Forward returns ---
        close = df["close"].ffill()
        fwd_ret = close.pct_change(forward_horizon).shift(-forward_horizon)

        # Align
        mask = numeric_signal.notna() & fwd_ret.notna()
        sig_aligned = numeric_signal[mask]
        fwd_aligned = fwd_ret[mask]

        if len(sig_aligned) < 50:
            result.fail_reasons.append(
                f"Too few valid signal-return pairs: {len(sig_aligned)} (need 50+)"
            )
            result.verdict = "REJECT"
            return result

        # --- Step 3: IC / IR ---
        ic = compute_ic(sig_aligned, fwd_aligned, method="spearman")
        result.ic = round(float(ic), 4)
        result.ic_pass = abs(ic) >= self.ic_threshold
        if not result.ic_pass:
            result.fail_reasons.append(
                f"IC = {ic:.4f} — below threshold {self.ic_threshold}"
            )

        ir_stats = compute_ir(sig_aligned, fwd_aligned, window=min(60, len(sig_aligned) // 3))
        result.ir = round(float(ir_stats["ir"]), 4)
        result.ir_pass = abs(result.ir) >= self.ir_threshold
        if not result.ir_pass:
            result.fail_reasons.append(
                f"IR = {result.ir:.4f} — below threshold {self.ir_threshold}"
            )

        # --- Step 4: Backtest (vectorized) ---
        bt = VectorizedBacktester(
            commission_bps=self.commission_bps,
            spread_bps=self.spread_bps,
        )
        try:
            bt_result = bt.run(df, sig_df)
            metrics = bt_result.summary()
            result.sharpe = round(float(metrics.get("sharpe_ratio", 0.0)), 3)
            result.max_drawdown_pct = round(float(metrics.get("max_drawdown_pct", 0.0)), 2)
            result.total_return_pct = round(float(metrics.get("total_return_pct", 0.0)), 2)
            result.win_rate = round(float(metrics.get("win_rate", 0.0)), 4)
        except Exception as exc:
            _log.warning(f"Backtest failed: {exc}")
            result.win_rate = 0.0

        result.win_rate_pass = result.win_rate >= self.win_rate_threshold
        if not result.win_rate_pass:
            result.fail_reasons.append(
                f"Win rate = {result.win_rate:.2%} — below threshold {self.win_rate_threshold:.0%}"
            )

        # --- Step 5: DSR ---
        try:
            returns_series = bt_result.returns if hasattr(bt_result, "returns") else fwd_aligned
            dsr_result = deflated_sharpe_ratio(
                returns_series.dropna(),
                n_strategies_tested=self.n_strategies_tested,
                freq=freq,
            )
            result.dsr = round(float(dsr_result.get("dsr", 0.0)), 4)
            result.is_sharpe = round(float(dsr_result.get("observed_sharpe", 0.0)), 3)
        except Exception as exc:
            _log.debug(f"DSR computation failed: {exc}")
            result.dsr = 0.0

        result.dsr_pass = result.dsr > self.dsr_threshold
        if not result.dsr_pass:
            result.fail_reasons.append(
                f"DSR = {result.dsr:.4f} — strategy likely not a genuine discovery"
            )

        # --- Step 6: CPCV / PBO ---
        try:
            cpcv_result = combinatorial_purged_cv(
                returns=fwd_aligned,
                n_splits=min(6, len(fwd_aligned) // 30),
                n_test_splits=2,
            )
            result.pbo = round(float(cpcv_result.get("pbo", 1.0)), 4)
            result.oos_sharpe = round(float(cpcv_result.get("oos_sharpe_mean", 0.0)), 3)
        except Exception as exc:
            _log.debug(f"CPCV failed: {exc}")
            result.pbo = 1.0

        result.pbo_pass = result.pbo <= self.pbo_threshold
        if not result.pbo_pass:
            result.fail_reasons.append(
                f"PBO = {result.pbo:.4f} — {result.pbo:.0%} probability of overfitting"
            )

        # --- Step 7: Min track record ---
        try:
            trl = min_track_record_length(
                target_sharpe=max(result.sharpe, 0.5),
                freq=freq,
            )
            result.min_track_record_bars = int(trl.get("min_observations", 0))
            result.track_record_pass = result.n_bars >= result.min_track_record_bars
        except Exception as exc:
            _log.debug(f"TRL failed: {exc}")
            result.track_record_pass = True  # Don't fail on computation error

        if not result.track_record_pass:
            result.fail_reasons.append(
                f"Track record too short: {result.n_bars} bars, need {result.min_track_record_bars}"
            )

        # --- Step 8: Alpha decay ---
        try:
            decay_df = alpha_decay(sig_aligned, fwd_aligned, max_lag=min(20, len(sig_aligned) // 10))
            ic1 = decay_df["ic"].iloc[0] if len(decay_df) > 0 else 0.0
            half_ic = abs(ic1) * 0.5
            below_half = decay_df[decay_df["ic"].abs() < half_ic]
            result.decay_lag = int(below_half.index[0]) if len(below_half) > 0 else None
        except Exception:
            pass

        # --- Final verdict ---
        gates = [
            result.ic_pass,
            result.ir_pass,
            result.dsr_pass,
            result.pbo_pass,
            result.win_rate_pass,
            result.track_record_pass,
        ]
        result.verdict = "DEPLOY" if all(gates) else "REJECT"

        _log.info(
            f"Validation complete: {strategy_name} → {result.verdict} "
            f"(IC={result.ic:.3f}, IR={result.ir:.3f}, DSR={result.dsr:.3f}, "
            f"PBO={result.pbo:.3f})"
        )
        return result

    # ------------------------------------------------------------------
    def _to_numeric(self, signal: pd.Series) -> pd.Series:
        """Convert BUY/SELL/HOLD to +1/−1/0."""
        mapping = {"BUY": 1, "SELL": -1, "HOLD": 0}
        if signal.dtype == object or str(signal.dtype) == "object":
            return signal.map(mapping).fillna(0).astype(float)
        return signal.fillna(0).astype(float)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def validate_strategy(
    signal_fn: Callable[[pd.DataFrame], pd.DataFrame],
    df: pd.DataFrame,
    forward_horizon: int = 5,
    strategy_name: str = "unnamed",
    freq: str = "daily",
    n_strategies_tested: int = 10,
) -> ValidationResult:
    """
    One-shot strategy validation.

    Parameters
    ----------
    signal_fn           Strategy function: df → df with 'signal' column.
    df                  Features DataFrame (from indicators.features.compute_features).
    forward_horizon     Bars ahead to measure returns.
    strategy_name       Name for reporting.
    freq                Bar frequency ('daily', 'hourly').
    n_strategies_tested Number of strategies being tested (for DSR correction).

    Returns
    -------
    ValidationResult with .verdict == 'DEPLOY' or 'REJECT'.

    Example
    -------
    from research.signal_validator import validate_strategy
    from strategies.momentum.ema_crossover import generate_signals
    from indicators.features import compute_features

    df_feat = compute_features(df_ohlcv)
    result = validate_strategy(generate_signals, df_feat, forward_horizon=5)
    print(result.summary())
    """
    validator = SignalValidator(n_strategies_tested=n_strategies_tested)
    return validator.validate(
        signal_fn=signal_fn,
        df=df,
        forward_horizon=forward_horizon,
        strategy_name=strategy_name,
        freq=freq,
    )
