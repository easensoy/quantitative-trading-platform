"""Service wiring, event delivery, order handling and portfolio updates.

All execution is simulated; quotes are published directly on the event bus, so no
market data source is involved and fills happen without delay.
"""
import asyncio
import copy
from datetime import datetime

import pytest

from src.core.container import ServiceRegistry
from src.core.event_bus import InMemoryEventBus
from src.core.implementations import BasicOrderExecutionEngine
from src.core.models import (
    AssetType, Instrument, MarketData, Order, OrderSide, OrderStatus, OrderType, Strategy,
)
from src.core.orchestrator import TradingOrchestrator
from src.services.application_service import TradingApplicationService

AAPL = Instrument("AAPL", AssetType.EQUITY, "NASDAQ")
INITIAL_CASH = 1_000_000.0

BASE_CONFIG = {
    "mode": "service",
    "initial_capital": INITIAL_CASH,
    "status_interval": 0.05,
    "market_data": {"provider": "simulated", "poll_interval": 0.01, "seed": 1},
    "event_bus": {"type": "memory"},
    "risk": {"max_position_size": 1_000, "max_portfolio_leverage": 3.0, "max_daily_loss": 0.05},
    "execution": {"commission": 0.001, "slippage": 0.001, "fill_delay": (0.0, 0.0)},
}


def make_config(**overrides):
    config = copy.deepcopy(BASE_CONFIG)
    for key, value in overrides.items():
        if isinstance(value, dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


@pytest.fixture(autouse=True)
def fresh_registry():
    # The service container is process-global; give every test its own.
    ServiceRegistry.reset()
    yield
    ServiceRegistry.reset()


async def initialized_app(**overrides):
    app = TradingApplicationService(make_config(**overrides))
    await app.initialize()
    return app


async def publish_quote(app, instrument, price):
    await app.event_bus.publish("market_data", {
        "symbol": instrument.symbol,
        "market_data": MarketData(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=price - 0.05,
            ask=price + 0.05,
            last=price,
            volume=1_000,
        ),
    })


async def wait_until(predicate, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met before timeout")
        await asyncio.sleep(0.005)


def market_order(side, quantity, instrument=AAPL):
    return Order(id="", instrument=instrument, side=side, order_type=OrderType.MARKET, quantity=quantity)


async def test_initialize_registers_services_on_one_event_bus():
    app = await initialized_app()

    for name in ("event_bus", "market_data_service", "order_execution_service",
                 "portfolio_service", "risk_service", "strategy_service"):
        assert app.container.get(name) is not None
    # The execution engine must publish where OrderExecutionService listens.
    assert app.order_execution_service.execution_engine.event_bus is app.event_bus

    subscribers = app.event_bus._subscribers
    assert len(subscribers["market_data"]) == 3  # market data cache, portfolio, strategies
    assert len(subscribers["order_filled"]) == 1

    # Re-initializing a service or re-subscribing instruments must not double-register.
    await app.market_data_service.initialize()
    await app.market_data_service.subscribe_to_instruments([AAPL])
    await app.market_data_service.subscribe_to_instruments([AAPL])
    assert len(subscribers["market_data"]) == 3
    assert app.market_data_service.subscribed_instruments == [AAPL]


async def test_market_buy_fill_updates_cash_and_position():
    app = await initialized_app()
    await publish_quote(app, AAPL, 100.0)

    order = market_order(OrderSide.BUY, 100)
    order_id = await app.order_execution_service.submit_order(order)
    portfolio = app.portfolio_service.portfolio
    await wait_until(lambda: portfolio.get_position("AAPL") is not None)

    fill_price = 100.0 * 1.001  # latest quote moved by slippage against the buyer
    commission = 100 * fill_price * 0.001
    assert order.avg_fill_price == pytest.approx(fill_price)
    assert portfolio.cash == pytest.approx(INITIAL_CASH - 100 * fill_price - commission)
    position = portfolio.get_position("AAPL")
    assert position.quantity == 100
    assert position.avg_price == pytest.approx(fill_price)
    # Filled orders report FILLED (previously REJECTED once they left the pending book).
    assert await app.order_execution_service.get_order_status(order_id) == OrderStatus.FILLED
    metrics = await app.order_execution_service.get_order_metrics()
    assert (metrics["total_orders"], metrics["filled_orders"]) == (1, 1)


async def test_market_sell_credits_cash_and_keeps_cost_basis():
    app = await initialized_app()
    portfolio = app.portfolio_service.portfolio
    await publish_quote(app, AAPL, 100.0)
    await app.order_execution_service.submit_order(market_order(OrderSide.BUY, 100))
    await wait_until(lambda: portfolio.get_position("AAPL") is not None)
    cash_after_buy = portfolio.cash

    await publish_quote(app, AAPL, 110.0)
    await app.order_execution_service.submit_order(market_order(OrderSide.SELL, 40))
    await wait_until(lambda: portfolio.get_position("AAPL").quantity == 60)

    sell_price = 110.0 * 0.999
    assert portfolio.cash == pytest.approx(cash_after_buy + 40 * sell_price * (1 - 0.001))
    assert portfolio.get_position("AAPL").avg_price == pytest.approx(100.0 * 1.001)
    value = await app.portfolio_service.calculate_portfolio_value(app.market_data_service.latest_data)
    assert value == pytest.approx(portfolio.cash + 60 * 110.0)


async def test_risk_rejection_happens_before_submission():
    app = await initialized_app(risk={"max_position_size": 50})
    lifecycle_events = []
    await app.event_bus.subscribe("order_lifecycle", lifecycle_events.append)
    await publish_quote(app, AAPL, 100.0)

    order = market_order(OrderSide.BUY, 100)
    result = await app.order_execution_service.submit_order(order)

    assert result is None
    assert order.status == OrderStatus.REJECTED
    assert app.order_execution_service.execution_engine.orders == {}  # never reached the engine
    assert app.order_execution_service.rejected_orders == [order]
    assert app.portfolio_service.portfolio.cash == INITIAL_CASH
    assert app.portfolio_service.portfolio.positions == {}
    alerts = await app.risk_service.get_risk_alerts()
    assert [alert["type"] for alert in alerts] == ["order_rejected"]
    assert "buy 100 AAPL" in alerts[0]["message"]
    assert lifecycle_events[-1]["event"] == "rejected"


async def test_leverage_check_prices_market_orders_from_latest_quote():
    app = await initialized_app(risk={"max_position_size": 1_000_000})
    await publish_quote(app, AAPL, 1_000.0)

    # 3,500 shares at the 1,000 quote is 3.5x leverage on 1M cash; the old fixed
    # 100.0 reference price would have priced it at 0.35x and let it through.
    order = market_order(OrderSide.BUY, 3_500)
    assert await app.order_execution_service.submit_order(order) is None
    assert order.status == OrderStatus.REJECTED


async def test_strategy_orders_pass_through_the_risk_gate():
    app = await initialized_app(risk={"max_position_size": 150})
    portfolio = app.portfolio_service.portfolio

    async def always_buy_100(market_data, current_portfolio):
        return [market_order(OrderSide.BUY, 100, market_data.instrument)]

    await app.strategy_service.register_strategy(
        Strategy(id="always_buy", name="Always buy", description="test"), always_buy_100
    )

    await publish_quote(app, AAPL, 100.0)  # 100 shares: within the 150 limit
    await wait_until(lambda: portfolio.get_position("AAPL") is not None)
    await publish_quote(app, AAPL, 100.0)  # would reach 200: rejected before submission

    assert portfolio.get_position("AAPL").quantity == 100
    assert len(app.order_execution_service.rejected_orders) == 1
    performance = await app.strategy_service.get_strategy_performance("always_buy")
    assert performance["orders_generated"] == 2
    assert performance["successful_orders"] == 1  # fills carry the strategy id back


async def test_orchestrator_submit_order_uses_the_same_risk_gate(monkeypatch):
    monkeypatch.setenv("MAX_POSITION_SIZE", "50")
    monkeypatch.setenv("EVENT_BUS_TYPE", "memory")
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "simulated")

    orchestrator = TradingOrchestrator()
    await orchestrator.initialize()

    order = market_order(OrderSide.BUY, 100)
    assert await orchestrator.submit_order(order) is None
    assert order.status == OrderStatus.REJECTED


async def test_start_streams_simulated_quotes_and_stop_is_prompt():
    app = TradingApplicationService(make_config())
    run = asyncio.create_task(app.start())

    # start() initializes the services and subscribes the five default instruments.
    await wait_until(lambda: app.market_data_service is not None
                     and len(app.market_data_service.latest_data) == 5, timeout=5)
    status = await app.get_system_status()
    assert status["status"] == "running"
    assert status["strategies"]["total_strategies"] == 2
    assert status["risk"]["monitoring_active"] is True

    await app.stop()
    await asyncio.wait_for(run, timeout=2)  # no waiting out a full status interval

    assert app.market_data_service.streaming_task is None
    assert app.risk_service._monitoring_task is None
    assert await app.get_system_status() == {"status": "stopped"}


async def test_default_strategies_do_not_replace_registered_ones():
    app = await initialized_app()

    async def my_handler(market_data, portfolio):
        return []

    await app.strategy_service.register_strategy(
        Strategy(id="momentum_001", name="Mine", description="same id as a default"), my_handler
    )
    run = asyncio.create_task(app.start())
    await wait_until(lambda: len(app.market_data_service.latest_data) > 0)

    assert list(app.strategy_service.strategies) == ["momentum_001"]
    assert app.strategy_service.strategy_handlers["momentum_001"] is my_handler

    await app.stop()
    await asyncio.wait_for(run, timeout=2)


async def test_execution_engine_publishes_on_the_injected_bus():
    bus = InMemoryEventBus()
    fills = []
    await bus.subscribe("order_filled", fills.append)
    engine = BasicOrderExecutionEngine(event_bus=bus, price_source=lambda instrument: 50.0,
                                       slippage=0.0, fill_delay=(0.0, 0.0))

    order_id = await engine.submit_order(market_order(OrderSide.BUY, 10))
    await wait_until(lambda: fills)

    assert fills[0]["order_id"] == order_id
    assert fills[0]["fill_price"] == 50.0
    assert await engine.get_order_status(order_id) == OrderStatus.FILLED


async def test_limit_orders_never_fill_worse_than_the_limit():
    bus = InMemoryEventBus()
    engine = BasicOrderExecutionEngine(event_bus=bus, price_source=lambda instrument: 100.0,
                                       slippage=0.001, fill_delay=(0.0, 0.0))
    buy = Order(id="", instrument=AAPL, side=OrderSide.BUY, order_type=OrderType.LIMIT,
                quantity=1, price=100.0)
    sell = Order(id="", instrument=AAPL, side=OrderSide.SELL, order_type=OrderType.LIMIT,
                 quantity=1, price=100.0)
    await engine.submit_order(buy)
    await engine.submit_order(sell)
    await wait_until(lambda: buy.status == sell.status == OrderStatus.FILLED)

    assert buy.avg_fill_price <= 100.0
    assert sell.avg_fill_price >= 100.0
