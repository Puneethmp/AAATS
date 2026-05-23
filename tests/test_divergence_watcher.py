"""Tests for the C3 divergence-watcher in monitoring/daily_digest.py.

Five required cases per the session 10 prompt:
  - test_skips_if_no_day1_marker
  - test_skips_after_7_days
  - test_halts_C3_on_negative_breach
  - test_halts_C3_on_positive_breach
  - test_includes_running_pnl_in_digest_row

The watcher computes cumulative C3 P&L since the d5_day1_marker.json
timestamp and, for the first 7 soak days, halts C3 + pages the
operator if pnl exits the +/-$2 band. After day 7 the watcher
deactivates (becomes a read-only digest annotation).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from execution import paper_trader
from monitoring import daily_digest as dd


# ── Fixtures ──────────────────────────────────────────────────────────────


def _seed_db(db_path: Path) -> None:
    paper_trader._conn(str(db_path)).close()


def _insert_trade(
    db_path: Path,
    *,
    strategy: str,
    pnl: float,
    timestamp: datetime,
) -> None:
    """Bypass dedupe to make test setup straightforward."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO paper_trades "
        "(id, timestamp, market, symbol, action, shares, price, value, "
        " signal, regime, risk_action, pnl, note, strategy, size_usd) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"test-{strategy}-{timestamp.isoformat()}",
            timestamp.isoformat(),
            "crypto", "SOL/USDT", "SELL", 1.0, 100.0, 100.0,
            "test-sig", "test-regime", "ALLOW", float(pnl), "test",
            strategy, 100.0,
        ),
    )
    conn.commit()
    conn.close()


def _write_marker(
    data_dir: Path,
    *,
    day1_at: datetime,
    armed: bool = True,
    window_days: int = 7,
    low: float = -2.0,
    high: float = 2.0,
) -> None:
    marker = {
        "day1_at": day1_at.isoformat(),
        "starting_equity_usd": 200.0,
        "divergence_watcher_armed": armed,
        "watcher_window_days": window_days,
        "c3_threshold_low_usd": low,
        "c3_threshold_high_usd": high,
    }
    (data_dir / "d5_day1_marker.json").write_text(
        json.dumps(marker, indent=2), encoding="utf-8"
    )


@pytest.fixture
def cfg(tmp_path: Path) -> dd.DigestConfig:
    db = tmp_path / "paper_trades.db"
    _seed_db(db)
    return dd.DigestConfig.from_data_dir(tmp_path)


# ── 1. Skip when marker absent ────────────────────────────────────────────


def test_skips_if_no_day1_marker(cfg: dd.DigestConfig) -> None:
    """No d5_day1_marker.json -> watcher returns None (dormant); no
    digest row, no side effects."""
    halt_calls: list[Any] = []
    alert_calls: list[Any] = []

    def fake_halt(*a: Any, **kw: Any) -> None:
        halt_calls.append((a, kw))

    def fake_alert(*a: Any, **kw: Any) -> None:
        alert_calls.append((a, kw))

    result = dd.enforce_c3_divergence_watcher(
        cfg,
        as_of=datetime(2026, 5, 26, tzinfo=timezone.utc),
        halt_strategy_fn=fake_halt,
        send_alert_fn=fake_alert,
    )
    assert result is None
    assert halt_calls == []
    assert alert_calls == []
    assert dd.render_watcher_row(result) is None


# ── 2. Skip after 7 days ─────────────────────────────────────────────────


def test_skips_after_7_days(cfg: dd.DigestConfig) -> None:
    """day1 + 8 days -> within_window False; threshold breaches don't
    halt; row says watcher inactive."""
    day1 = datetime(2026, 5, 25, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1)

    # Insert a massively breaching loss (-$50) — would fire if within window.
    _insert_trade(cfg.db_path, strategy="C3_altcoin_reversion",
                  pnl=-50.0, timestamp=day1 + timedelta(hours=12))

    halt_calls: list[Any] = []

    def fake_halt(*a: Any, **kw: Any) -> None:
        halt_calls.append((a, kw))

    result = dd.enforce_c3_divergence_watcher(
        cfg,
        as_of=day1 + timedelta(days=8),
        halt_strategy_fn=fake_halt,
        send_alert_fn=lambda *a, **kw: None,
    )

    assert result is not None
    assert result["within_window"] is False
    assert result["days_into_watcher"] == 8
    assert halt_calls == [], "must NOT halt C3 after window expires"

    row = dd.render_watcher_row(result)
    assert row is not None
    assert "watcher inactive" in row


# ── 3 + 4. Halt on negative / positive breach ───────────────────────────────


def test_halts_C3_on_negative_breach(cfg: dd.DigestConfig) -> None:
    """Cumulative C3 P&L < -$2 within window -> halt fires + pager sent."""
    day1 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1)

    # -$3.50 cumulative C3 loss in 4 trades.
    for i, p in enumerate([-1.0, -1.0, -1.0, -0.5]):
        _insert_trade(cfg.db_path, strategy="C3_altcoin_reversion",
                      pnl=p, timestamp=day1 + timedelta(hours=i + 1))

    halt_calls: list[Any] = []
    alert_calls: list[Any] = []

    def fake_halt(*a: Any, **kw: Any) -> None:
        halt_calls.append((a, kw))

    def fake_alert(*a: Any, **kw: Any) -> None:
        alert_calls.append((a, kw))

    result = dd.enforce_c3_divergence_watcher(
        cfg,
        as_of=day1 + timedelta(hours=5),
        halt_strategy_fn=fake_halt,
        send_alert_fn=fake_alert,
    )

    assert result is not None
    assert result["pnl_since_day1_usd"] == pytest.approx(-3.5)
    assert result["threshold_breach"] == "low"

    assert len(halt_calls) == 1
    halt_args, halt_kwargs = halt_calls[0]
    assert halt_args[0] == "C3_altcoin_reversion"
    halt_reason = halt_kwargs.get("reason", "") or (halt_args[1] if len(halt_args) > 1 else "")
    assert "divergence-watcher" in halt_reason
    assert "$-3.50" in halt_reason

    assert len(alert_calls) == 1
    alert_args, alert_kwargs = alert_calls[0]
    msg = alert_args[0] if alert_args else alert_kwargs.get("message", "")
    assert "[PAGER]" in msg
    assert alert_kwargs.get("severity") == "critical"


def test_halts_C3_on_positive_breach(cfg: dd.DigestConfig) -> None:
    """Cumulative C3 P&L > +$2 within window -> halt fires too. The
    positive breach is just as 'we cannot trust this' as a negative
    breach (would mean the strategy is wildly outperforming the
    backtest)."""
    day1 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1)

    for i, p in enumerate([1.5, 1.0, 0.75]):
        _insert_trade(cfg.db_path, strategy="C3_altcoin_reversion",
                      pnl=p, timestamp=day1 + timedelta(hours=i + 1))

    halt_calls: list[Any] = []
    alert_calls: list[Any] = []

    result = dd.enforce_c3_divergence_watcher(
        cfg,
        as_of=day1 + timedelta(days=2),
        halt_strategy_fn=lambda *a, **kw: halt_calls.append((a, kw)),
        send_alert_fn=lambda *a, **kw: alert_calls.append((a, kw)),
    )

    assert result is not None
    assert result["pnl_since_day1_usd"] == pytest.approx(3.25)
    assert result["threshold_breach"] == "high"

    assert len(halt_calls) == 1
    assert halt_calls[0][0][0] == "C3_altcoin_reversion"
    assert len(alert_calls) == 1
    msg = alert_calls[0][0][0]
    assert "[PAGER]" in msg
    assert "+3.25" in msg or "$+3.25" in msg


# ── 5. Digest row includes running pnl ────────────────────────────────────


def test_includes_running_pnl_in_digest_row(cfg: dd.DigestConfig) -> None:
    """build_digest output contains the watcher row with the current
    cumulative C3 P&L."""
    day1 = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1)

    # +$0.75 cumulative — inside the threshold band so no halt; the
    # row must still appear with the running value.
    _insert_trade(cfg.db_path, strategy="C3_altcoin_reversion",
                  pnl=0.75, timestamp=day1 + timedelta(hours=2))

    body = dd.build_digest(cfg, as_of=day1 + timedelta(hours=6))

    assert "C3 P&L since day-1: $+0.75" in body
    assert "watcher active" in body
    assert "days 0/7" in body


# ── Bonus: dormant marker keeps watcher dormant ─────────────────────────


def test_dormant_marker_is_dormant(cfg: dd.DigestConfig) -> None:
    """A failed-reset marker (divergence_watcher_armed=False) must
    leave the watcher dormant even if the day1_at field exists."""
    day1 = datetime(2026, 5, 25, tzinfo=timezone.utc)
    _write_marker(cfg.data_dir, day1_at=day1, armed=False)

    halt_calls: list[Any] = []
    result = dd.enforce_c3_divergence_watcher(
        cfg,
        as_of=day1 + timedelta(hours=4),
        halt_strategy_fn=lambda *a, **kw: halt_calls.append(a),
        send_alert_fn=lambda *a, **kw: None,
    )
    assert result is None
    assert halt_calls == []
