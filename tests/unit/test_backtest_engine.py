from datetime import datetime

import pandas as pd
import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.backtesting.synthetic import generate_ohlcv
from src.core.models import AssetType, Instrument, Order, OrderSide, OrderType

START, END = datetime(2023, 1, 2), datetime(2023, 1, 31)


def bars(seed=1, start_price=100.0):
    return generate_ohlcv(start="2023-01-02", end="2023-01-31", start_price=start_price, seed=seed)


def engine(initial_capital=100_000.0):
    return BacktestEngine(BacktestConfig(
        start_date=START, end_date=END, initial_capital=initial_capital,
        commission=0.001, slippage=0.0005,
    ))


def buy_once(symbol, quantity):
    """Strategy that submits one market buy on the first bar."""
    submitted = []

    async def strategy(timestamp, market_data, portfolio):
        if submitted:
            return []
        submitted.append(timestamp)
        return [Order(id="", instrument=Instrument(symbol, AssetType.EQUITY, "NYSE"),
                      side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=quantity)]

    return strategy


def test_synthetic_bars_are_deterministic_and_consistent():
    first, second = generate_ohlcv(seed=7), generate_ohlcv(seed=7)

    pd.testing.assert_frame_equal(first, second)
    assert not first.equals(generate_ohlcv(seed=8))
    assert (first["low"] <= first[["open", "close"]].min(axis=1)).all()
    assert (first["high"] >= first[["open", "close"]].max(axis=1)).all()
    assert (first["open"].iloc[1:].to_numpy() == first["close"].iloc[:-1].to_numpy()).all()


async def test_fills_update_cash_and_equity_curve():
    data = bars()
    backtest = engine()

    result = await backtest.run_backtest(buy_once("AAPL", 100), {"AAPL": data})

    fill = backtest.trades[0]
    # Ordered on bar 0, filled at bar 1's close plus slippage.
    assert fill.price == pytest.approx(data["close"].iloc[1] * 1.0005)
    assert fill.commission == pytest.approx(100 * fill.price * 0.001)
    cash = 100_000 - 100 * fill.price - fill.commission
    assert backtest.portfolio.cash == pytest.approx(cash)
    # Equity on the fill bar is cash + position value, not initial capital + position value.
    assert result.pnl_series.iloc[1] == pytest.approx(cash + 100 * data["close"].iloc[1])
    assert result.final_capital == pytest.approx(cash + 100 * data["close"].iloc[-1])
    assert result.total_trades == 1


async def test_orders_fill_against_their_own_symbol():
    cheap, expensive = bars(seed=1, start_price=100.0), bars(seed=2, start_price=500.0)
    backtest = engine(initial_capital=1_000_000.0)

    await backtest.run_backtest(buy_once("BBB", 10), {"AAA": cheap, "BBB": expensive})

    fill = backtest.trades[0]
    assert fill.instrument.symbol == "BBB"
    assert fill.price == pytest.approx(expensive["close"].iloc[1] * 1.0005)


async def test_trade_ids_are_unique():
    data = bars()
    backtest = engine()
    calls = []

    async def buy_then_sell(timestamp, market_data, portfolio):
        calls.append(timestamp)
        side = {1: OrderSide.BUY, 3: OrderSide.SELL}.get(len(calls))
        if side is None:
            return []
        return [Order(id="", instrument=Instrument("AAPL", AssetType.EQUITY, "NYSE"),
                      side=side, order_type=OrderType.MARKET, quantity=10)]

    await backtest.run_backtest(buy_then_sell, {"AAPL": data})

    assert len(backtest.trades) == 2
    assert len({trade.trade_id for trade in backtest.trades}) == 2
    assert backtest.portfolio.positions == {}


async def test_engine_can_be_reused_without_carrying_state():
    data = bars()
    backtest = engine()

    first = await backtest.run_backtest(buy_once("AAPL", 100), {"AAPL": data})
    second = await backtest.run_backtest(buy_once("AAPL", 100), {"AAPL": data})

    assert len(second.pnl_series) == len(data)
    assert second.final_capital == pytest.approx(first.final_capital)
    assert second.total_trades == 1


async def test_backtest_example_runs(capsys):
    from main import run_backtest_example

    await run_backtest_example()

    output = capsys.readouterr().out
    for label in ("Total Return:", "Sharpe Ratio:", "Max Drawdown:", "Total Trades:", "Final Capital:"):
        assert label in output
    trades_line = next(line for line in output.splitlines() if line.startswith("Total Trades:"))
    assert int(trades_line.split(":")[1]) > 0
