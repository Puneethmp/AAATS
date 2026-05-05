"""
Vectorized Backtesting Engine with Walk-Forward Cross-Validation
================================================================
Why this exists
---------------
Paper-trading a strategy you have not backtested is gambling, not quant.
This module provides:

  1. VectorizedBacktester   — fast, position-based backtesting over a DataFrame
                              of OHLCV + signals. Handles transaction costs
                              (spread, commission, market impact), position
                              sizing, and benchmark comparison.

  2. WalkForwardValidator   — splits the time series into expanding or rolling
                              in-sample / out-of-sample windows and runs the
                              strategy on each fold, producing a realistic
                              out-of-sample equity curve. Prevents look-ahead
                              bias and overfitting on a single in-sample window.

  3. BacktestResult          — dataclass holding the full equity curve, trade
                              log, drawdown series, and summary statistics.

Transaction cost model
----------------------
  total_cost_bps = spread_bps/2 + commission_bps + market_impact_bps

Market impact uses the simplified square-root model:
  impact_bps = eta * sigma * sqrt(participation_rate) * 10_000

where eta ≈ 0.1 (typical for liquid markets).

Usage
-----
  import pandas as pd
  from research.backtester import VectorizedBacktester, WalkForwardValidator

  # df must have columns: open, high, low, close, volume
  # and a 'signal' column in {-1, 0, 1}
  bt = VectorizedBacktester(commission_bps=5, spread_bps=2)
  result = bt.run(df, signal_col='signal', initial_capital=100_000)
  print(result.summary())

  wf = WalkForwardValidator(n_folds=5, train_ratio=0.6, mode='expanding')
  oos_result = wf.run(df, signal_col='signal', backtester=bt)
  print(oos_result.summary())
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np
import pandas as pd

__all__ = [
    "VectorizedBacktester",
    "WalkForwardValidator",
    "BacktestResult",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ANNUALISATION = {
    "1min": 252 * 390,
    "5min": 252 * 78,
    "15min": 252 * 26,
    "1h": 252 * 6.5,
    "1Hour": 252 * 6.5,
    "1d": 252,
    "1Day": 252,
    "1w": 52,
}
_DEFAULT_ANN = 252  # fallback


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    equity: pd.Series                  # portfolio value over time
    returns: pd.Series                 # period returns
    positions: pd.Series               # position sizes (fraction of capital)
    trade_log: pd.DataFrame            # one row per trade
    benchmark_equity: pd.Series | None = None
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    def summary(self, freq: str = "1d") -> dict:
        """Return a dictionary of key performance statistics."""
        ann = ANNUALISATION.get(freq, _DEFAULT_ANN)
        r = self.returns.dropna()
        total_return = (self.equity.iloc[-1] / self.equity.iloc[0]) - 1
        ann_return = (1 + total_return) ** (ann / max(len(r), 1)) - 1
        vol = r.std() * np.sqrt(ann)
        sharpe = ann_return / vol if vol > 0 else 0.0

        downside = r[r < 0].std() * np.sqrt(ann)
        sortino = ann_return / downside if downside > 0 else 0.0

        # Drawdown
        roll_max = self.equity.cummax()
        dd = (self.equity - roll_max) / roll_max
        max_dd = dd.min()
        calmar = ann_return / abs(max_dd) if max_dd < 0 else 0.0

        # Drawdown duration
        in_dd = dd < 0
        dd_duration = 0
        max_dd_dur = 0
        for v in in_dd:
            dd_duration = dd_duration + 1 if v else 0
            max_dd_dur = max(max_dd_dur, dd_duration)

        # Trade stats
        tl = self.trade_log
        n_trades = len(tl)
        if n_trades > 0 and "pnl" in tl.columns:
            wins = (tl["pnl"] > 0).sum()
            win_rate = wins / n_trades
            avg_win = tl.loc[tl["pnl"] > 0, "pnl"].mean() if wins > 0 else 0.0
            avg_loss = tl.loc[tl["pnl"] <= 0, "pnl"].mean() if (n_trades - wins) > 0 else 0.0
            profit_factor = (
                abs(tl.loc[tl["pnl"] > 0, "pnl"].sum()) /
                max(abs(tl.loc[tl["pnl"] <= 0, "pnl"].sum()), 1e-9)
            )
        else:
            win_rate = avg_win = avg_loss = profit_factor = float("nan")

        # Benchmark comparison
        alpha = beta = info_ratio = float("nan")
        if self.benchmark_equity is not None:
            bm_r = self.benchmark_equity.pct_change().dropna()
            aligned = pd.concat([r, bm_r], axis=1, join="inner")
            aligned.columns = ["strat", "bench"]
            if len(aligned) > 10:
                cov = np.cov(aligned["strat"], aligned["bench"])
                beta = cov[0, 1] / max(cov[1, 1], 1e-12)
                alpha = ann_return - beta * (
                    (1 + aligned["bench"].mean()) ** ann - 1
                )
                active = aligned["strat"] - aligned["bench"]
                info_ratio = (
                    active.mean() / active.std() * np.sqrt(ann)
                    if active.std() > 0 else 0.0
                )

        return {
            "total_return_pct": round(total_return * 100, 2),
            "ann_return_pct": round(ann_return * 100, 2),
            "ann_volatility_pct": round(vol * 100, 2),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "calmar_ratio": round(calmar, 3),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "max_drawdown_days": max_dd_dur,
            "n_trades": n_trades,
            "win_rate_pct": round(win_rate * 100, 2) if not np.isnan(win_rate) else float("nan"),
            "avg_win": round(avg_win, 2) if not np.isnan(avg_win) else float("nan"),
            "avg_loss": round(avg_loss, 2) if not np.isnan(avg_loss) else float("nan"),
            "profit_factor": round(profit_factor, 3) if not np.isnan(profit_factor) else float("nan"),
            "alpha": round(alpha, 4) if not np.isnan(alpha) else float("nan"),
            "beta": round(beta, 3) if not np.isnan(beta) else float("nan"),
            "information_ratio": round(info_ratio, 3) if not np.isnan(info_ratio) else float("nan"),
        }

    def drawdown_series(self) -> pd.Series:
        roll_max = self.equity.cummax()
        return (self.equity - roll_max) / roll_max

    def rolling_sharpe(self, window: int = 60, freq: str = "1d") -> pd.Series:
        ann = ANNUALISATION.get(freq, _DEFAULT_ANN)
        r = self.returns.rolling(window)
        return r.mean() / r.std() * np.sqrt(ann)


# ---------------------------------------------------------------------------
# VectorizedBacktester
# ---------------------------------------------------------------------------
class VectorizedBacktester:
    """
    Vectorized position-based backtester.

    Parameters
    ----------
    commission_bps   One-way commission in basis points (e.g. 5 = 0.05%).
    spread_bps       Half-spread in bps paid on each trade (cost = spread/2 × 2 sides).
    market_impact    Enable square-root market impact model.
    impact_eta       Market impact coefficient (default 0.1).
    slippage_bps     Fixed slippage per trade in bps (used if market_impact=False).
    max_position     Maximum position size as fraction of capital (default 1.0 = 100%).
    """

    def __init__(
        self,
        commission_bps: float = 5.0,
        spread_bps: float = 2.0,
        market_impact: bool = True,
        impact_eta: float = 0.1,
        slippage_bps: float = 0.0,
        max_position: float = 1.0,
    ):
        self.commission_bps = commission_bps
        self.spread_bps = spread_bps
        self.market_impact = market_impact
        self.impact_eta = impact_eta
        self.slippage_bps = slippage_bps
        self.max_position = max_position

    # ------------------------------------------------------------------
    def _cost_bps(
        self, sigma: float, participation: float = 0.01
    ) -> float:
        """Total one-way transaction cost in bps."""
        impact = 0.0
        if self.market_impact and sigma > 0:
            impact = self.impact_eta * sigma * np.sqrt(participation) * 1e4
        return self.commission_bps + self.spread_bps / 2 + impact + self.slippage_bps

    # ------------------------------------------------------------------
    def run(
        self,
        data: pd.DataFrame,
        signal_col: str = "signal",
        size_col: str | None = None,
        benchmark_col: str | None = None,
        initial_capital: float = 100_000.0,
        freq: str = "1d",
    ) -> BacktestResult:
        """
        Run the backtest.

        Parameters
        ----------
        data          DataFrame with at minimum: close, and a signal column.
                      Optional: open, high, low, volume for cost modelling.
        signal_col    Column name for the signal. Values in {-1, 0, 1} or
                      continuous in [-1, 1] for fractional sizing.
        size_col      Optional column with explicit position sizes [0,1].
                      If None, signal magnitude is used.
        benchmark_col Column of benchmark prices (e.g. index level).
        initial_capital Starting capital.
        freq          Bar frequency for annualisation.
        """
        df = data.copy()
        required = {"close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if signal_col not in df.columns:
            raise ValueError(f"signal column '{signal_col}' not in DataFrame")

        # ---- positions (forward-filled, shifted to avoid look-ahead) ------
        raw_signal = df[signal_col].clip(-1, 1)
        if size_col and size_col in df.columns:
            position_size = df[size_col].clip(0, self.max_position)
            positions = raw_signal.apply(np.sign) * position_size
        else:
            positions = raw_signal * self.max_position

        # Shift by 1: trade executes on NEXT bar open (no look-ahead)
        positions = positions.shift(1).fillna(0)

        # ---- returns -------------------------------------------------------
        close = df["close"]
        price_ret = close.pct_change().fillna(0)

        # Daily rolling volatility for impact model (20-bar)
        sigma = price_ret.rolling(20, min_periods=5).std().fillna(price_ret.std())

        # ---- transaction costs --------------------------------------------
        delta_pos = positions.diff().fillna(positions)
        trades_mask = delta_pos.abs() > 1e-6

        # Participation rate: assume we trade 1% of ADV when volume available
        participation = pd.Series(0.01, index=df.index)
        if "volume" in df.columns and (df["volume"] > 0).any():
            # Estimate capital traded vs. ADV
            adv = df["volume"].rolling(20, min_periods=5).mean().fillna(df["volume"])
            cap_traded = delta_pos.abs() * initial_capital / close.replace(0, np.nan)
            participation = (cap_traded / adv.replace(0, 1)).clip(0.001, 0.5)

        cost_bps_series = pd.Series(0.0, index=df.index)
        for idx in df.index[trades_mask]:
            cost_bps_series[idx] = self._cost_bps(
                float(sigma.loc[idx]), float(participation.loc[idx])
            )

        # Cost applied to the capital moved
        cost_fraction = cost_bps_series / 1e4
        strategy_ret = positions * price_ret - delta_pos.abs() * cost_fraction

        # ---- equity curve -------------------------------------------------
        equity = (1 + strategy_ret).cumprod() * initial_capital

        # ---- trade log ----------------------------------------------------
        trade_log = self._build_trade_log(df, positions, close, strategy_ret)

        # ---- benchmark equity --------------------------------------------
        bm_equity = None
        if benchmark_col and benchmark_col in df.columns:
            bm_prices = df[benchmark_col]
            bm_equity = bm_prices / bm_prices.iloc[0] * initial_capital

        return BacktestResult(
            equity=equity,
            returns=strategy_ret,
            positions=positions,
            trade_log=trade_log,
            benchmark_equity=bm_equity,
            metadata={"freq": freq, "initial_capital": initial_capital},
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_trade_log(
        df: pd.DataFrame,
        positions: pd.Series,
        close: pd.Series,
        strategy_ret: pd.Series,
    ) -> pd.DataFrame:
        delta = positions.diff().fillna(positions)
        entries = df.index[delta.abs() > 1e-6]
        trades = []
        open_trade: dict | None = None

        for idx in entries:
            d = float(delta.loc[idx])
            if open_trade is None and d != 0:
                open_trade = {
                    "entry_date": idx,
                    "entry_price": float(close.loc[idx]),
                    "direction": np.sign(d),
                    "size": abs(d),
                }
            elif open_trade is not None:
                exit_price = float(close.loc[idx])
                pnl = (
                    (exit_price - open_trade["entry_price"])
                    * open_trade["direction"]
                    * open_trade["size"]
                )
                trades.append({
                    **open_trade,
                    "exit_date": idx,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "return_pct": pnl / open_trade["entry_price"] * 100,
                    "bars_held": (df.index.get_loc(idx) -
                                  df.index.get_loc(open_trade["entry_date"])),
                })
                open_trade = {"entry_date": idx, "entry_price": exit_price,
                              "direction": np.sign(d), "size": abs(d)} if d != 0 else None

        return pd.DataFrame(trades) if trades else pd.DataFrame(
            columns=["entry_date", "entry_price", "direction", "size",
                     "exit_date", "exit_price", "pnl", "return_pct", "bars_held"]
        )


# ---------------------------------------------------------------------------
# WalkForwardValidator
# ---------------------------------------------------------------------------
class WalkForwardValidator:
    """
    Walk-Forward Cross-Validation for time-series strategies.

    Prevents look-ahead bias by ensuring the test period never overlaps
    with the training period. Two modes:

      'expanding'  — training window grows with each fold (anchored start).
                     Closest to real deployment: more data = better model.
      'rolling'    — training window is fixed size, slides forward.
                     Tests stability across regimes.

    Parameters
    ----------
    n_folds      Number of out-of-sample folds.
    train_ratio  Fraction of each fold used for training (0.6 = 60%).
    mode         'expanding' or 'rolling'.
    gap_bars     Bars between train end and test start (avoids lookahead
                 from multi-bar signals). Default 0.
    signal_fn    Optional callable: (train_df) -> signal series for test_df.
                 If None, uses signal_col from the DataFrame directly.
    """

    def __init__(
        self,
        n_folds: int = 5,
        train_ratio: float = 0.6,
        mode: Literal["expanding", "rolling"] = "expanding",
        gap_bars: int = 0,
        signal_fn: Callable[[pd.DataFrame], pd.Series] | None = None,
    ):
        if not 0 < train_ratio < 1:
            raise ValueError("train_ratio must be in (0, 1)")
        self.n_folds = n_folds
        self.train_ratio = train_ratio
        self.mode = mode
        self.gap_bars = gap_bars
        self.signal_fn = signal_fn

    # ------------------------------------------------------------------
    def _split(self, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """Return list of (train_idx, test_idx) arrays."""
        fold_size = n // self.n_folds
        splits = []
        for i in range(self.n_folds):
            test_end = n - (self.n_folds - 1 - i) * fold_size
            test_start = test_end - fold_size + self.gap_bars
            if self.mode == "expanding":
                train_start = 0
            else:
                train_start = max(0, test_start - int(fold_size * self.train_ratio / (1 - self.train_ratio)))
            train_end = test_start - self.gap_bars
            if train_end <= train_start or test_end <= test_start:
                continue
            splits.append((
                np.arange(train_start, train_end),
                np.arange(test_start, test_end),
            ))
        return splits

    # ------------------------------------------------------------------
    def run(
        self,
        data: pd.DataFrame,
        signal_col: str = "signal",
        backtester: VectorizedBacktester | None = None,
        initial_capital: float = 100_000.0,
        freq: str = "1d",
    ) -> BacktestResult:
        """
        Run walk-forward validation and return a stitched OOS BacktestResult.

        The returned equity curve is composed only of out-of-sample periods,
        making it a realistic estimate of live performance.
        """
        if backtester is None:
            backtester = VectorizedBacktester()

        splits = self._split(len(data))
        if not splits:
            raise ValueError("Not enough data for the requested number of folds.")

        oos_returns_list: list[pd.Series] = []
        oos_positions_list: list[pd.Series] = []
        fold_summaries: list[dict] = []

        for fold_i, (train_idx, test_idx) in enumerate(splits):
            train_df = data.iloc[train_idx].copy()
            test_df = data.iloc[test_idx].copy()

            if self.signal_fn is not None:
                # Re-generate signal on train, apply to test
                test_df[signal_col] = self.signal_fn(train_df).reindex(test_df.index)

            if signal_col not in test_df.columns or test_df[signal_col].isna().all():
                warnings.warn(f"Fold {fold_i}: no valid signal, skipping.", stacklevel=2)
                continue

            result = backtester.run(
                test_df, signal_col=signal_col,
                initial_capital=initial_capital, freq=freq,
            )
            oos_returns_list.append(result.returns)
            oos_positions_list.append(result.positions)
            summary = result.summary(freq=freq)
            summary["fold"] = fold_i
            fold_summaries.append(summary)

        if not oos_returns_list:
            raise ValueError("All folds were skipped — check your data and signal.")

        # Stitch OOS returns into a single equity curve
        all_returns = pd.concat(oos_returns_list).sort_index()
        all_positions = pd.concat(oos_positions_list).sort_index()
        oos_equity = (1 + all_returns).cumprod() * initial_capital

        oos_result = BacktestResult(
            equity=oos_equity,
            returns=all_returns,
            positions=all_positions,
            trade_log=pd.DataFrame(),  # aggregated; build per-fold if needed
            metadata={
                "freq": freq,
                "initial_capital": initial_capital,
                "mode": self.mode,
                "n_folds": self.n_folds,
                "fold_summaries": fold_summaries,
            },
        )
        return oos_result

    # ------------------------------------------------------------------
    def fold_report(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """Return a DataFrame comparing in-sample vs. out-of-sample Sharpe per fold."""
        result = self.run(data, **kwargs)
        rows = result.metadata.get("fold_summaries", [])
        return pd.DataFrame(rows).set_index("fold") if rows else pd.DataFrame()
