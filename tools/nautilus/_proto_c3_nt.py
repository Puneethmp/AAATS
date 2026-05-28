"""Minimal NT engine smoke test — verifies install + data + instruments load.

Use: ``python3 tools/nautilus/_proto_c3_nt.py`` should print "smoke OK" and
the per-symbol bar counts. The real graduation harness is ``run_c3_oos.py``.
"""

# ruff: noqa: E402  — sys.path bootstrap (below) must precede repo-local imports
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import MakerTakerFeeModel, FillModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.currencies import USDT
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.objects import Money
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.wranglers import BarDataWrangler

# Reuse helpers from the real runner so the smoke and the harness stay in sync.
from tools.nautilus.run_c3_oos import UNIVERSE, BTCSYM, VENUE, make_pair, load_df


def main():
    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="C3-SMOKE",
            logging=LoggingConfig(bypass_logging=True),
        )
    )
    engine.add_venue(
        venue=VENUE,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        base_currency=None,
        starting_balances=[Money(100, USDT)],
        fee_model=MakerTakerFeeModel(),
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0, random_seed=7),
    )
    total = 0
    for sym in UNIVERSE + [BTCSYM]:
        inst = make_pair(sym)
        engine.add_instrument(inst)
        bt = BarType.from_str(f"{inst.id}-1-HOUR-LAST-EXTERNAL")
        bars = BarDataWrangler(bt, inst).process(
            load_df(sym), ts_init_delta=(1 if sym == BTCSYM else 0)
        )
        engine.add_data(bars)
        total += len(bars)
        print(f"  {sym}: {len(bars)} bars")
    print(f">>> total bars: {total}")
    print(">>> smoke OK (engine built, instruments + data loaded)")
    engine.dispose()


if __name__ == "__main__":
    main()
