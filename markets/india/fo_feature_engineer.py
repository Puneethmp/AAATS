"""
F&O feature engineer.
Computes option-chain derived features: PCR, IV Rank, Max Pain, and Black-Scholes Greeks.

mibian (last released 2016) was specified but is too stale to install.
Greeks are implemented directly via scipy.stats.norm — identical mathematics,
no external dependency beyond scipy which is already part of the project stack.
"""

import math

import pandas as pd
from scipy.stats import norm

from foundation.logger import get_logger

_log = get_logger("india", "fo_feature_engineer")

_REQUIRED_CHAIN_COLS: frozenset[str] = frozenset({"strike", "option_type", "oi"})


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validate_chain(df: pd.DataFrame) -> None:
    """Raise ValueError if required columns are missing from the option chain."""
    missing = _REQUIRED_CHAIN_COLS - set(df.columns)
    if missing:
        raise ValueError(f"option_chain_df missing required columns: {sorted(missing)}")


# ── Public API ────────────────────────────────────────────────────────────────


def compute_pcr(option_chain_df: pd.DataFrame) -> float:
    """
    Put-Call Ratio = sum(Put OI) / sum(Call OI).

    Returns float('nan') — not infinity — when Call OI sums to zero.
    """
    _validate_chain(option_chain_df)

    call_oi = option_chain_df.loc[option_chain_df["option_type"] == "CE", "oi"].sum()
    put_oi = option_chain_df.loc[option_chain_df["option_type"] == "PE", "oi"].sum()

    if call_oi == 0:
        _log.warning(
            "compute_pcr: sum(Call OI)=0 — returning NaN to avoid division by zero"
        )
        return float("nan")

    pcr = float(put_oi / call_oi)
    _log.debug(f"compute_pcr: put_oi={put_oi}, call_oi={call_oi}, pcr={pcr:.4f}")
    return pcr


def compute_iv_rank(current_iv: float, iv_history_52w: list[float]) -> float:
    """
    IV Rank = (current_iv - min_52w) / (max_52w - min_52w) * 100.

    Returns 50.0 (neutral) when the 52-week range is flat (max == min) or
    when iv_history_52w is empty — prevents division-by-zero in either case.
    Result is clamped to [0.0, 100.0].
    """
    if not iv_history_52w:
        _log.warning("compute_iv_rank: empty iv_history_52w — returning neutral 50.0")
        return 50.0

    min_iv = min(iv_history_52w)
    max_iv = max(iv_history_52w)

    if max_iv == min_iv:
        _log.debug("compute_iv_rank: flat 52-week IV range — returning neutral 50.0")
        return 50.0

    rank = (current_iv - min_iv) / (max_iv - min_iv) * 100.0
    rank = float(max(0.0, min(100.0, rank)))
    _log.debug(
        f"compute_iv_rank: current={current_iv}, min={min_iv}, max={max_iv}, rank={rank:.2f}"
    )
    return rank


def compute_max_pain(option_chain_df: pd.DataFrame) -> float:
    """
    Max Pain = expiry price (a strike) at which total writer losses are minimised.

    Algorithm: for each candidate strike S*, sum:
      - Call writer losses: max(0, S* - K_call) * call_OI for every call strike K_call
      - Put writer losses:  max(0, K_put - S*) * put_OI  for every put strike K_put
    Return the S* with the lowest total writer loss.
    """
    _validate_chain(option_chain_df)

    strikes = sorted(option_chain_df["strike"].unique())
    if not strikes:
        raise ValueError("compute_max_pain: option_chain_df contains no strikes")

    calls = option_chain_df[option_chain_df["option_type"] == "CE"].set_index("strike")[
        "oi"
    ]
    puts = option_chain_df[option_chain_df["option_type"] == "PE"].set_index("strike")[
        "oi"
    ]

    min_total_loss = float("inf")
    max_pain_strike = strikes[0]

    for expiry_at in strikes:
        call_loss = sum(
            max(0.0, expiry_at - s) * float(calls.get(s, 0.0)) for s in strikes
        )
        put_loss = sum(
            max(0.0, s - expiry_at) * float(puts.get(s, 0.0)) for s in strikes
        )
        total = call_loss + put_loss
        if total < min_total_loss:
            min_total_loss = total
            max_pain_strike = expiry_at

    _log.debug(
        f"compute_max_pain: max_pain_strike={max_pain_strike}, total_loss={min_total_loss:.0f}"
    )
    return float(max_pain_strike)


def compute_greeks(
    option_type: str,
    underlying_price: float,
    strike: float,
    time_to_expiry_days: float,
    risk_free_rate: float,
    implied_volatility: float,
) -> dict:
    """
    Black-Scholes Greeks computed directly via scipy.stats.norm.

    Args:
        option_type:          "CE" (call) or "PE" (put).
        underlying_price:     Current spot price of the underlying (e.g. Nifty level).
        strike:               Option strike price.
        time_to_expiry_days:  Calendar days remaining to expiry (must be > 0).
        risk_free_rate:       Annualised risk-free rate as decimal (e.g. 0.065 for 6.5%).
        implied_volatility:   Annualised IV as decimal (e.g. 0.20 for 20%).

    Returns:
        dict with keys: delta, gamma, theta (daily), vega (per 1% IV move).

    Notes:
        - Delta: CE ∈ [0, 1], PE ∈ [-1, 0].
        - Theta: always negative for ATM/OTM options (time decay).
        - Vega: expressed per 1% absolute change in implied_volatility.
    """
    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be 'CE' or 'PE', got '{option_type!r}'")
    if time_to_expiry_days <= 0:
        raise ValueError(f"time_to_expiry_days must be > 0, got {time_to_expiry_days}")
    if implied_volatility <= 0:
        raise ValueError(f"implied_volatility must be > 0, got {implied_volatility}")
    if underlying_price <= 0:
        raise ValueError(f"underlying_price must be > 0, got {underlying_price}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")

    S = float(underlying_price)
    K = float(strike)
    T = time_to_expiry_days / 365.0
    r = float(risk_free_rate)
    sigma = float(implied_volatility)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    n_d1 = norm.pdf(d1)
    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)
    N_neg_d2 = norm.cdf(-d2)

    gamma = n_d1 / (S * sigma * sqrt_T)
    # Vega per 1% change in IV (divide raw vega by 100)
    vega = S * n_d1 * sqrt_T / 100.0

    if option_type == "CE":
        delta = N_d1
        # Annualised theta → daily (divide by 365)
        theta_annual = (
            -S * n_d1 * sigma / (2.0 * sqrt_T) - r * K * math.exp(-r * T) * N_d2
        )
        theta = theta_annual / 365.0
    else:  # PE
        delta = N_d1 - 1.0  # equivalent to -N(-d1)
        theta_annual = (
            -S * n_d1 * sigma / (2.0 * sqrt_T) + r * K * math.exp(-r * T) * N_neg_d2
        )
        theta = theta_annual / 365.0

    result = {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
    }
    _log.debug(
        f"compute_greeks: {option_type} S={S} K={K} T={time_to_expiry_days}d "
        f"IV={implied_volatility:.2%} → {result}"
    )
    return result
