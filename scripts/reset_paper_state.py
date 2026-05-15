"""
scripts/reset_paper_state.py  —  Phase 0 clean reset (2026-05-14)
==================================================================

PURPOSE
-------
Bring the paper bot back to a known-clean baseline after the data was
contaminated by universe-drift + source-of-truth bugs (now fixed).

WHAT IT DOES
------------
  1. Reads ALL open positions from strategy state files (data/*_state.json,
     excluding *_cooldown.json).
  2. For each, fetches current Binance market price.
  3. Records a SELL row in paper_trades for each (signal=RESET_2026_05_14)
     with realistic PnL based on entry vs market.
  4. Clears the strategy state files (writes empty {}).
  5. Clears the altcoin_reversion_cooldown.json file.
  6. Clears the positions table in paper_trades.db.
  7. Resets paper_portfolio.json:
        crypto.capital -> $110
        crypto.realized_pnl -> 0
        crypto.total_trades/wins/losses -> 0
  8. Records a single audit row signal=RESET_2026_05_14_COMPLETE marking
     the moment.

DRY-RUN by default. Pass --apply to mutate state.

Run inside aaats-paper-crypto container:
    docker exec aaats-paper-crypto python scripts/reset_paper_state.py
    docker exec aaats-paper-crypto python scripts/reset_paper_state.py --apply

The script is idempotent: if no open positions exist, the cleanup steps
still run safely (clear-already-empty is fine).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(os.environ.get("AAATS_REPO_ROOT", "/app"))
DATA_DIR = Path(os.environ.get("AAATS_DATA_DIR", "/app/data"))
DB_PATH = Path(os.environ.get("AAATS_DB_PATH", "/app/data/paper_trades.db"))
PORTFOLIO_FILE = DATA_DIR / "paper_portfolio.json"

SIGNAL_TAG = "RESET_2026_05_14"
COMPLETE_TAG = "RESET_2026_05_14_COMPLETE"

# Reset capital target (locked doctrine 2026-05-14)
RESET_CAPITAL = {
    "crypto": 110.0,
    "india": 25000.0,
}


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_files() -> list[Path]:
    """Discover all strategy state files (data/*_state.json, excluding cooldown)."""
    if not DATA_DIR.is_dir():
        return []
    out = []
    for f in DATA_DIR.glob("*_state.json"):
        if "cooldown" in f.name:
            continue
        out.append(f)
    return out


def _fetch_market_price(symbol: str) -> float | None:
    """Current price from Binance via ccxt; None if unavailable."""
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True, "timeout": 15000})
        ticker = ex.fetch_ticker(symbol)
        last = ticker.get("last") or ticker.get("close")
        if last is None or last <= 0:
            return None
        return float(last)
    except Exception as e:
        print(f"[WARN] price fetch failed for {symbol}: {e}")
        return None


def _paper_trades_columns(con: sqlite3.Connection) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info(paper_trades)").fetchall()]


def _insert_sell_row(con: sqlite3.Connection,
                     symbol: str, current_price: float, entry_price: float,
                     size_usd: float, entry_ts: str | None,
                     strategy: str) -> None:
    """Schema-adaptive SELL row insert (lessons from cleanup-script bug)."""
    shares = round(size_usd / max(entry_price, 1e-12), 8) if entry_price else 0.0
    proceeds = shares * current_price
    pnl = proceeds - size_usd
    pnl_pct = round((pnl / size_usd) * 100, 4) if size_usd else None
    exit_ts = _now_iso()

    known = {
        "timestamp":  exit_ts,
        "market":     "crypto",
        "symbol":     symbol,
        "action":     "SELL",
        "shares":     shares,
        "price":      current_price,
        "value":      round(proceeds, 6),
        "value_usd":  round(proceeds, 6),
        "proceeds":   round(proceeds, 6),
        "pnl":        pnl,
        "signal":     SIGNAL_TAG,
        "regime":     "RESET",
        "strategy":   strategy,
        "entry_time": entry_ts,
        "exit_time":  exit_ts,
        "pnl_pct":    pnl_pct,
        "size_usd":   round(size_usd, 4),
        "note":       f"Phase-0 reset: closed at market {current_price:.6f}",
        "notes":      json.dumps({
            "exit_reason": "phase0_reset",
            "entry_price": entry_price,
            "exit_price":  current_price,
            "size_usd":    size_usd,
            "pnl":         pnl,
            "pnl_pct":     pnl_pct,
        }),
    }

    actual = _paper_trades_columns(con)
    cols = [c for c in actual if c in known]

    # Pad NOT-NULL columns without defaults that we don't have values for.
    ti = con.execute("PRAGMA table_info(paper_trades)").fetchall()
    for col_info in ti:
        cname = col_info[1]
        notnull = col_info[3]
        has_default = col_info[4] is not None
        is_pk = col_info[5] > 0
        if notnull and not has_default and not is_pk and cname not in cols:
            known[cname] = 0
            cols.append(cname)

    placeholders = ",".join("?" * len(cols))
    col_sql = ",".join(cols)
    values = [known[c] for c in cols]

    con.execute(
        f"INSERT INTO paper_trades ({col_sql}) VALUES ({placeholders})",
        values,
    )


def _clear_state_file(f: Path) -> None:
    tmp = f.with_suffix(".tmp")
    tmp.write_text("{}\n", encoding="utf-8")
    tmp.replace(f)


def _reset_portfolio() -> None:
    """Reset paper_portfolio.json to clean baseline."""
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    for market, capital in RESET_CAPITAL.items():
        data.setdefault(market, {})
        data[market]["capital"] = capital
        data[market]["realized_pnl"] = 0.0
        data[market]["total_trades"] = 0
        data[market]["wins"] = 0
        data[market]["losses"] = 0
        data[market]["total_win_pct"] = 0.0
        data[market]["total_loss_pct"] = 0.0
        data[market]["settlement_queue"] = []

    tmp = PORTFOLIO_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(PORTFOLIO_FILE)


def _clear_positions_table(con: sqlite3.Connection) -> int:
    """Wipe the positions table. Returns rows deleted."""
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "positions" not in tables:
        return 0
    cur = con.execute("DELETE FROM positions")
    return cur.rowcount


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="actually mutate state (default: dry-run)")
    args = p.parse_args()

    print(f"[INFO] mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"[INFO] data dir: {DATA_DIR}")
    print(f"[INFO] db: {DB_PATH}  exists={DB_PATH.exists()}")
    print()

    # 1. Discover positions to close
    plan = []
    for state_file in _state_files():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[WARN] could not read {state_file.name}: {e}")
            continue
        if not isinstance(state, dict) or not state:
            continue

        # Strategy name inferred from file name
        # e.g. altcoin_reversion_state.json -> C3_altcoin_reversion
        stem = state_file.stem.replace("_state", "")
        strategy = f"C3_{stem}" if stem == "altcoin_reversion" else stem

        for symbol, pos in state.items():
            if not isinstance(pos, dict):
                continue
            entry_price = pos.get("entry_price") or 0
            size_usd = pos.get("size_usd") or 0
            if not entry_price or entry_price <= 0:
                print(f"[SKIP] {symbol}: no usable entry_price")
                continue
            plan.append({
                "symbol": symbol,
                "entry_price": float(entry_price),
                "size_usd": float(size_usd),
                "entry_ts": pos.get("entry_ts"),
                "strategy": strategy,
                "state_file": state_file,
            })

    if not plan:
        print("[INFO] no open positions found in strategy state files.")
    else:
        print(f"[INFO] {len(plan)} positions to close:")

    # 2. Fetch prices and preview
    for item in plan:
        price = _fetch_market_price(item["symbol"])
        if price is None:
            print(f"[SKIP] {item['symbol']}: market price unavailable")
            item["current_price"] = None
            continue
        item["current_price"] = price
        size = item["size_usd"]
        entry = item["entry_price"]
        pnl = size * (price - entry) / entry
        item["est_pnl"] = pnl
        print(f"  - {item['symbol']:<14}  entry=${entry:.6f}  current=${price:.6f}  "
              f"size=${size:.2f}  est_pnl=${pnl:+.4f}")

    if not args.apply:
        print()
        print("[NOTE] DRY-RUN. Re-run with --apply to actually:")
        print("       - record SELL rows in paper_trades")
        print("       - clear strategy state files")
        print("       - clear positions table")
        print(f"       - reset paper_portfolio.json (crypto cap -> ${RESET_CAPITAL['crypto']})")
        return 0

    # 3. APPLY
    print()
    print("[APPLY] Starting mutations...")

    closed = 0
    failed = 0
    con = sqlite3.connect(str(DB_PATH))
    try:
        for item in plan:
            if item.get("current_price") is None:
                failed += 1
                continue
            try:
                _insert_sell_row(
                    con,
                    symbol=item["symbol"],
                    current_price=item["current_price"],
                    entry_price=item["entry_price"],
                    size_usd=item["size_usd"],
                    entry_ts=item["entry_ts"],
                    strategy=item["strategy"],
                )
                closed += 1
                print(f"  [DONE] SELL row recorded: {item['symbol']}")
            except Exception as e:
                print(f"  [FAIL] {item['symbol']}: {e}")
                failed += 1

        # 4. Clear positions table
        deleted = _clear_positions_table(con)
        print(f"  [DONE] positions table cleared ({deleted} rows deleted)")

        # 5. Record completion audit row
        try:
            actual = _paper_trades_columns(con)
            completion = {
                "timestamp": _now_iso(),
                "market":    "crypto",
                "symbol":    "*",
                "action":    "RESET",
                "signal":    COMPLETE_TAG,
                "strategy":  "phase0_reset",
                "note":      f"Reset complete. Closed {closed} positions. Reset capital to ${RESET_CAPITAL['crypto']}.",
            }
            # Schema-pad NOT-NULLs
            ti = con.execute("PRAGMA table_info(paper_trades)").fetchall()
            for col_info in ti:
                cname = col_info[1]
                notnull = col_info[3]
                has_default = col_info[4] is not None
                is_pk = col_info[5] > 0
                if notnull and not has_default and not is_pk and cname not in completion:
                    completion[cname] = 0
            cols = [c for c in actual if c in completion]
            placeholders = ",".join("?" * len(cols))
            con.execute(
                f"INSERT INTO paper_trades ({','.join(cols)}) VALUES ({placeholders})",
                [completion[c] for c in cols],
            )
            print(f"  [DONE] audit row recorded ({COMPLETE_TAG})")
        except Exception as e:
            print(f"  [WARN] audit row failed: {e}")

        con.commit()
    finally:
        con.close()

    # 6. Clear state files
    seen_files = {item["state_file"] for item in plan}
    for sf in seen_files:
        try:
            _clear_state_file(sf)
            print(f"  [DONE] cleared {sf.name}")
        except Exception as e:
            print(f"  [WARN] could not clear {sf.name}: {e}")

    # Also clear cooldown file
    cooldown_file = DATA_DIR / "altcoin_reversion_cooldown.json"
    if cooldown_file.exists():
        try:
            _clear_state_file(cooldown_file)
            print(f"  [DONE] cleared {cooldown_file.name}")
        except Exception as e:
            print(f"  [WARN] could not clear cooldown: {e}")

    # 7. Reset portfolio
    try:
        _reset_portfolio()
        print(f"  [DONE] portfolio reset (crypto cap -> ${RESET_CAPITAL['crypto']})")
    except Exception as e:
        print(f"  [FAIL] portfolio reset: {e}")
        return 1

    print()
    print(f"[SUMMARY] closed={closed}  failed/skipped={failed}  capital_reset=${RESET_CAPITAL['crypto']}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
