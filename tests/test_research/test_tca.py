"""
Tests for research/tca.py — Transaction Cost Analysis
"""
import pytest
import pandas as pd
from research.tca import Order, TCAResult, TCAAnalyzer, TCAReport


@pytest.fixture
def btc_buy():
    return Order(
        symbol="BTC/USDT",
        side="buy",
        quantity=1.0,
        decision_price=50_000.0,
        execution_price=50_300.0,
        vwap=50_150.0,
        arrival_mid=50_050.0,
        adv=1_000.0,
        sigma=0.025,
        spread_bps=1.0,
    )


@pytest.fixture
def eth_sell():
    return Order(
        symbol="ETH/USDT",
        side="sell",
        quantity=10.0,
        decision_price=3_000.0,
        execution_price=2_985.0,
        vwap=2_990.0,
        arrival_mid=2_998.0,
        adv=5_000.0,
        sigma=0.03,
    )


def test_is_positive_for_buy_above_decision(btc_buy):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(btc_buy)
    assert result.implementation_shortfall_bps > 0, "Buy above decision price → positive IS"


def test_is_positive_for_sell_below_decision(eth_sell):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(eth_sell)
    assert result.implementation_shortfall_bps > 0, "Sell below decision price → positive IS"


def test_vwap_slippage_computed(btc_buy):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(btc_buy)
    assert result.vwap_slippage_bps is not None
    # Buy: exec > VWAP → positive slippage
    assert result.vwap_slippage_bps > 0


def test_arrival_slippage_computed(btc_buy):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(btc_buy)
    assert result.arrival_slippage_bps is not None
    assert result.arrival_slippage_bps > 0


def test_market_impact_uses_sqrt_law(btc_buy):
    """Impact should scale with sqrt of participation rate."""
    analyzer = TCAAnalyzer(impact_eta=0.1)
    r1 = analyzer.analyze(btc_buy)

    # Double the order size → participation doubles → impact ≈ sqrt(2)x
    order2x = Order(
        symbol=btc_buy.symbol,
        side=btc_buy.side,
        quantity=btc_buy.quantity * 2,
        decision_price=btc_buy.decision_price,
        execution_price=btc_buy.execution_price,
        adv=btc_buy.adv,
        sigma=btc_buy.sigma,
        spread_bps=btc_buy.spread_bps,
    )
    r2 = analyzer.analyze(order2x)
    ratio = r2.estimated_market_impact_bps / r1.estimated_market_impact_bps
    assert abs(ratio - (2 ** 0.5)) < 0.05, f"Expected sqrt(2)≈1.41, got {ratio:.3f}"


def test_spread_cost_half_spread(btc_buy):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(btc_buy)
    # spread_bps=1.0 → cost = 0.5 bps
    assert abs(result.estimated_spread_cost_bps - 0.5) < 0.01


def test_total_cost_usd_positive(btc_buy):
    analyzer = TCAAnalyzer()
    result = analyzer.analyze(btc_buy)
    assert result.total_cost_usd > 0


def test_direction_buy():
    order = Order("X", "buy", 1.0, 100.0, 101.0)
    assert order.direction == 1


def test_direction_sell():
    order = Order("X", "sell", 1.0, 100.0, 99.0)
    assert order.direction == -1


def test_participation_rate_capped_at_one():
    order = Order("X", "buy", 1000.0, 100.0, 100.0, adv=10.0)
    assert order.participation_rate == 1.0


def test_pre_trade_estimate_keys():
    analyzer = TCAAnalyzer()
    est = analyzer.estimate_pre_trade(
        symbol="BTC/USDT",
        side="buy",
        quantity=1.0,
        current_price=50_000.0,
        sigma=0.02,
        adv=1_000.0,
        spread_bps=1.0,
    )
    required = {"estimated_total_cost_bps", "estimated_total_cost_usd",
                "breakeven_edge_bps", "advice", "participation_rate_pct"}
    assert required.issubset(set(est.keys()))


def test_pre_trade_high_cost_large_order():
    analyzer = TCAAnalyzer()
    est = analyzer.estimate_pre_trade(
        symbol="ILLIQUID",
        side="buy",
        quantity=500.0,
        current_price=100.0,
        sigma=0.05,
        adv=100.0,
    )
    assert "HIGH COST" in est["advice"]


def test_batch_analysis(btc_buy, eth_sell):
    analyzer = TCAAnalyzer()
    df = pd.DataFrame([
        {
            "symbol": btc_buy.symbol, "side": btc_buy.side,
            "quantity": btc_buy.quantity,
            "decision_price": btc_buy.decision_price,
            "execution_price": btc_buy.execution_price,
            "sigma": btc_buy.sigma, "adv": btc_buy.adv,
        },
        {
            "symbol": eth_sell.symbol, "side": eth_sell.side,
            "quantity": eth_sell.quantity,
            "decision_price": eth_sell.decision_price,
            "execution_price": eth_sell.execution_price,
            "sigma": eth_sell.sigma, "adv": eth_sell.adv,
        },
    ])
    report = analyzer.analyze_batch(df)
    summary = report.summary()
    assert summary["n_trades"] == 2
    assert "avg_is_bps" in summary
    assert "total_cost_usd" in summary
