"""
Anomaly detector for AAATS.

Detects unusual trading activity patterns:
  - Abnormal price spikes (>3σ from mean)
  - Sudden volume surges
  - Unusual win/loss streaks
  - Latency spikes in API responses

Usage:
    from risk.anomaly_detector import AnomalyDetector
    ad = AnomalyDetector()
    anomaly = ad.check_price_anomaly("BTC/USDT", price=51000.0, recent_prices=[...])
    if anomaly:
        skip this trade
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from foundation.logger import get_logger

_log = get_logger("risk", "anomaly_detector")
_DB = Path("data/anomalies.db")


@dataclass
class Anomaly:
    type: str
    symbol: str
    market: str
    severity: str   # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    detail: str
    timestamp: float


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            symbol TEXT NOT NULL,
            market TEXT NOT NULL,
            severity TEXT NOT NULL,
            detail TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_anom_ts ON anomalies(timestamp, severity)")
    conn.commit()


class AnomalyDetector:
    """
    Detects statistical anomalies in price, volume, and system behavior.

    Args:
        z_threshold:  Z-score threshold for price anomalies (default 3.0 = 3σ).
        vol_threshold: Volume multiplier to flag as surge (default 5×).
    """

    def __init__(
        self,
        z_threshold: float = 3.0,
        vol_threshold: float = 5.0,
    ) -> None:
        self._z_thresh = z_threshold
        self._vol_thresh = vol_threshold
        _DB.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(_DB) as conn:
            _init_db(conn)

    def check_price_anomaly(
        self,
        symbol: str,
        price: float,
        recent_prices: list[float],
        market: str = "crypto",
    ) -> Anomaly | None:
        """Detect if current price is a statistical outlier vs recent history."""
        if len(recent_prices) < 10:
            return None
        mean = sum(recent_prices) / len(recent_prices)
        variance = sum((p - mean) ** 2 for p in recent_prices) / len(recent_prices)
        std = variance ** 0.5
        if std == 0:
            return None
        z = abs(price - mean) / std
        if z >= self._z_thresh:
            pct_move = (price - mean) / mean
            severity = "CRITICAL" if z > 5 else "HIGH" if z > 4 else "MEDIUM"
            anomaly = Anomaly(
                type="PRICE_SPIKE",
                symbol=symbol,
                market=market,
                severity=severity,
                detail=f"Price {price:.2f} is {z:.1f}σ from mean {mean:.2f} ({pct_move:+.2%})",
                timestamp=time.time(),
            )
            self._record(anomaly)
            _log.warning(f"ANOMALY [{severity}] {symbol}: {anomaly.detail}")
            return anomaly
        return None

    def check_volume_anomaly(
        self,
        symbol: str,
        volume: float,
        avg_volume: float,
        market: str = "crypto",
    ) -> Anomaly | None:
        """Detect abnormal volume surge."""
        if avg_volume <= 0:
            return None
        ratio = volume / avg_volume
        if ratio >= self._vol_thresh:
            severity = "HIGH" if ratio > 10 else "MEDIUM"
            anomaly = Anomaly(
                type="VOLUME_SURGE",
                symbol=symbol,
                market=market,
                severity=severity,
                detail=f"Volume {volume:.0f} is {ratio:.1f}× avg ({avg_volume:.0f})",
                timestamp=time.time(),
            )
            self._record(anomaly)
            _log.warning(f"ANOMALY [{severity}] {symbol}: {anomaly.detail}")
            return anomaly
        return None

    def check_loss_streak(
        self,
        market: str,
        recent_pnls: list[float],
        max_consecutive_losses: int = 5,
    ) -> Anomaly | None:
        """Detect consecutive losing trades."""
        if not recent_pnls:
            return None
        streak = 0
        for pnl in reversed(recent_pnls):
            if pnl < 0:
                streak += 1
            else:
                break
        if streak >= max_consecutive_losses:
            anomaly = Anomaly(
                type="LOSS_STREAK",
                symbol="PORTFOLIO",
                market=market,
                severity="HIGH",
                detail=f"{streak} consecutive losing trades",
                timestamp=time.time(),
            )
            self._record(anomaly)
            _log.warning(f"ANOMALY [HIGH] {market}: {anomaly.detail}")
            return anomaly
        return None

    def _record(self, anomaly: Anomaly) -> None:
        with sqlite3.connect(_DB) as conn:
            conn.execute(
                "INSERT INTO anomalies (type, symbol, market, severity, detail, timestamp) VALUES (?,?,?,?,?,?)",
                (anomaly.type, anomaly.symbol, anomaly.market, anomaly.severity, anomaly.detail, anomaly.timestamp),
            )

    def get_recent(self, hours: int = 24, severity: str | None = None) -> list[dict]:
        cutoff = time.time() - hours * 3600
        with sqlite3.connect(_DB) as conn:
            if severity:
                rows = conn.execute(
                    "SELECT type, symbol, market, severity, detail, timestamp FROM anomalies WHERE timestamp > ? AND severity=? ORDER BY timestamp DESC",
                    (cutoff, severity),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT type, symbol, market, severity, detail, timestamp FROM anomalies WHERE timestamp > ? ORDER BY timestamp DESC",
                    (cutoff,),
                ).fetchall()
        return [{"type": r[0], "symbol": r[1], "market": r[2], "severity": r[3], "detail": r[4], "timestamp": r[5]} for r in rows]
