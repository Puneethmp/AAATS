"""
Data Quality Validation
========================
Why this exists
---------------
Garbage in, garbage out. Silent data errors — gaps, outliers, stale prices,
zero volumes, OHLC constraint violations — corrupt every downstream computation
silently. A strategy that backtests well on dirty data will fail in production
for reasons that have nothing to do with the alpha model.

This module validates OHLCV DataFrames before they are consumed by any
strategy, risk engine, or backtester. It is designed to be called:
  1. At data ingest (before writing to database)
  2. Before backtest runs
  3. As a cron job on live data feeds

Contents
--------
  OHLCVValidator          — Main validator class. Runs all checks and returns
                             a DataQualityReport with issues and a score (0-100).

  Checks implemented
  ------------------
  - Timestamp ordering    : Timestamps must be strictly monotonic increasing
  - Gap detection         : Missing bars relative to expected frequency
  - OHLC consistency      : high >= max(open, close), low <= min(open, close),
                             high >= low at all times
  - Price outliers        : Z-score and IQR-based outlier detection on returns
  - Volume checks         : Zero volume, negative volume, outlier volume
  - Stale prices          : Consecutive identical close prices (flat market or feed error)
  - Negative prices       : Open, high, low, close must all be > 0
  - Returns sanity        : Single-bar return > ±50% flagged as suspect
  - Completeness          : Fraction of expected bars actually present

Usage
-----
  from data.validator import OHLCVValidator
  import pandas as pd

  df = pd.read_sql("SELECT * FROM ohlcv WHERE symbol='BTC/USDT'", conn)
  report = OHLCVValidator(freq='1h').validate(df)
  print(report.score)           # 0-100, higher = cleaner
  print(report.issues)          # list of Issue objects
  print(report.summary())       # human-readable text
  clean_df = report.clean()     # remove rows with critical issues
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

import numpy as np
import pandas as pd

__all__ = ["OHLCVValidator", "DataQualityReport", "Issue", "Severity"]

# ---------------------------------------------------------------------------
# Enums and Issue dataclass
# ---------------------------------------------------------------------------

class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Issue:
    check: str
    severity: Severity
    message: str
    affected_rows: list = field(default_factory=list)
    n_affected: int = 0

    def __post_init__(self):
        if not self.n_affected and self.affected_rows:
            self.n_affected = len(self.affected_rows)


# ---------------------------------------------------------------------------
# Expected bar frequencies
# ---------------------------------------------------------------------------
_FREQ_TIMEDELTA = {
    "1min": pd.Timedelta(minutes=1),
    "5min": pd.Timedelta(minutes=5),
    "15min": pd.Timedelta(minutes=15),
    "30min": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "1Hour": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
    "1Day": pd.Timedelta(days=1),
    "1w": pd.Timedelta(weeks=1),
}


# ---------------------------------------------------------------------------
# DataQualityReport
# ---------------------------------------------------------------------------
@dataclass
class DataQualityReport:
    symbol: str
    freq: str
    n_rows: int
    issues: list[Issue] = field(default_factory=list)
    _bad_rows: set = field(default_factory=set, repr=False)

    @property
    def score(self) -> float:
        """
        Quality score 0-100. Deductions per issue type:
          CRITICAL  → 20 pts per unique check (capped at 100)
          ERROR     → 10 pts
          WARNING   → 3 pts
          INFO      → 0 pts
        """
        deductions = {
            Severity.CRITICAL: 20,
            Severity.ERROR: 10,
            Severity.WARNING: 3,
            Severity.INFO: 0,
        }
        seen_checks: set[str] = set()
        total_deduction = 0
        for issue in self.issues:
            key = (issue.check, issue.severity)
            if key not in seen_checks:
                total_deduction += deductions[issue.severity]
                seen_checks.add(key)
            # Additional deduction proportional to fraction of bad rows
            if issue.n_affected > 0 and self.n_rows > 0:
                frac = min(issue.n_affected / self.n_rows, 1.0)
                total_deduction += frac * deductions[issue.severity] * 0.5
        return max(0.0, round(100.0 - total_deduction, 1))

    @property
    def n_critical(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)

    def summary(self) -> str:
        lines = [
            f"Data Quality Report — {self.symbol} @ {self.freq}",
            f"Rows: {self.n_rows:,} | Score: {self.score}/100",
            f"Issues: {self.n_critical} CRITICAL, {self.n_errors} ERROR, "
            f"{self.n_warnings} WARNING",
            "",
        ]
        for issue in sorted(self.issues, key=lambda i: i.severity.value, reverse=True):
            lines.append(f"  [{issue.severity.value:8s}] {issue.check}: {issue.message}")
        return "\n".join(lines)

    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove rows flagged as CRITICAL or ERROR from the DataFrame."""
        if not self._bad_rows:
            return df
        mask = ~df.index.isin(self._bad_rows)
        n_removed = mask.sum()
        if n_removed < len(df):
            warnings.warn(
                f"Removed {len(df) - n_removed:,} bad rows from {self.symbol}.",
                stacklevel=2,
            )
        return df.loc[mask]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "freq": self.freq,
            "n_rows": self.n_rows,
            "score": self.score,
            "n_critical": self.n_critical,
            "n_errors": self.n_errors,
            "n_warnings": self.n_warnings,
            "issues": [
                {"check": i.check, "severity": i.severity.value,
                 "message": i.message, "n_affected": i.n_affected}
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# OHLCVValidator
# ---------------------------------------------------------------------------
class OHLCVValidator:
    """
    Validate an OHLCV DataFrame for a single symbol.

    Parameters
    ----------
    freq                Bar frequency string (e.g. '1h', '1d', '15min').
    outlier_z_thresh    Z-score threshold for return outlier detection.
    outlier_iqr_mult    IQR multiplier for price outlier detection.
    stale_run_length    Number of consecutive identical closes to flag as stale.
    max_single_return   Maximum plausible single-bar absolute return.
    symbol              Symbol name (for reporting).
    """

    def __init__(
        self,
        freq: str = "1d",
        outlier_z_thresh: float = 5.0,
        outlier_iqr_mult: float = 8.0,
        stale_run_length: int = 5,
        max_single_return: float = 0.5,
        symbol: str = "UNKNOWN",
    ):
        self.freq = freq
        self.outlier_z_thresh = outlier_z_thresh
        self.outlier_iqr_mult = outlier_iqr_mult
        self.stale_run_length = stale_run_length
        self.max_single_return = max_single_return
        self.symbol = symbol
        self._expected_delta = _FREQ_TIMEDELTA.get(freq)

    # ------------------------------------------------------------------
    def validate(self, df: pd.DataFrame) -> DataQualityReport:
        """
        Run all validation checks. Returns a DataQualityReport.

        Parameters
        ----------
        df    DataFrame with at minimum a 'close' column. Expected columns:
              open, high, low, close, volume. Index should be datetime.
        """
        if df.empty:
            report = DataQualityReport(self.symbol, self.freq, 0)
            report.issues.append(Issue(
                "completeness", Severity.CRITICAL,
                "DataFrame is empty — no data to validate."
            ))
            return report

        report = DataQualityReport(self.symbol, self.freq, len(df))
        has_ohlcv = all(c in df.columns for c in ["open", "high", "low", "close", "volume"])
        has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])

        self._check_timestamp_ordering(df, report)
        self._check_negative_prices(df, report)

        if has_ohlc:
            self._check_ohlc_consistency(df, report)

        self._check_return_outliers(df, report)
        self._check_stale_prices(df, report)
        self._check_extreme_returns(df, report)

        if "volume" in df.columns:
            self._check_volume(df, report)

        if self._expected_delta is not None:
            self._check_gaps(df, report)

        self._check_completeness(df, report)

        return report

    # ------------------------------------------------------------------
    def _add_issue(
        self, report: DataQualityReport, check: str,
        severity: Severity, message: str,
        affected: list | None = None,
    ):
        affected = affected or []
        issue = Issue(check, severity, message, affected, len(affected))
        report.issues.append(issue)
        if severity in (Severity.CRITICAL, Severity.ERROR):
            report._bad_rows.update(affected)

    # ------------------------------------------------------------------
    def _check_timestamp_ordering(self, df: pd.DataFrame, report: DataQualityReport):
        if not isinstance(df.index, pd.DatetimeIndex):
            self._add_issue(report, "timestamp_ordering", Severity.ERROR,
                            "Index is not a DatetimeIndex.")
            return
        diffs = pd.Series(df.index).diff().iloc[1:]
        bad = diffs[diffs <= pd.Timedelta(0)]
        if len(bad) > 0:
            self._add_issue(
                report, "timestamp_ordering", Severity.CRITICAL,
                f"{len(bad)} non-monotonic or duplicate timestamps found.",
                list(df.index[bad.index]),
            )

    # ------------------------------------------------------------------
    def _check_negative_prices(self, df: pd.DataFrame, report: DataQualityReport):
        price_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        for col in price_cols:
            bad_mask = df[col] <= 0
            if bad_mask.any():
                self._add_issue(
                    report, "negative_prices", Severity.CRITICAL,
                    f"{col}: {bad_mask.sum()} rows with price ≤ 0.",
                    list(df.index[bad_mask]),
                )

    # ------------------------------------------------------------------
    def _check_ohlc_consistency(self, df: pd.DataFrame, report: DataQualityReport):
        # high >= open, close
        bad_high = df["high"] < df[["open", "close"]].max(axis=1) - 1e-9
        if bad_high.any():
            self._add_issue(
                report, "ohlc_consistency", Severity.ERROR,
                f"{bad_high.sum()} rows where high < max(open, close).",
                list(df.index[bad_high]),
            )
        # low <= open, close
        bad_low = df["low"] > df[["open", "close"]].min(axis=1) + 1e-9
        if bad_low.any():
            self._add_issue(
                report, "ohlc_consistency", Severity.ERROR,
                f"{bad_low.sum()} rows where low > min(open, close).",
                list(df.index[bad_low]),
            )
        # high >= low
        bad_hl = df["high"] < df["low"] - 1e-9
        if bad_hl.any():
            self._add_issue(
                report, "ohlc_consistency", Severity.CRITICAL,
                f"{bad_hl.sum()} rows where high < low.",
                list(df.index[bad_hl]),
            )

    # ------------------------------------------------------------------
    def _check_return_outliers(self, df: pd.DataFrame, report: DataQualityReport):
        close = df["close"].replace(0, np.nan)
        ret = close.pct_change().dropna()
        if len(ret) < 10:
            return

        # Z-score method
        z = (ret - ret.mean()) / ret.std()
        z_bad = z.abs() > self.outlier_z_thresh
        if z_bad.any():
            self._add_issue(
                report, "return_outliers_zscore", Severity.WARNING,
                f"{z_bad.sum()} returns with |z-score| > {self.outlier_z_thresh}.",
                list(ret.index[z_bad]),
            )

        # IQR method
        q1, q3 = ret.quantile(0.25), ret.quantile(0.75)
        iqr = q3 - q1
        iqr_bad = (ret < q1 - self.outlier_iqr_mult * iqr) | (ret > q3 + self.outlier_iqr_mult * iqr)
        if iqr_bad.any():
            self._add_issue(
                report, "return_outliers_iqr", Severity.WARNING,
                f"{iqr_bad.sum()} returns outside {self.outlier_iqr_mult}×IQR fence.",
                list(ret.index[iqr_bad]),
            )

    # ------------------------------------------------------------------
    def _check_extreme_returns(self, df: pd.DataFrame, report: DataQualityReport):
        close = df["close"].replace(0, np.nan)
        ret = close.pct_change().dropna()
        extreme = ret.abs() > self.max_single_return
        if extreme.any():
            self._add_issue(
                report, "extreme_returns", Severity.WARNING,
                f"{extreme.sum()} bars with |return| > {self.max_single_return*100:.0f}%. "
                f"Verify these are real price moves, not data errors.",
                list(ret.index[extreme]),
            )

    # ------------------------------------------------------------------
    def _check_stale_prices(self, df: pd.DataFrame, report: DataQualityReport):
        close = df["close"]
        # Count consecutive runs of identical close prices
        run_len = (close != close.shift()).cumsum()
        run_sizes = run_len.map(run_len.value_counts())
        stale_mask = (close == close.shift()) & (run_sizes >= self.stale_run_length)
        if stale_mask.any():
            n = stale_mask.sum()
            self._add_issue(
                report, "stale_prices", Severity.WARNING,
                f"{n} bars in runs of {self.stale_run_length}+ consecutive "
                f"identical close prices (possible feed freeze).",
                list(df.index[stale_mask]),
            )

    # ------------------------------------------------------------------
    def _check_volume(self, df: pd.DataFrame, report: DataQualityReport):
        vol = df["volume"]
        # Negative volume
        neg_vol = vol < 0
        if neg_vol.any():
            self._add_issue(
                report, "volume", Severity.CRITICAL,
                f"{neg_vol.sum()} rows with negative volume.",
                list(df.index[neg_vol]),
            )
        # Zero volume
        zero_vol = vol == 0
        if zero_vol.any():
            n = zero_vol.sum()
            sev = Severity.ERROR if n > len(df) * 0.02 else Severity.WARNING
            self._add_issue(
                report, "zero_volume", sev,
                f"{n} rows ({n/len(df)*100:.1f}%) with zero volume.",
                list(df.index[zero_vol]),
            )
        # Volume outliers (z-score)
        if len(vol) > 20:
            log_vol = np.log1p(vol.clip(lower=0))
            z = (log_vol - log_vol.mean()) / log_vol.std()
            vol_out = z > 8.0
            if vol_out.any():
                self._add_issue(
                    report, "volume_outliers", Severity.WARNING,
                    f"{vol_out.sum()} bars with volume >8 std above log-mean.",
                    list(df.index[vol_out]),
                )

    # ------------------------------------------------------------------
    def _check_gaps(self, df: pd.DataFrame, report: DataQualityReport):
        if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
            return
        diffs = pd.Series(df.index).diff().iloc[1:]
        expected = self._expected_delta
        gaps = diffs[diffs > expected * 1.5]
        if len(gaps) > 0:
            total_missing = int((gaps / expected - 1).clip(lower=0).sum())
            sev = Severity.ERROR if total_missing > 5 else Severity.WARNING
            self._add_issue(
                report, "gaps", sev,
                f"{len(gaps)} gap(s) found, ~{total_missing} missing bar(s) total. "
                f"Largest gap: {gaps.max()}.",
            )

    # ------------------------------------------------------------------
    def _check_completeness(self, df: pd.DataFrame, report: DataQualityReport):
        if self._expected_delta is None or not isinstance(df.index, pd.DatetimeIndex):
            return
        span = df.index[-1] - df.index[0]
        expected_bars = max(int(span / self._expected_delta) + 1, 1)
        actual_bars = len(df)
        completeness = actual_bars / expected_bars

        if completeness < 0.80:
            self._add_issue(
                report, "completeness", Severity.ERROR,
                f"Only {completeness*100:.1f}% of expected bars present "
                f"({actual_bars:,}/{expected_bars:,}). Significant data gaps.",
            )
        elif completeness < 0.95:
            self._add_issue(
                report, "completeness", Severity.WARNING,
                f"{completeness*100:.1f}% of expected bars present "
                f"({actual_bars:,}/{expected_bars:,}).",
            )
