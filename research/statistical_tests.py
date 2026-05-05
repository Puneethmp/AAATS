"""
Statistical Rigour for Strategy Research
=========================================
Why this exists
---------------
Most strategies that look good in backtests are false discoveries.
The Sharpe ratio is easy to overfit. Without proper statistical testing,
you will ship noise traders.

This module implements the tools that prevent that:

  1. Deflated Sharpe Ratio (DSR)    — Adjusts the Sharpe for the number of
                                       strategies tested and non-normality of
                                       returns. Published by Bailey & Lopez de
                                       Prado (2014). If DSR < threshold, the
                                       strategy likely owes its performance to
                                       multiple testing rather than genuine skill.

  2. Minimum Track Record Length    — Given a target Sharpe and desired
                                       confidence, computes the minimum number
                                       of observations needed to reject the
                                       null hypothesis. Most strategies need
                                       ~3–5 years of daily data.

  3. Multiple Testing Correction    — When you test K strategies and pick
                                       the best, you must correct for multiple
                                       comparisons. Implements Bonferroni
                                       (conservative) and Benjamini-Hochberg-
                                       Yekutieli (BHY, more powerful).

  4. Combinatorial Purged CV        — Bailey & Lopez de Prado's CPCV: generates
                                       all C(N,k) combinations of test folds,
                                       ensuring no future data leaks into training.
                                       Produces a realistic Probability of
                                       Backtest Overfitting (PBO) score.

Reference
---------
  Bailey, D., & Lopez de Prado, M. (2014). The Deflated Sharpe Ratio.
  Journal of Portfolio Management, 40(5).

  Bailey, D., et al. (2014). Pseudo-Mathematics and Financial Charlatanism.
  Notices of the AMS.

  Benjamini, Y., & Yekutieli, D. (2001). The control of the false discovery
  rate in multiple testing under dependency. Annals of Statistics.
"""

from __future__ import annotations

import itertools
import warnings
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import comb as _comb

__all__ = [
    "deflated_sharpe_ratio",
    "min_track_record_length",
    "multiple_testing_correction",
    "combinatorial_purged_cv",
    "probabilistic_sharpe_ratio",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_ANN = {"1d": 252, "1Day": 252, "1h": 252 * 6.5, "1Hour": 252 * 6.5, "1w": 52}


def _ann_factor(freq: str) -> float:
    return _ANN.get(freq, 252)


def _sharpe(r: np.ndarray) -> float:
    s = r.std()
    return float(r.mean() / s) if s > 0 else 0.0


# ---------------------------------------------------------------------------
# Probabilistic Sharpe Ratio (PSR)
# ---------------------------------------------------------------------------
def probabilistic_sharpe_ratio(
    returns: pd.Series,
    benchmark_sharpe: float = 0.0,
    freq: str = "1d",
) -> dict:
    """
    Compute the Probabilistic Sharpe Ratio (PSR).

    PSR = P(SR* > SR_benchmark | observed SR, T, skewness, kurtosis)

    PSR corrects the Sharpe for:
      - Finite sample bias (small N → wide CI on Sharpe)
      - Non-normality (negative skew and fat tails inflate Sharpe variance)

    PSR > 0.95 means 95%+ confidence the true Sharpe beats the benchmark.

    Parameters
    ----------
    returns          Strategy returns.
    benchmark_sharpe Sharpe ratio to beat (often 0 or Sharpe of buy-and-hold).
    freq             Bar frequency for annualisation.

    Returns
    -------
    dict: psr, z_stat, observed_sharpe_ann, benchmark_sharpe_ann.
    """
    ann = _ann_factor(freq)
    r = returns.dropna().values
    n = len(r)
    if n < 4:
        return {"psr": float("nan"), "z_stat": float("nan")}

    sr_obs = _sharpe(r)  # per-bar SR
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r))  # excess kurtosis

    # Variance of SR estimator (Lo 2002 / Bailey & LP 2014)
    sr_var = (
        1 / (n - 1)
        * (1 + (skew * sr_obs) / 2 - ((kurt - 1) / 4) * sr_obs**2)
    )  # already in per-bar^2 / sample size units
    if sr_var <= 0:
        return {"psr": float("nan"), "z_stat": float("nan")}

    # Benchmark SR in per-bar units
    sr_bench_per_bar = benchmark_sharpe / np.sqrt(ann)
    z = (sr_obs - sr_bench_per_bar) / np.sqrt(sr_var)
    psr = float(stats.norm.cdf(z))

    return {
        "psr": round(psr, 6),
        "z_stat": round(float(z), 4),
        "observed_sharpe_ann": round(sr_obs * np.sqrt(ann), 4),
        "benchmark_sharpe_ann": round(benchmark_sharpe, 4),
        "n_obs": n,
        "skewness": round(skew, 4),
        "excess_kurtosis": round(kurt, 4),
        "interpretation": (
            f"{'PASS' if psr >= 0.95 else 'FAIL'}: "
            f"P(true SR > {benchmark_sharpe:.2f}) = {psr:.1%}"
        ),
    }


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio
# ---------------------------------------------------------------------------
def deflated_sharpe_ratio(
    returns: pd.Series,
    n_strategies_tested: int,
    freq: str = "1d",
    benchmark_sharpe: float = 0.0,
) -> dict:
    """
    Compute the Deflated Sharpe Ratio (DSR).

    Adjusts the observed Sharpe for the number of strategies/trials tested.
    When you test many strategies and report only the best, the expected
    maximum Sharpe across N i.i.d. trials follows the distribution of
    the maximum of N standard normals.

    DSR accounts for this by raising the required threshold:
      SR_threshold = E[max_{i=1..N} SR_i]

    If DSR (= PSR using SR_threshold as benchmark) < 0.95, the strategy
    is likely a false discovery.

    Parameters
    ----------
    returns              Observed returns of the BEST strategy after search.
    n_strategies_tested  Total number of strategies tried in the search.
    freq                 Bar frequency.
    benchmark_sharpe     Minimum acceptable SR (before deflation).

    Returns
    -------
    dict: dsr, expected_max_sr, adjusted_threshold, is_genuine.
    """
    ann = _ann_factor(freq)
    r = returns.dropna().values
    n = len(r)

    # Expected max Sharpe across N trials (iid normal Sharpe)
    # E[max_N Z] ≈ (1 - euler_gamma) * z_{1-1/N} + euler_gamma * z_{1-1/(N*e)}
    # Simpler: use the approximation from Bailey & LP (2014)
    euler_gamma = 0.5772156649
    if n_strategies_tested > 1:
        expected_max = (
            (1 - euler_gamma) * stats.norm.ppf(1 - 1 / n_strategies_tested) +
            euler_gamma * stats.norm.ppf(1 - 1 / (n_strategies_tested * np.e))
        )
    else:
        expected_max = 0.0

    # Convert from Z-score to annualised SR (expected max is in std normal units)
    # The SR per bar corresponds to the SR / sqrt(T) of the Z-score
    # Bailey & LP use: SR* = (expected_max / sqrt(T)) * (mean corrected variance)
    adjusted_threshold_per_bar = max(expected_max / np.sqrt(n), benchmark_sharpe / np.sqrt(ann))
    adjusted_threshold_ann = adjusted_threshold_per_bar * np.sqrt(ann)

    psr_result = probabilistic_sharpe_ratio(
        returns,
        benchmark_sharpe=adjusted_threshold_ann,
        freq=freq,
    )
    dsr = psr_result.get("psr", float("nan"))

    return {
        "dsr": round(dsr, 6) if not np.isnan(dsr) else None,
        "n_strategies_tested": n_strategies_tested,
        "expected_max_sharpe_ann": round(float(expected_max), 4),
        "adjusted_sr_threshold_ann": round(float(adjusted_threshold_ann), 4),
        "observed_sharpe_ann": psr_result.get("observed_sharpe_ann"),
        "is_genuine_discovery": bool(dsr >= 0.95) if not np.isnan(dsr) else False,
        "interpretation": (
            f"{'GENUINE' if dsr >= 0.95 else 'LIKELY OVERFITTED'}: "
            f"After testing {n_strategies_tested} strategies, threshold SR = "
            f"{adjusted_threshold_ann:.3f}. DSR = {dsr:.3f}."
            if not np.isnan(dsr) else "Insufficient data."
        ),
    }


# ---------------------------------------------------------------------------
# Minimum Track Record Length
# ---------------------------------------------------------------------------
def min_track_record_length(
    target_sharpe: float,
    freq: str = "1d",
    confidence: float = 0.95,
    benchmark_sharpe: float = 0.0,
    skewness: float = 0.0,
    excess_kurtosis: float = 0.0,
) -> dict:
    """
    Compute the minimum number of observations needed to statistically
    confirm a target Sharpe ratio exceeds a benchmark.

    Most retail strategies need 2–5 years of daily data (500–1250 bars)
    to achieve 95% confidence. This function tells you exactly how long
    to run before claiming the strategy works.

    Parameters
    ----------
    target_sharpe     Annualised Sharpe you expect the strategy to achieve.
    freq              Bar frequency.
    confidence        Desired statistical confidence (default 0.95).
    benchmark_sharpe  Minimum acceptable annualised Sharpe to beat.
    skewness          Expected skewness of returns (default 0 = normal).
    excess_kurtosis   Expected excess kurtosis (default 0 = normal).

    Returns
    -------
    dict: min_observations, min_period_label, confidence.
    """
    ann = _ann_factor(freq)
    z = stats.norm.ppf(confidence)
    sr_per_bar = target_sharpe / np.sqrt(ann)
    sr_bench_per_bar = benchmark_sharpe / np.sqrt(ann)

    # Variance of Sharpe estimator (Lo 2002)
    sr_var_coeff = 1 + (skewness * sr_per_bar) - ((excess_kurtosis - 1) / 4) * sr_per_bar**2

    # From PSR: n >= z^2 * var_coeff / (sr_obs - sr_bench)^2
    diff = sr_per_bar - sr_bench_per_bar
    if diff <= 0:
        return {
            "error": "target_sharpe must exceed benchmark_sharpe",
            "min_observations": None,
        }

    n_min = int(np.ceil(z**2 * sr_var_coeff / diff**2 + 1))
    bars_per_year = ann
    years = n_min / bars_per_year

    period_map = {
        "1d": "trading days",
        "1Day": "trading days",
        "1h": "trading hours",
        "1Hour": "trading hours",
        "1w": "weeks",
    }
    period_label = period_map.get(freq, "bars")

    return {
        "min_observations": n_min,
        "period_label": period_label,
        "years_equivalent": round(years, 2),
        "target_sharpe_ann": target_sharpe,
        "benchmark_sharpe_ann": benchmark_sharpe,
        "confidence_pct": int(confidence * 100),
        "interpretation": (
            f"Need {n_min:,} {period_label} (~{years:.1f} years) at {confidence:.0%} confidence "
            f"to confirm SR ≥ {target_sharpe:.2f} beats SR = {benchmark_sharpe:.2f}."
        ),
    }


# ---------------------------------------------------------------------------
# Multiple Testing Correction
# ---------------------------------------------------------------------------
def multiple_testing_correction(
    p_values: Sequence[float],
    method: str = "bhy",
    alpha: float = 0.05,
) -> pd.DataFrame:
    """
    Correct p-values for multiple testing.

    When you test N strategies and use the same dataset, the probability
    of finding at least one false positive is 1 - (1-alpha)^N.
    For N=20 at alpha=0.05, that's 64% chance of at least one false positive.

    Methods
    -------
    'bonferroni'  — Multiply each p-value by N. Conservative, many false negatives.
    'holm'        — Holm-Bonferroni step-down. Less conservative than Bonferroni.
    'bhy'         — Benjamini-Hochberg-Yekutieli. Controls FDR under arbitrary
                    dependence. Best for correlated strategies (most realistic).

    Parameters
    ----------
    p_values  Sequence of p-values from N strategy tests.
    method    'bonferroni', 'holm', or 'bhy'.
    alpha     Family-wise error rate (default 0.05).

    Returns
    -------
    DataFrame: p_value, corrected_p_value, reject_null (at alpha level).
    """
    pv = np.array(p_values, dtype=float)
    n = len(pv)
    if n == 0:
        return pd.DataFrame()

    if method == "bonferroni":
        corrected = np.minimum(pv * n, 1.0)
    elif method == "holm":
        order = np.argsort(pv)
        corrected = np.empty(n)
        for i, idx in enumerate(order):
            corrected[idx] = min(pv[idx] * (n - i), 1.0)
        # Ensure monotonicity
        for i in range(1, n):
            corrected[order[i]] = max(corrected[order[i]], corrected[order[i - 1]])
    elif method == "bhy":
        # Benjamini-Hochberg-Yekutieli (valid under arbitrary dependency)
        c_n = np.sum(1.0 / np.arange(1, n + 1))  # harmonic number
        order = np.argsort(pv)[::-1]  # descending
        corrected = np.empty(n)
        min_val = 1.0
        for i, idx in enumerate(order):
            rank = n - i
            threshold = alpha * rank / (n * c_n)
            corrected[idx] = min(pv[idx] * n * c_n / rank, 1.0)
        # Ensure monotonicity (step-up)
        sorted_corrected = corrected[np.argsort(pv)]
        for i in range(len(sorted_corrected) - 2, -1, -1):
            sorted_corrected[i] = min(sorted_corrected[i], sorted_corrected[i + 1])
        corrected[np.argsort(pv)] = sorted_corrected
    else:
        raise ValueError(f"Unknown method '{method}'. Use 'bonferroni', 'holm', or 'bhy'.")

    return pd.DataFrame({
        "p_value": pv,
        "corrected_p_value": corrected.round(6),
        "reject_null": corrected < alpha,
        "method": method,
    })


# ---------------------------------------------------------------------------
# Combinatorial Purged Cross-Validation (CPCV)
# ---------------------------------------------------------------------------
def combinatorial_purged_cv(
    returns: pd.Series,
    n_splits: int = 6,
    n_test_splits: int = 2,
    purge_pct: float = 0.01,
) -> dict:
    """
    Combinatorial Purged Cross-Validation (Bailey & Lopez de Prado 2018).

    Generates C(n_splits, n_test_splits) path combinations to produce
    a distribution of out-of-sample Sharpe ratios. The Probability of
    Backtest Overfitting (PBO) is the fraction of paths where the OOS
    Sharpe is lower than the IS Sharpe.

    A PBO > 0.50 means the strategy is more likely overfit than not.

    Parameters
    ----------
    returns        Strategy returns series.
    n_splits       Total number of equally-sized splits.
    n_test_splits  Number of splits used as test in each combination.
    purge_pct      Fraction of each split to purge at boundaries (prevents
                   leakage from overlapping labels or multi-bar signals).

    Returns
    -------
    dict: pbo, oos_sharpes (distribution), is_sharpes, n_combinations.
    """
    r = returns.dropna()
    n = len(r)
    split_size = n // n_splits
    purge_size = max(1, int(split_size * purge_pct))

    # Create split indices
    splits = [
        r.iloc[i * split_size: (i + 1) * split_size]
        for i in range(n_splits)
    ]

    n_combos = int(_comb(n_splits, n_test_splits))
    oos_sharpes = []
    is_sharpes = []

    for test_idx in itertools.combinations(range(n_splits), n_test_splits):
        test_idx_set = set(test_idx)
        train_idx_set = set(range(n_splits)) - test_idx_set

        # Collect train and test periods with purging at boundaries
        train_parts = []
        for ti in sorted(train_idx_set):
            s = splits[ti]
            # Purge if adjacent to test split
            if (ti + 1) in test_idx_set:
                s = s.iloc[: -purge_size]
            if (ti - 1) in test_idx_set:
                s = s.iloc[purge_size:]
            if len(s) > 0:
                train_parts.append(s)

        test_parts = [splits[ti] for ti in sorted(test_idx)]

        if not train_parts or not test_parts:
            continue

        train_r = pd.concat(train_parts)
        test_r = pd.concat(test_parts)

        is_sr = _sharpe(train_r.values)
        oos_sr = _sharpe(test_r.values)
        is_sharpes.append(is_sr)
        oos_sharpes.append(oos_sr)

    if not oos_sharpes:
        return {"pbo": float("nan"), "error": "No valid combinations generated."}

    is_arr = np.array(is_sharpes)
    oos_arr = np.array(oos_sharpes)
    pbo = float((oos_arr < is_arr).mean())

    return {
        "pbo": round(pbo, 4),
        "n_combinations": len(oos_sharpes),
        "oos_sharpe_mean": round(float(oos_arr.mean()), 4),
        "oos_sharpe_std": round(float(oos_arr.std()), 4),
        "oos_sharpe_median": round(float(np.median(oos_arr)), 4),
        "is_sharpe_mean": round(float(is_arr.mean()), 4),
        "is_sharpe_degradation_pct": round(
            float((1 - oos_arr.mean() / is_arr.mean()) * 100)
            if is_arr.mean() != 0 else float("nan"), 2
        ),
        "interpretation": (
            f"PBO = {pbo:.1%}. "
            + ("HIGH OVERFITTING RISK — do not deploy."
               if pbo > 0.5 else "Acceptable overfitting risk.")
        ),
        "oos_sharpes": oos_arr.tolist(),
        "is_sharpes": is_arr.tolist(),
    }
