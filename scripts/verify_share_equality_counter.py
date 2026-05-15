"""
One-shot verification (NOT a permanent test) for the share-equality
counter pipeline shipped 2026-05-15.

Setup:
  1. Spin up a temp SQLite DB with the paper_trades schema.
  2. Insert one BUY row (strategy=TEST_S, symbol=TEST/USDT, shares=1.0).
  3. Call paper_trader.record_trade() with action=SELL, shares=2.0 — a
     deliberate mismatch that should fire the WARN branch.
  4. Read data/share_equality_mismatches.json and assert the
     "TEST_S|TEST/USDT" key incremented by exactly 1.

Run:
  venv\\Scripts\\python scripts\\verify_share_equality_counter.py

Exits 0 on PASS, non-zero on FAIL.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from execution.paper_trader import _conn, record_trade  # noqa: E402

COUNTER_PATH = ROOT / "data" / "share_equality_mismatches.json"
STRATEGY = "VERIFY_TEST_S"
SYMBOL = "VERIFY/USDT"
KEY = f"{STRATEGY}|{SYMBOL}"


def _read_counter() -> int:
    if not COUNTER_PATH.exists():
        return 0
    try:
        state = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
        return int(state.get(KEY, 0))
    except Exception:
        return 0


def main() -> int:
    before = _read_counter()
    print(f"[verify] counter before: {KEY} = {before}")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    try:
        # 1. Bootstrap schema + seed one BUY row with shares=1.0 at price=10.0
        c = _conn(db_path)
        c.execute(
            "INSERT INTO paper_trades "
            "(id,timestamp,market,symbol,action,shares,price,value,signal,regime,"
            " risk_action,pnl,note,strategy,entry_time,exit_time,pnl_pct,notes,size_usd,"
            " client_order_id,correlation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "2026-05-15T00:00:00+00:00", "crypto", SYMBOL,
             "BUY", 1.0, 10.0, 10.0, "VERIFY", "TEST", "ALLOW", 0.0, "verify-seed",
             STRATEGY, "2026-05-15T00:00:00+00:00", None, None, None, 10.0,
             f"verify-buy-{uuid.uuid4()}", f"corr-{uuid.uuid4()}"),
        )
        c.commit()
        c.close()

        # 2. Record a deliberately mismatched SELL (shares=2.0 vs BUY's 1.0)
        record_trade(
            db_path=db_path, market="crypto", symbol=SYMBOL,
            action="SELL", shares=2.0, price=11.0,
            signal="VERIFY_EXIT", regime="TEST", risk_action="ALLOW",
            pnl=2.0, strategy=STRATEGY,
            entry_time="2026-05-15T00:00:00+00:00",
            exit_time="2026-05-15T00:01:00+00:00",
            client_order_id=f"verify-sell-{uuid.uuid4()}",
        )

        after = _read_counter()
        print(f"[verify] counter after:  {KEY} = {after}")
        delta = after - before
        if delta == 1:
            print("[verify] PASS — counter incremented by exactly 1 on mismatched SELL")
            # Best-effort clean up our test increment so we don't pollute prod metrics
            try:
                state = json.loads(COUNTER_PATH.read_text(encoding="utf-8"))
                if state.get(KEY, 0) > 0:
                    state[KEY] = state[KEY] - 1
                    if state[KEY] <= 0:
                        state.pop(KEY, None)
                    COUNTER_PATH.write_text(json.dumps(state), encoding="utf-8")
                    print("[verify] cleanup — decremented test key to avoid metric pollution")
            except Exception as e:
                print(f"[verify] cleanup failed (non-fatal): {e}")
            return 0
        else:
            print(f"[verify] FAIL — expected delta=1, got delta={delta}")
            return 1
    finally:
        try:
            pathlib.Path(db_path).unlink()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
