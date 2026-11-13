import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Dict, List, Optional

from src.core.orchestrator import TradingOrchestrator
from src.core.models import Instrument, AssetType, Strategy, Order, OrderSide, OrderType
from src.core.config import get_config
from src.services.application_service import ApplicationFactory, TradingApplicationService


async def _run_until_stopped(
    run: Awaitable, stop: Callable[[], Awaitable], duration: Optional[float]
) -> None:
    """Await a long-running coroutine; with a duration, call stop() after that many seconds."""
    if duration is None:
        await run
        return
    task = asyncio.ensure_future(run)
    done, _ = await asyncio.wait({task}, timeout=duration)
    if not done:
        await stop()
    await task


async def _print_session_summary(app: TradingApplicationService) -> None:
    summary = await app.get_portfolio_summary()
    orders = await app.order_execution_service.get_order_metrics()
    print("Session summary (simulated execution):")
    print(f"  Portfolio value: ${summary['portfolio_value']:,.2f}")
    print(f"  Cash: ${summary['cash']:,.2f}")
    for position in summary["positions"]:
        print(f"  {position['symbol']}: {position['quantity']} @ avg ${position['avg_price']:,.2f}")
    print(
        f"  Orders: {orders['total_orders']} submitted, {orders['filled_orders']} filled, "
        f"{orders['rejected_orders']} rejected by risk checks"
    )


async def simple_momentum_strategy(market_data, portfolio):
    orders = []
    
    if hasattr(market_data, 'last') and market_data.last:
        price = market_data.last
        symbol = market_data.instrument.symbol
        
        current_pos = portfolio.get_position(symbol)
        current_qty = current_pos.quantity if current_pos else 0
        
        if price > 105 and current_qty <= 0:
            order = Order(
                id="",
                instrument=market_data.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=100
            )
            orders.append(order)
        elif price < 95 and current_qty >= 0:
            order = Order(
                id="",
                instrument=market_data.instrument,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=100
            )
            orders.append(order)
    
    return orders


async def mean_reversion_strategy(market_data, portfolio):
    orders = []
    
    if hasattr(market_data, 'last') and market_data.last:
        price = market_data.last
        symbol = market_data.instrument.symbol
        
        current_pos = portfolio.get_position(symbol)
        current_qty = current_pos.quantity if current_pos else 0
        
        if price < 98 and current_qty <= 0:
            order = Order(
                id="",
                instrument=market_data.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=50,
                price=price * 0.99
            )
            orders.append(order)
        elif price > 102 and current_qty >= 0:
            order = Order(
                id="",
                instrument=market_data.instrument,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=50,
                price=price * 1.01
            )
            orders.append(order)
    
    return orders


async def run_live_trading(duration: Optional[float] = None):
    # "live" uses the configured market data provider (simulated by default) with
    # simulated execution; nothing connects to a broker.
    logging.basicConfig(level=logging.INFO)
    orchestrator = TradingOrchestrator()
    await orchestrator.initialize()
    
    await orchestrator.add_instrument("AAPL", "equity", "NASDAQ")
    await orchestrator.add_instrument("GOOGL", "equity", "NASDAQ")
    await orchestrator.add_instrument("MSFT", "equity", "NASDAQ")
    
    momentum_strategy = Strategy(
        id="momentum_001",
        name="Simple Momentum",
        description="Buy high, sell low momentum strategy"
    )
    
    mean_reversion_strategy_obj = Strategy(
        id="mean_reversion_001",
        name="Mean Reversion",
        description="Buy low, sell high mean reversion strategy"
    )
    
    await orchestrator.add_strategy(momentum_strategy, simple_momentum_strategy)
    await orchestrator.add_strategy(mean_reversion_strategy_obj, mean_reversion_strategy)
    
    await _run_until_stopped(orchestrator.start(), orchestrator.stop, duration)
    await _print_session_summary(orchestrator.application_service)


async def run_service(duration: Optional[float] = None):
    app_service = ApplicationFactory.create_application()
    await _run_until_stopped(app_service.start(), app_service.stop, duration)
    await _print_session_summary(app_service)


async def run_backtest_example():
    from src.backtesting.synthetic import generate_ohlcv
    
    logging.basicConfig(level=logging.INFO)
    
    # Seeded synthetic bars: the same result on every run, no market data access needed.
    market_data = {
        "AAPL": generate_ohlcv(start="2023-01-01", end="2023-12-31", seed=42)
    }
    
    async def backtest_strategy(timestamp, market_data_dict, portfolio):
        orders = []
        
        for symbol, data in market_data_dict.items():
            price = data.close
            current_pos = portfolio.get_position(symbol)
            current_qty = current_pos.quantity if current_pos else 0
            
            if price > 102 and current_qty == 0:
                order = Order(
                    id="",
                    instrument=Instrument(symbol, AssetType.EQUITY, "NYSE"),
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=100
                )
                orders.append(order)
            elif price < 98 and current_qty > 0:
                order = Order(
                    id="",
                    instrument=Instrument(symbol, AssetType.EQUITY, "NYSE"),
                    side=OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=current_qty
                )
                orders.append(order)
        
        return orders
    
    orchestrator = TradingOrchestrator()
    await orchestrator.initialize()
    
    config = {
        "start_date": datetime(2023, 1, 1),
        "end_date": datetime(2023, 12, 31),
        "initial_capital": 1000000
    }
    
    result = await orchestrator.run_backtest(backtest_strategy, market_data, config)
    
    print(f"Backtest Results:")
    print(f"Total Return: {result.total_return:.2%}")
    print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown: {result.max_drawdown:.2%}")
    print(f"Total Trades: {result.total_trades}")
    print(f"Final Capital: ${result.final_capital:,.2f}")


async def main():
    config = get_config()
    mode = config.get("mode", "live")
    duration = config.get("run_duration_seconds")
    
    if mode == "backtest":
        await run_backtest_example()
    elif mode == "service":
        await run_service(duration)
    else:
        await run_live_trading(duration)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Trading system shutdown")
    except Exception as e:
        logging.error(f"Application error: {e}")
        raise