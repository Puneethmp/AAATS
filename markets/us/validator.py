"""
US market bar validator.
Rejects bars with null fields, zero volume, high < low, price spikes > 20%,
or out-of-order timestamps. Rejected bars are logged to the audit trail as
REJECTION events and never stored.
"""

from typing import Any

import pandas as pd

from foundation.audit_trail import AuditTrail
from foundation.logger import get_logger

_log = get_logger("us", "validator")

_REQUIRED_COLUMNS: list[str] = ["timestamp", "open", "high", "low", "close", "volume"]


def validate_bars(
    df: pd.DataFrame,
    symbol: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """
    Validate OHLCV bars for a US equity symbol.

    Rejects bars with any of:
    - Null value in any required column
    - volume == 0
    - high < low
    - |close / prev_close - 1| > 0.20 (price spike)
    - timestamp not strictly greater than the previous bar's timestamp

    Args:
        df:     DataFrame with columns [timestamp, open, high, low, close, volume].
        symbol: Ticker symbol — included in every rejection record and audit entry.

    Returns:
        (clean_df, rejections): clean_df contains only valid rows with index reset;
        rejections is a list of dicts with keys [symbol, timestamp, reasons].
    """
    if df.empty:
        return df.copy(), []

    audit = AuditTrail()

    null_mask = df[_REQUIRED_COLUMNS].isnull().any(axis=1)
    zero_vol_mask = df["volume"] == 0
    hl_mask = df["high"] < df["low"]

    prev_close = df["close"].shift(1)
    spike_mask = (
        prev_close.notna() & ((df["close"] / prev_close - 1).abs() > 0.20)
    ).fillna(False)

    ts = pd.to_datetime(df["timestamp"])
    oor_mask = (ts <= ts.shift(1)).fillna(False)

    reject_mask = null_mask | zero_vol_mask | hl_mask | spike_mask | oor_mask

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

        rejections.append(
            {"symbol": symbol, "timestamp": row["timestamp"], "reasons": reasons}
        )
        _log.warning(f"Rejected bar {symbol} @ {row['timestamp']}: {reasons}")
        audit.append(
            market="us",
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
