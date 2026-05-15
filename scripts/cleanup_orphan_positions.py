"""
scripts/cleanup_orphan_positions.py  —  Close positions on deny-listed symbols.

Why: the 2026-05-13 fix pack added a universe deny-list (LUNC, PENGU, PEPE,
SHIB, FLOKI, WIF, BONK, DOGE, etc.). Positions opened BEFORE the fix on those
symbols still exist in paper_trades.db and altcoin_reversion_state.json and
cause `reconcile_intracycle` to halt with `symbol_present_in_only_one_source`.

What this does (idempotent, audited):
  1. Loads the deny-list directly from markets.crypto.universe._DENY_LIST.
  2. Queries open positions (positions table + altcoin_reversion_state.json).
  3. For each orphan, fetches current Binance USDT-spot price.
  4. Inserts a SELL row in paper_trades with realistic PnL and an audit note
     (`signal="ORPHAN_CLEANUP_2026_05_13"`).
  5. Removes the row from `positions` table.
  6. Removes the entry from altcoin_reversion_state.json.
  7. Prints a summary and exits 0 (or 1 if anything went wrong mid-cleanup).

DRY-RUN by default. Pass `--apply` to actually mutate state.

Run inside the aaats-paper-crypto container:
  docker exec aaats-paper-crypto python scripts/cleanup_orphan_positions.py --apply
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
DB_PATH = Path(os.environ.get("AAATS_DB_PATH", "/app/data/paper_trades.db"))
STATE_FILE = Path(os.environ.get("AAATS_C3_STATE", "/app/data/altcoin_reversion_state.json"))
SIGNAL_TAG = "ORPHAN_CLEANUP_2026_05_13"


def load_denylist() -> set[str]:
    """Import the deny-list from the source of truth."""
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from markets.crypto.universe import _DENY_LIST
        return set(_DENY_LIST)
    except Exception as e:
        print(f"[WARN] could not import _DENY_LIST ({e}); falling back to manual list")
        return {
            "LUNC", "USTC", "LUNA", "FTT", "SRM",
            "PEPE", "SHIB", "FLOKI", "BONK", "WIF", "MEME", "BABYDOGE",
            "DOGE", "PENGU", "TURBO", "BRETT", "MOG", "POPCAT", "GOAT",
            "NEIRO", "PNUT", "ACT", "MEW", "TRUMP", "PEOPLE", "BOME",
            "WBTC", "WETH", "STETH", "WBETH", "WSTETH", "CBBTC", "TBTC",
            "XMR", "ZEC", "DASH",
        }


def symbol_base(symbol: str) -> str:
    """Extract base asset from 'LUNC/USDT' -> 'LUNC'."""
    return symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()


def fetch_market_price(symbol: str) -> float | None:
    """Get current market price from Binance via ccxt."""
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


def query_db_positions(deny: set[str]) -> list[dict]:
    """Find open positions in `positions` table for deny-listed symbols."""
    if not DB_PATH.exists():
        print(f"[WARN] DB not found: {DB_PATH}")
        return []
    out = []
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "positions" not in tables:
            print(f"[INFO] no 'positions' table — skipping DB query")
            return []
        cols = [r[1] for r in con.execute("PRAGMA table_info(positions)").fetchall()]
        print(f"[INFO] positions columns: {cols}")
        rows = con.execute("SELECT * FROM positions").fetchall()
        for r in rows:
            row = dict(r)
            sym = row.get("symbol") or ""
            if symbol_base(sym) in deny:
                out.append(row)
    finally:
        con.close()
    return out


def query_state_positions(deny: set[str]) -> dict:
    """Find positions in altcoin_reversion_state.json for deny-listed symbols."""
    if not STATE_FILE.exists():
        return {}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] state file unreadable: {e}")
        return {}
    return {
        sym: pos for sym, pos in state.items()
        if isinstance(pos, dict) and symbol_base(sym) in deny
    }


def _paper_trades_columns(con: sqlite3.Connection) -> list[str]:
    """Return actual paper_trades column names. Used to adapt to schema drift."""
    return [r[1] for r in con.execute("PRAGMA table_info(paper_trades)").fetchall()]


def record_sell(symbol: str, current_price: float, entry_price: float,
                size_usd: float, entry_ts: str | None) -> None:
    """Insert a SELL row in paper_trades reflecting a market-price close.

    Schema-adaptive: introspects the actual paper_trades columns at runtime
    and includes any required column we know how to fill (e.g. `value`,
    `value_usd`, etc.). Required-but-unknown columns get a 0 default so the
    insert never crashes — the audit row is preserved.
    """
    shares = round(size_usd / max(entry_price, 1e-12), 8) if entry_price else 0.0
    proceeds = shares * current_price
    pnl = proceeds - size_usd
    pnl_pct = round((pnl / size_usd) * 100, 4) if size_usd else None
    exit_ts = datetime.now(timezone.utc).isoformat()

    # Field map — fields we know how to populate. We insert the intersection
    # of (known_fields) ∩ (actual_columns).
    known = {
        "timestamp":  exit_ts,
        "market":     "crypto",
        "symbol":     symbol,
        "action":     "SELL",
        "shares":     shares,
        "price":      current_price,
        "value":      round(proceeds, 6),       # column required NOT NULL
        "value_usd":  round(proceeds, 6),       # tolerate alt name
        "proceeds":   round(proceeds, 6),       # tolerate alt name
        "pnl":        pnl,
        "signal":     SIGNAL_TAG,
        "regime":     "ORPHAN",
        "strategy":   "C3_altcoin_reversion",
        "entry_time": entry_ts,
        "exit_time":  exit_ts,
        "pnl_pct":    pnl_pct,
        "size_usd":   round(size_usd, 4),
        "note":       f"Orphan cleanup (deny-listed): closed at market {current_price:.6f}",
        "notes":      json.dumps({
            "exit_reason": "orphan_cleanup",
            "entry_price": entry_price,
            "exit_price":  current_price,
            "size_usd":    size_usd,
            "pnl":         pnl,
            "pnl_pct":     pnl_pct,
        }),
    }

    con = sqlite3.connect(str(DB_PATH))
    try:
        actual_cols = _paper_trades_columns(con)
        cols = [c for c in actual_cols if c in known]
        # Pad any NOT-NULL columns we don't know how to fill with a safe default.
        # Inspect schema for NOT NULL constraints to be robust to future migrations.
        ti = con.execute("PRAGMA table_info(paper_trades)").fetchall()
        for col_info in ti:
            cname = col_info[1]
            notnull = col_info[3]   # 1 if NOT NULL
            has_default = col_info[4] is not None
            is_pk = col_info[5] > 0
            if notnull and not has_default and not is_pk and cname not in cols:
                # Unknown required column — fill with a sane default.
                known[cname] = 0
                cols.append(cname)

        placeholders = ",".join("?" * len(cols))
        col_sql = ",".join(cols)
        values = [known[c] for c in cols]

        con.execute(
            f"INSERT INTO paper_trades ({col_sql}) VALUES ({placeholders})",
            values,
        )
        con.commit()
    finally:
        con.close()


def delete_from_positions(symbol: str) -> int:
    """Remove this symbol's row(s) from the `positions` table. Returns rows deleted."""
    con = sqlite3.connect(str(DB_PATH))
    try:
        cur = con.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def remove_from_state(symbol: str) -> bool:
    """Remove this symbol from altcoin_reversion_state.json. Returns True if changed."""
    if not STATE_FILE.exists():
        return False
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    if symbol not in state:
        return False
    del state[symbol]
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually mutate state (default: dry-run preview)")
    args = parser.parse_args()

    deny = load_denylist()
    print(f"[INFO] deny-list size: {len(deny)}")
    print(f"[INFO] DB:    {DB_PATH}  exists={DB_PATH.exists()}")
    print(f"[INFO] STATE: {STATE_FILE}  exists={STATE_FILE.exists()}")
    print(f"[INFO] mode:  {'APPLY (mutating)' if args.apply else 'DRY-RUN (preview only)'}")
    print()

    db_orphans = query_db_positions(deny)
    state_orphans = query_state_positions(deny)

    all_symbols = set()
    by_symbol: dict[str, dict] = {}

    for row in db_orphans:
        sym = row.get("symbol") or ""
        all_symbols.add(sym)
        by_symbol.setdefault(sym, {"db": None, "state": None})
        by_symbol[sym]["db"] = row

    for sym, pos in state_orphans.items():
        all_symbols.add(sym)
        by_symbol.setdefault(sym, {"db": None, "state": None})
        by_symbol[sym]["state"] = pos

    if not all_symbols:
        print("[OK] no orphan positions found — nothing to clean up.")
        return 0

    print(f"[INFO] orphan positions discovered ({len(all_symbols)} symbols):")
    for sym in sorted(all_symbols):
        src = by_symbol[sym]
        markers = []
        if src["db"]:    markers.append("DB")
        if src["state"]: markers.append("STATE")
        print(f"  - {sym:<14}  in: {','.join(markers)}")
    print()

    cleaned = 0
    failed = 0

    for sym in sorted(all_symbols):
        src = by_symbol[sym]
        db_row = src["db"]
        state_pos = src["state"]

        # Resolve entry price + size from whichever source is present
        entry_price = None
        size_usd = None
        entry_ts = None
        if state_pos:
            entry_price = float(state_pos.get("entry_price") or 0)
            size_usd = float(state_pos.get("size_usd") or 0)
            entry_ts = state_pos.get("entry_ts")
        if db_row and (entry_price is None or entry_price <= 0):
            entry_price = float(db_row.get("entry_price") or db_row.get("price") or 0)
            size_usd = float(db_row.get("size_usd") or 0)
            entry_ts = db_row.get("entry_time") or entry_ts

        if not entry_price or entry_price <= 0:
            print(f"[SKIP] {sym}: no usable entry_price in either source")
            failed += 1
            continue

        current_price = fetch_market_price(sym)
        if current_price is None:
            print(f"[SKIP] {sym}: could not fetch current market price")
            failed += 1
            continue

        pnl = (size_usd or 0) * (current_price - entry_price) / entry_price
        print(f"[PLAN] {sym}:  entry=${entry_price:.6f}  current=${current_price:.6f}  "
              f"size=${size_usd:.2f}  est_pnl=${pnl:+.4f}")

        if not args.apply:
            continue

        try:
            record_sell(sym, current_price, entry_price, size_usd or 0, entry_ts)
            db_deleted = delete_from_positions(sym) if db_row else 0
            state_changed = remove_from_state(sym) if state_pos else False
            print(f"[DONE] {sym}: SELL recorded, db_rows_deleted={db_deleted}, "
                  f"state_removed={state_changed}")
            cleaned += 1
        except Exception as e:
            print(f"[FAIL] {sym}: {e}")
            failed += 1

    print()
    print(f"[SUMMARY] planned={len(all_symbols)}  applied={cleaned}  failed/skipped={failed}")
    if not args.apply:
        print("[NOTE] DRY-RUN. Re-run with --apply to mutate.")
        return 0
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
