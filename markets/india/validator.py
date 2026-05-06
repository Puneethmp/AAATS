"""
India NSE/BSE equity bar validator.
Extends standard OHLCV checks with NSE circuit breaker rejection.
Rejected bars are audit-logged as REJECTION events and never stored.
"""

from typing import Any

import pandas as pd

from foundation.audit_trail import AuditTrail
from foundation.logger import get_logger

_log = get_logger("india", "validator")

_REQUIRED_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]
_CIRCUIT_PCT_DEFAULT: int = 20  # NSE default band for most equities
_CIRCUIT_EPSILON: float = 1e-9  # tolerance for FP comparison at exact circuit boundary


def _get_circuit_pct(symbol: str, config) -> float:
    """Return the NSE circuit breaker % for a symbol, with fallback to default."""
    try:
        limits = config.india.circuit_limits
        return float(limits.get(symbol, _CIRCUIT_PCT_DEFAULT))
    except (AttributeError, TypeError, ValueError):
        return float(_CIRCUIT_PCT_DEFAULT)


def validate_bars(
    df: pd.DataFrame,
    symbol: str,
    config,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Validate OHLCV bars for an India NSE/BSE equity symbol.

    Rejects bars with any of:
    - Null value in any required column
    - volume == 0
    - high < low
    - |close / prev_close - 1| > 0.20 (price spike)
    - timestamp not strictly greater than previous bar's timestamp
    - close at or above the NSE upper circuit limit for this symbol
    - close at or below the NSE lower circuit limit for this symbol

    Args:
        df:     DataFrame with columns [timestamp, open, high, low, close, volume].
        symbol: NSE ticker — included in every rejection record and audit entry.
        config: AppConfig-compatible object; optional circuit_limits dict read from
                config.india.circuit_limits (defaults to 20% if absent or misconfigured).

    Returns:
        (clean_df, rejections): clean_df contains only valid rows with index reset;
        rejections is a list of dicts with keys [symbol, timestamp, reasons].
    """
    if df.empty:
        return df.copy(), []

    audit = AuditTrail()

    # ── Standard checks ────────────────────────────────────────────────────────
    null_mask = df[_REQUIRED_COLUMNS].isnull().any(axis=1)
    zero_vol_mask = df["volume"] == 0
    hl_mask = df["high"] < df["low"]

    prev_close = df["close"].shift(1)
    spike_mask = (
        prev_close.notna() & ((df["close"] / prev_close - 1).abs() > 0.20)
    ).fillna(False)

    ts = pd.to_datetime(df["timestamp"])
    oor_mask = (ts <= ts.shift(1)).fillna(False)

    # ── India-specific: NSE circuit breaker ────────────────────────────────────
    circuit_pct = _get_circuit_pct(symbol, config)
    upper_limit = prev_close * (1.0 + circuit_pct / 100.0)
    lower_limit = prev_close * (1.0 - circuit_pct / 100.0)

    valid_prev = prev_close.notna() & (prev_close > 0)
    upper_circuit_mask = (valid_prev & (df["close"] >= upper_limit - _CIRCUIT_EPSILON)).fillna(False)
    lower_circuit_mask = (valid_prev & (df["close"] <= lower_limit + _CIRCUIT_EPSILON)).fillna(False)

    reject_mask = (
        null_mask
        | zero_vol_mask
        | hl_mask
        | spike_mask
        | oor_mask
        | upper_circuit_mask
        | lower_circuit_mask
    )

    rejections: list[dict[str, Any]] = []
    for idx in df.index[reject_mask]:
        row = df.loc[idx]
        reasons: list[str] = []
        if null_mask.loc[idx]:
            reasons.append("null_field")
        if zero_vol_mask.loc[idx]:
            reasons.append("zero_volume")
        if hl_mask.loc[idx]:
            reasons.append("high_lt_low")
        if spike_mask.loc[idx]:
            reasons.append("price_spike_gt_20pct")
        if oor_mask.loc[idx]:
            reasons.append("out_of_order_timestamp")
        if upper_circuit_mask.loc[idx]:
            reasons.append("upper_circuit_limit")
        if lower_circuit_mask.loc[idx]:
            reasons.append("lower_circuit_limit")

        rejections.append(
            {"symbol": symbol, "timestamp": row["timestamp"], "reasons": reasons}
        )
        _log.warning(f"Rejected bar {symbol} @ {row['timestamp']}: {reasons}")
        audit.append(
            market="india",
            module="validator",
            event_type="REJECTION",
            details={
                "symbol": symbol,
                "timestamp": str(row["timestamp"]),
                "reasons": reasons,
            },
            result="REJECTED",
            reason=f"Bar rejected: {', '.join(reasons)}",
        )

    _log.info(f"Validated {len(df)} bars for {symbol}: {len(rejections)} rejected")
    clean_df = df[~reject_mask].reset_index(drop=True)
    return clean_df, rejections
