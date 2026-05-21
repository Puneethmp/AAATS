"""
Tests for production_readiness/metrics_aggregator.py drawdown + uptime calcs.

Pre-fix, the 2026-05-22 readiness scorer wrote -781.0% drawdown and 0.0%
infrastructure uptime into deployment_decision.json. Root cause was:

  1. Drawdown denominator clamped to max(peak, 1.0). When the cum-pnl peak
     is tiny (e.g. $1) and the trough is -$8, the math is -8/1 = -800%.
  2. Uptime was a binary `1.0 if heartbeats else 0.0`. A stale 19-day-old
     heartbeat voted 100% healthy; an empty heartbeat file dropped it to 0%.

These tests pin the corrected behavior. The first three FAIL against the
pre-fix code and PASS against the fix in commit 2026-05-21 A.0.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# --- helpers --------------------------------------------------------------


def _seed_paper_trades(db_path: Path, sell_pnls: list[float]) -> None:
    """Seed a minimal paper_trades.db with SELL rows carrying given pnls."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            pnl REAL,
            risk_action TEXT
        )
        """
    )
    now = datetime.now(timezone.utc)
    for i, pnl in enumerate(sell_pnls):
        conn.execute(
            "INSERT INTO paper_trades(id, timestamp, action, pnl, risk_action) VALUES (?, ?, ?, ?, ?)",
            (f"t{i}", (now - timedelta(days=9 - i)).isoformat(), "SELL", pnl, "ALLOW"),
        )
    conn.commit()
    conn.close()


def _seed_risk_state(state_dir: Path, peak: float, last_equity: float) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "risk_engine_state.json").write_text(
        json.dumps(
            {
                "peak": peak,
                "last_equity": last_equity,
                "market_peaks": {"crypto": peak},
            }
        ),
        encoding="utf-8",
    )


def _seed_heartbeat(data_dir: Path, age_seconds: float, market: str = "crypto") -> None:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    payload = {
        market: {
            "timestamp": ts.isoformat(),
            "market": market,
            "status": "RUNNING",
            "cycle_count": 71,
            "error": "",
        }
    }
    (data_dir / "heartbeat.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def fresh_data_dir(tmp_path, monkeypatch):
    """Build an isolated data dir and rebind heartbeat_monitor + aggregator to it."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Re-bind heartbeat_monitor's module-level singleton so it reads our temp dir.
    from monitoring import heartbeat_monitor as hm

    fresh_monitor = hm.HeartbeatMonitor(data_dir=str(data_dir))
    monkeypatch.setattr(hm, "_monitor", fresh_monitor)

    return data_dir


# --- drawdown -------------------------------------------------------------


class TestDrawdownArithmetic:
    """Drawdown must be in [-1.0, 0.0] under every realistic input."""

    def test_drawdown_uses_risk_engine_state_when_present(self, fresh_data_dir, monkeypatch):
        """Canonical peak/last_equity should be preferred over pnl-curve calc."""
        # The buggy inputs from the box: realized SELLs sum to -$5.76 but the
        # equity peak is $116.53 (mark-to-market) — only the state file knows.
        _seed_paper_trades(fresh_data_dir / "paper_trades.db", [+0.5, +0.5, -11.0])
        _seed_risk_state(fresh_data_dir / "state", peak=116.53, last_equity=101.32)

        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_paper_trading_metrics()

        # Real drawdown is (101.32 - 116.53) / 116.53 = -0.1306
        assert -0.20 < metrics.max_drawdown < -0.05, (
            f"Expected ~-13% drawdown from canonical state; got {metrics.max_drawdown}"
        )
        # Hard ceiling — the -781% legacy bug must never resurface.
        assert -1.0 <= metrics.max_drawdown <= 0.0

    def test_drawdown_clamped_when_no_state_file(self, fresh_data_dir):
        """Fallback pnl-curve path must clamp to [-1.0, 0.0] even with tiny peak."""
        # Pre-fix this produced -10/1 = -1000%. Post-fix the $100 denominator
        # floor + final clamp keeps it inside the contract.
        _seed_paper_trades(fresh_data_dir / "paper_trades.db", [+0.5, +0.5, -11.0])
        # No state file written — exercise the fallback branch.

        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_paper_trading_metrics()

        assert -1.0 <= metrics.max_drawdown <= 0.0, (
            f"Drawdown {metrics.max_drawdown} escaped the [-100%, 0%] contract"
        )

    def test_drawdown_zero_when_no_trades(self, fresh_data_dir):
        """No SELLs, no state → drawdown is 0, not -inf or 0%-collapsed garbage."""
        _seed_paper_trades(fresh_data_dir / "paper_trades.db", [])

        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_paper_trading_metrics()

        assert metrics.max_drawdown == 0.0


# --- uptime ---------------------------------------------------------------


class TestUptimeReflectsFreshness:
    """Uptime must reflect heartbeat freshness, not just presence."""

    def test_uptime_drops_when_heartbeat_is_stale(self, fresh_data_dir):
        """A 4-hour-old heartbeat must NOT vote 100% uptime."""
        # Pre-fix the binary `1.0 if heartbeats else 0.0` returns 100%
        # because the heartbeat *file* exists — staleness is ignored.
        _seed_heartbeat(fresh_data_dir, age_seconds=4 * 3600)

        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_infrastructure_metrics()

        assert metrics.uptime_percentage < 95.0, (
            f"Stale heartbeat should drop uptime below 95%; got {metrics.uptime_percentage}"
        )

    def test_uptime_above_zero_when_heartbeat_is_fresh(self, fresh_data_dir):
        """A fresh heartbeat must produce >0% uptime — not collapse to 0%."""
        _seed_heartbeat(fresh_data_dir, age_seconds=10)

        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_infrastructure_metrics()

        # Pre-fix returns 0% when get_all_heartbeats() reads empty; this test
        # exercises the path where the file exists AND is fresh.
        assert metrics.uptime_percentage > 0.0
        assert metrics.uptime_percentage <= 100.0

    def test_uptime_zero_when_no_heartbeat_file(self, fresh_data_dir):
        """No heartbeat file at all → 0% is the correct answer, not a crash."""
        from production_readiness.metrics_aggregator import MetricsAggregator

        agg = MetricsAggregator(data_dir=str(fresh_data_dir))
        metrics = agg._collect_infrastructure_metrics()

        assert metrics.uptime_percentage == 0.0
