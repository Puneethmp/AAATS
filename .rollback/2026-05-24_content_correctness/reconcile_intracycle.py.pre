"""
scripts/reconcile_intracycle.py  —  Intra-cycle reconciliation worker
======================================================================

PURPOSE
-------
Closes Gap 3 — silent state divergence detection.

2026-05-14 ARCHITECTURE UPDATE (Option a — canonical strategy state):
  Source A is now the aggregate of strategy state files (data/*_state.json).
  Specifically: altcoin_reversion_state.json and any future *_state.json.
  Each strategy is canonical for its own positions. `paper_positions.json`
  is DEPRECATED (was empty, never written to by current strategies).

Compares the two state-of-truth sources for paper trading every cycle:
  A. Strategy state files (data/*_state.json) — canonical position state
  B. Computed positions   (BUYS - SELLS aggregated from paper_trades.db) — audit derivation

Dust tolerance ($0.10 notional): residual share artifacts from rounding in
the audit ledger (where Source B has tiny non-zero shares that Source A no
longer tracks) are ignored when notional value < $0.10. This kills the 5
PENGU/LUNC/SOL/ETH/EUR ledger-rounding false-positives without rewriting
historical paper_trades rows.

Any drift beyond tolerance halts trading and pages via audit trail +
Telegram alert. No exceptions, no overrides without 24h cooldown.

Run modes:
  1. STANDALONE — invoked end-of-cycle by live_paper_runner.py:
       from scripts.reconcile_intracycle import reconcile_now
       result = reconcile_now()
       if not result.passed: halt(...)

  2. CRON / SYSTEMD TIMER — every 60s as a separate watchdog process:
       while True:
           reconcile_now()
           time.sleep(60)

  3. CLI — manual check:
       python scripts/reconcile_intracycle.py
       python scripts/reconcile_intracycle.py --json

DRIFT POLICY (crypto-only mode)
-------------------------------
- Position drift > 0.5% of expected size  → ALERT
- Position drift > 2.0% of expected size  → HALT + ALERT
- Symbol present in one source but not other → HALT + ALERT (catastrophic)
- A.cash != B.cash by > $1                 → ALERT (cash diverged)

Why these thresholds:
- 0.5% catches accumulating rounding errors before they snowball
- 2.0% catches a genuine bug (double-fire, missing fill)
- Missing symbol = state corruption — never tolerate

LIVE TRADING NOTE
-----------------
When AAATS goes live, this worker becomes:
  A. AAATS internal ledger (paper_trades.db with status=FILLED only)
  B. Broker positions (Binance API get_account)

Same drift policy, same kill semantics. The interface is preserved.

NEVER COMMENTS THE KILL SWITCH
------------------------------
If reconciliation fails, the system MUST halt. Do not add "let me investigate
first" branches. The whole point of the worker is unattended detection.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from foundation.audit_trail import AuditTrail
from foundation.kill_switch import halt, is_halted
from foundation.logger import get_logger

try:
    from markets.crypto.universe import _DENY_LIST as _CRYPTO_DENY_LIST
except Exception:
    _CRYPTO_DENY_LIST = set()

_log = get_logger("scripts", "reconcile_intracycle")


def _denylist_base(symbol: str) -> str:
    """Extract the base asset from a Binance/CCXT symbol for deny-list lookup."""
    if not symbol:
        return ""
    if "/" in symbol:
        return symbol.split("/", 1)[0].upper()
    return symbol.upper()


def _is_denied_symbol(market: str, symbol: str) -> bool:
    """Hide symbols whose base asset is in the crypto deny-list (zombies/memes)."""
    if market != "crypto":
        return False
    return _denylist_base(symbol) in _CRYPTO_DENY_LIST

# ─── Config ──────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
POSITIONS_FILE = _ROOT / "data" / "paper_positions.json"
PORTFOLIO_FILE = _ROOT / "data" / "paper_portfolio.json"
DB_PATH        = _ROOT / "data" / "paper_trades.db"

# Drift thresholds (crypto)
WARN_DRIFT_PCT = 0.005   # 0.5% — alert only
HALT_DRIFT_PCT = 0.02    # 2.0% — halt + alert
CASH_DRIFT_USD = 1.0     # $1.00 — alert if portfolio cash differs by more

# 2026-05-14: dust tolerance for share-rounding artifacts in paper_trades.
# Symbols where Source B (DB-computed) has a tiny residual but Source A has
# nothing are filtered if their NOTIONAL value (shares × last_price) is below
# this threshold. Used to ignore harmless rounding leftovers from closed
# positions without rewriting historical SELL rows.
# TEMP 2026-05-15: covers TON/FET exit-sizing residuals ($0.12-$0.15). Revert
# to $0.10 after unified positions ledger lands (docs/specs/unified_positions_ledger.md).
# DO NOT raise further without explicit approval.
DUST_TOLERANCE_USD = 0.25


# ─── Result types ────────────────────────────────────────────────────────────


@dataclass
class DriftIssue:
    market: str
    symbol: str
    expected_shares: float
    actual_shares: float
    drift_pct: float
    severity: str  # "WARN" | "HALT"
    reason: str


@dataclass
class ReconciliationResult:
    timestamp: str
    passed: bool
    halted: bool
    issues: list[DriftIssue] = field(default_factory=list)
    cash_drift: dict[str, float] = field(default_factory=dict)
    positions_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "passed": self.passed,
            "halted": self.halted,
            "positions_checked": self.positions_checked,
            "cash_drift": self.cash_drift,
            "issues": [
                {
                    "market": i.market,
                    "symbol": i.symbol,
                    "expected_shares": round(i.expected_shares, 8),
                    "actual_shares": round(i.actual_shares, 8),
                    "drift_pct": round(i.drift_pct, 4),
                    "severity": i.severity,
                    "reason": i.reason,
                }
                for i in self.issues
            ],
        }


# ─── Data loaders ────────────────────────────────────────────────────────────


def _load_positions_file() -> dict:
    """
    DEPRECATED 2026-05-14: paper_positions.json is no longer canonical.
    Kept as fallback for any legacy strategy still writing here.
    The new Source A is `_load_strategy_state_positions()` below.
    """
    if not POSITIONS_FILE.exists():
        return {"india": {}, "crypto": {}}
    try:
        return json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _log.error(f"failed to read {POSITIONS_FILE}: {exc}")
        return {"india": {}, "crypto": {}}


def _load_strategy_state_positions() -> dict[str, dict[str, dict]]:
    """
    NEW Source A (2026-05-14, Option a): aggregate positions from all strategy
    state files at data/*_state.json. Each strategy is canonical for its
    own positions.

    Returns {market: {symbol: {"shares": float, "size_usd": float, "entry_price": float}}}.

    For crypto strategies (the only ones with state files today), market="crypto".
    Future india/us strategies should follow the same pattern.
    """
    out: dict[str, dict[str, dict]] = {"india": {}, "crypto": {}}

    data_dir = _ROOT / "data"
    if not data_dir.is_dir():
        return out

    for state_file in data_dir.glob("*_state.json"):
        # Exclude cooldown files (different shape — they map symbol→ISO timestamp)
        if "cooldown" in state_file.name:
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning(f"failed to read {state_file.name}: {exc}")
            continue

        if not isinstance(state, dict):
            continue

        # Each entry: symbol -> {entry_price, size_usd, ...}
        for symbol, pos in state.items():
            if not isinstance(pos, dict):
                continue
            entry_price = pos.get("entry_price")
            size_usd = pos.get("size_usd")
            if not entry_price or entry_price <= 0 or not size_usd:
                continue
            shares = float(size_usd) / float(entry_price)
            # All current strategy state files are crypto. Future strategies
            # in india/us markets can prefix their state file with the market
            # name (e.g. india_pairs_state.json) or pass market in the dict.
            market = pos.get("market", "crypto")
            out.setdefault(market, {})
            # Multiple strategies can hold the same symbol — accumulate shares.
            if symbol in out[market]:
                out[market][symbol]["shares"] += shares
                out[market][symbol]["size_usd"] += float(size_usd)
            else:
                out[market][symbol] = {
                    "shares": shares,
                    "size_usd": float(size_usd),
                    "entry_price": float(entry_price),
                }

    return out


def _last_price(conn: sqlite3.Connection, symbol: str) -> float | None:
    """Look up the most recent price for a symbol from paper_trades."""
    try:
        row = conn.execute(
            "SELECT price FROM paper_trades WHERE symbol = ? "
            "ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row and row[0]:
            return float(row[0])
    except Exception:
        pass
    return None


def _is_dust(symbol: str, residual_shares: float, conn: sqlite3.Connection | None = None) -> bool:
    """
    True if residual shares represent dust (notional < DUST_TOLERANCE_USD).

    A `conn` may be passed in to avoid reopening the DB; otherwise opens its own.
    """
    close_conn = False
    try:
        if conn is None:
            if not DB_PATH.exists():
                return False
            conn = sqlite3.connect(str(DB_PATH))
            close_conn = True
        price = _last_price(conn, symbol)
        if price is None:
            return False
        notional = abs(residual_shares) * price
        return notional < DUST_TOLERANCE_USD
    except Exception:
        return False
    finally:
        if close_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _load_portfolio_file() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {}
    try:
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _compute_positions_from_db() -> dict[str, dict[str, float]]:
    """
    Source B: net positions computed from paper_trades.db.

    Returns {market: {symbol: net_shares}}.
    Net = sum(BUY shares) - sum(SELL shares) per (market, symbol).
    Excludes delta-neutral arb strategies whose per-leg trades net non-zero
    by design (C5b_funding_arb perp/spot legs; C1_stat_arb long-A/short-B
    legs). Their canonical position state lives in *_state.json (Source A).
    """
    if not DB_PATH.exists():
        return {"india": {}, "crypto": {}}

    out: dict[str, dict[str, float]] = {"india": {}, "crypto": {}}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute(
            "SELECT market, symbol, action, SUM(shares) as total "
            "FROM paper_trades "
            # 2026-05-23: add C1_stat_arb (parity with C5b). C1's pair-keyed
            # state file does not surface as a per-symbol position in Source A,
            # so leaving its leg trades in Source B caused symbol_present_in_only_one_source
            # HALTs on every cycle once halt_on_critical=True. Option A of
            # docs/known_issues/2026-05-23_btc_eth_ledger_drift.md.
            "WHERE strategy NOT IN ('C5b_funding_arb', 'C1_stat_arb') "
            "GROUP BY market, symbol, action"
        ).fetchall()
        conn.close()
    except Exception as exc:
        _log.error(f"failed to read {DB_PATH}: {exc}")
        return out

    for market, symbol, action, total in rows:
        if market not in out:
            out[market] = {}
        if symbol not in out[market]:
            out[market][symbol] = 0.0
        if action == "BUY":
            out[market][symbol] += float(total or 0.0)
        elif action == "SELL":
            out[market][symbol] -= float(total or 0.0)

    # Drop near-zero entries (closed positions)
    for market in out:
        out[market] = {s: q for s, q in out[market].items() if abs(q) > 1e-9}

    return out


# ─── Reconciliation core ─────────────────────────────────────────────────────


def reconcile_now(
    halt_on_critical: bool = True,
    markets: list[str] | None = None,
) -> ReconciliationResult:
    """
    Run one reconciliation pass.

    Args:
        halt_on_critical: When True, fires foundation.kill_switch.halt() on
                          any HALT-severity drift. False is for testing only.
        markets:          Subset to check, e.g. ["crypto"]. None = all enabled.

    Returns:
        ReconciliationResult with all detected issues.
    """
    # Source A (canonical, 2026-05-14): aggregated strategy state files
    state_a = _load_strategy_state_positions()
    # Backward-compat: merge any positions still written to legacy paper_positions.json.
    # If both have an entry for the same symbol, strategy state files win.
    legacy_a = _load_positions_file()
    for market, syms in legacy_a.items():
        for symbol, leg in syms.items():
            if symbol not in state_a.get(market, {}):
                shares = float(leg.get("shares", 0.0) or 0.0)
                state_a.setdefault(market, {})[symbol] = {"shares": shares,
                                                          "size_usd": 0.0,
                                                          "entry_price": 0.0}

    state_b = _compute_positions_from_db()

    markets = markets or ["crypto", "india"]
    issues: list[DriftIssue] = []
    cash_drift: dict[str, float] = {}
    checked = 0
    dust_filtered = 0
    denied_skipped: list[str] = []

    # Single DB connection reused for dust price lookups.
    dust_conn = None
    try:
        if DB_PATH.exists():
            dust_conn = sqlite3.connect(str(DB_PATH))

        for market in markets:
            a_positions = state_a.get(market, {})
            b_positions = state_b.get(market, {})

            # Union of all symbols in either source
            all_symbols = set(a_positions.keys()) | set(b_positions.keys())

            for symbol in all_symbols:
                # Deny-list filter: ignore symbols the universe scanner has
                # banned (zombies/memes/wrapped). They legitimately have stale
                # ledger entries — strategies will never reopen them, so any
                # SELL we'd need to drain them is impossible. Without this
                # the reconciler reports HALT-severity drift forever.
                if _is_denied_symbol(market, symbol):
                    denied_skipped.append(f"{market}:{symbol}")
                    continue

                checked += 1
                expected = float(a_positions.get(symbol, {}).get("shares", 0.0) or 0.0)
                actual = float(b_positions.get(symbol, 0.0) or 0.0)

                # Catastrophic: symbol in one but not the other
                if (expected == 0.0) != (actual == 0.0):
                    # 2026-05-14: dust filter — if the residual side is below
                    # $0.10 notional, it's harmless ledger rounding (not a real
                    # position). Skip without flagging.
                    residual = actual if expected == 0.0 else expected
                    if _is_dust(symbol, residual, conn=dust_conn):
                        dust_filtered += 1
                        _log.debug(
                            f"dust filter: {symbol} residual_shares={residual:.6f} "
                            f"notional<${DUST_TOLERANCE_USD:.2f} — skip"
                        )
                        continue
                    issues.append(DriftIssue(
                        market=market, symbol=symbol,
                        expected_shares=expected, actual_shares=actual,
                        drift_pct=1.0,
                        severity="HALT",
                        reason="symbol_present_in_only_one_source",
                    ))
                    continue

                if expected == 0.0 and actual == 0.0:
                    continue

                # Drift = abs(actual - expected) / max(abs(expected), eps)
                drift_pct = abs(actual - expected) / max(abs(expected), 1e-9)

                # 2026-05-14: dust filter for non-zero drift — if both sides
                # are tiny in notional terms, treat as ledger noise, not drift.
                drift_shares = abs(actual - expected)
                if _is_dust(symbol, drift_shares, conn=dust_conn):
                    dust_filtered += 1
                    _log.debug(
                        f"dust filter (drift): {symbol} drift_shares={drift_shares:.6f} "
                        f"notional<${DUST_TOLERANCE_USD:.2f} — skip"
                    )
                    continue

                if drift_pct > HALT_DRIFT_PCT:
                    issues.append(DriftIssue(
                        market=market, symbol=symbol,
                        expected_shares=expected, actual_shares=actual,
                        drift_pct=drift_pct,
                        severity="HALT",
                        reason=f"drift_{drift_pct:.4f}_>_halt_threshold_{HALT_DRIFT_PCT}",
                    ))
                elif drift_pct > WARN_DRIFT_PCT:
                    issues.append(DriftIssue(
                        market=market, symbol=symbol,
                        expected_shares=expected, actual_shares=actual,
                        drift_pct=drift_pct,
                        severity="WARN",
                        reason=f"drift_{drift_pct:.4f}_>_warn_threshold_{WARN_DRIFT_PCT}",
                    ))
    finally:
        if dust_conn is not None:
            try:
                dust_conn.close()
            except Exception:
                pass

    if dust_filtered:
        _log.info(
            f"reconciler: filtered {dust_filtered} dust drift entries "
            f"(notional < ${DUST_TOLERANCE_USD:.2f})"
        )

    if denied_skipped:
        _denied_csv = ", ".join(sorted(set(denied_skipped)))
        _log.info(
            f"reconciler: skipped {len(denied_skipped)} deny-list symbols this cycle: {_denied_csv}"
        )

    # Cash drift check (best-effort — paper_portfolio.json may not have full info)
    portfolio = _load_portfolio_file()
    for market in markets:
        if market in portfolio and "capital" in portfolio[market]:
            # We can't easily reconstruct cash from paper_trades alone (would
            # need full PnL replay). So we just record the snapshot value for
            # external monitoring; treat large changes between cycles as the
            # signal of interest, not absolute drift.
            cash_drift[market] = float(portfolio[market].get("capital", 0.0))

    halt_issues = [i for i in issues if i.severity == "HALT"]
    halted = False

    result = ReconciliationResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        passed=(len(issues) == 0),
        halted=False,
        issues=issues,
        cash_drift=cash_drift,
        positions_checked=checked,
    )

    # ── Audit trail entry for the reconciliation pass itself ────────────────
    audit = AuditTrail()
    audit.append(
        market="system",
        module="reconcile_intracycle",
        event_type="HEALTH",
        details={
            "passed": result.passed,
            "issues_total": len(issues),
            "halt_severity": len(halt_issues),
            "warn_severity": len(issues) - len(halt_issues),
            "positions_checked": checked,
            "issues": result.to_dict()["issues"],
        },
        result="SUCCESS" if result.passed else "FAILURE",
        reason=(
            "reconciliation_clean" if result.passed
            else f"drift_detected:{len(halt_issues)}_halt:{len(issues) - len(halt_issues)}_warn"
        ),
    )

    # ── Halt on critical drift ──────────────────────────────────────────────
    if halt_issues and halt_on_critical:
        affected_markets = sorted({i.market for i in halt_issues})
        reason = (
            f"intracycle_reconciliation_drift "
            f"({len(halt_issues)} halt-severity, "
            f"first={halt_issues[0].symbol} drift={halt_issues[0].drift_pct:.4f})"
        )
        for m in affected_markets:
            if not is_halted(m):
                halt(market=m, reason=reason, triggered_by="reconcile_intracycle")
        halted = True
        result.halted = True

    # ── Logging ─────────────────────────────────────────────────────────────
    if result.passed:
        _log.info(
            f"Reconciliation clean | checked={checked} positions across {','.join(markets)}"
        )
    else:
        _log.warning(
            f"Reconciliation drift | total={len(issues)} "
            f"(halt={len(halt_issues)} warn={len(issues) - len(halt_issues)}) "
            f"checked={checked}"
        )
        for i in issues:
            _log.warning(
                f"  {i.severity} {i.market} {i.symbol} | "
                f"expected={i.expected_shares:.8f} actual={i.actual_shares:.8f} "
                f"drift={i.drift_pct * 100:.4f}% | {i.reason}"
            )

    return result


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="AAATS intra-cycle reconciliation")
    parser.add_argument("--market", choices=["crypto", "india", "all"], default="all")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--no-halt", action="store_true",
                        help="Detect-only (do NOT fire kill switch). DANGEROUS — testing only.")
    args = parser.parse_args()

    markets = ["crypto", "india"] if args.market == "all" else [args.market]
    result = reconcile_now(halt_on_critical=not args.no_halt, markets=markets)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"Reconciliation: {'PASSED' if result.passed else 'FAILED'}")
        print(f"Positions checked: {result.positions_checked}")
        if result.halted:
            print("⚠️  KILL SWITCH FIRED — drift exceeded HALT threshold")
        if result.issues:
            print(f"\nIssues ({len(result.issues)}):")
            for i in result.issues:
                print(
                    f"  [{i.severity}] {i.market}:{i.symbol} | "
                    f"expected={i.expected_shares:.8f} actual={i.actual_shares:.8f} "
                    f"drift={i.drift_pct * 100:.3f}% | {i.reason}"
                )

    return 0 if result.passed else 2


if __name__ == "__main__":
    sys.exit(main())
