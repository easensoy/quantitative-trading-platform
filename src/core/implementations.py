import asyncio
import random
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set, Tuple
import pandas as pd
import numpy as np

from src.core.models import (
    MarketDataProvider, OrderExecutionEngine, RiskManager, EventBus,
    Instrument, MarketData, Order, Portfolio, OrderStatus, OrderSide, OrderType, Venue
)
from src.core.event_bus import create_event_bus
from src.core.config import get_config

# Returns a reference price for an instrument (for example the latest streamed quote),
# or None when no price is known yet.
PriceSource = Callable[[Instrument], Optional[float]]


class SimulatedMarketDataProvider(MarketDataProvider):
    """Synthetic quotes drawn around a base price.

    The provider is pull-only: MarketDataService polls get_market_data() and publishes
    each quote on the application's event bus, so the provider never publishes itself.
    Pass a seed for a reproducible price sequence.
    """

    def __init__(self, seed: Optional[int] = None, base_price: float = 100.0, price_std: float = 5.0):
        self._rng = random.Random(seed)
        self.base_price = base_price
        self.price_std = price_std
        self._subscribed_instruments: Set[str] = set()
        
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        base_price = self.base_price + self._rng.gauss(0, self.price_std)
        spread = base_price * 0.001
        
        return MarketData(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=base_price - spread/2,
            ask=base_price + spread/2,
            last=base_price,
            volume=self._rng.randint(1000, 10000),
            bid_size=self._rng.randint(100, 1000),
            ask_size=self._rng.randint(100, 1000)
        )
    
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        for instrument in instruments:
            self._subscribed_instruments.add(instrument.symbol)


class BasicOrderExecutionEngine(OrderExecutionEngine):
    """Simulated execution: every accepted order fills in full after a short delay.

    Market (and stop) orders fill at the reference price -- the latest quote from
    price_source, else the order price, else 100.0 -- moved by slippage against the
    trader. Limit orders fill at the limit price or better. Resting, unmarketable limit
    orders and partial fills are not modelled.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        price_source: Optional[PriceSource] = None,
        slippage: float = 0.001,
        fill_delay: Tuple[float, float] = (0.1, 0.5),
    ):
        # Lifecycle events must go to the bus OrderExecutionService listens on. Creating a
        # private bus here (the old behaviour) silently dropped every fill.
        self.event_bus = event_bus if event_bus is not None else create_event_bus()
        self.price_source = price_source
        self.slippage = slippage
        self.fill_delay = fill_delay
        self.orders: Dict[str, Order] = {}
        self.pending_orders: Dict[str, Order] = {}
        self.order_counter = 0
        self._tasks: Set[asyncio.Task] = set()
        
    async def submit_order(self, order: Order) -> str:
        order.id = f"order_{self.order_counter}"
        self.order_counter += 1
        order.status = OrderStatus.SUBMITTED
        
        self.orders[order.id] = order
        self.pending_orders[order.id] = order
        
        await self.event_bus.publish("order_submitted", {
            "order_id": order.id,
            "order": order
        })
        
        # Keep a reference so the fill task cannot be garbage-collected mid-flight.
        task = asyncio.create_task(self._process_order(order))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return order.id
    
    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self.pending_orders:
            order = self.pending_orders.pop(order_id)
            order.status = OrderStatus.CANCELLED
            
            await self.event_bus.publish("order_cancelled", {
                "order_id": order_id,
                "order": order
            })
            return True
        return False
    
    async def get_order_status(self, order_id: str) -> OrderStatus:
        order = self.orders.get(order_id)
        # Unknown order ids report REJECTED, as before.
        return order.status if order is not None else OrderStatus.REJECTED
        
    async def _process_order(self, order: Order):
        low, high = self.fill_delay
        await asyncio.sleep(random.uniform(low, high) if high > 0 else 0)
        
        if order.id not in self.pending_orders:
            return
            
        fill_price = self._calculate_fill_price(order)
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        
        del self.pending_orders[order.id]
        
        await self.event_bus.publish("order_filled", {
            "order_id": order.id,
            "order": order,
            "fill_price": fill_price
        })
        
    def _reference_price(self, order: Order) -> Optional[float]:
        if self.price_source is not None:
            price = self.price_source(order.instrument)
            if price:
                return price
        return None

    def _calculate_fill_price(self, order: Order) -> float:
        reference = self._reference_price(order)
        direction = 1 if order.side == OrderSide.BUY else -1

        if order.order_type == OrderType.LIMIT and order.price:
            if reference is None:
                return order.price
            market_price = reference * (1 + direction * self.slippage)
            # Never fill a limit order at a worse price than its limit.
            return min(order.price, market_price) if order.side == OrderSide.BUY else max(order.price, market_price)

        base_price = reference or order.price or 100.0
        return base_price * (1 + direction * self.slippage)


class BasicRiskManager(RiskManager):
    def __init__(self, config: Optional[Dict] = None, price_source: Optional[PriceSource] = None):
        self.config = config if config is not None else get_config()
        self.max_position_size = self.config.get("risk", {}).get("max_position_size", 10000)
        self.max_portfolio_leverage = self.config.get("risk", {}).get("max_portfolio_leverage", 3.0)
        self.max_daily_loss = self.config.get("risk", {}).get("max_daily_loss", 0.05)
        self.price_source = price_source
        
    def validate_order(self, order: Order, portfolio: Portfolio) -> bool:
        if not self._check_position_limits(order, portfolio):
            return False
        if not self._check_leverage_limits(order, portfolio):
            return False
        if not self._check_daily_loss_limits(portfolio):
            return False
        return True
    
    def calculate_risk_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        positions_df = pd.DataFrame([
            {
                "symbol": pos.instrument.symbol,
                "quantity": pos.quantity,
                "price": pos.avg_price,
                "notional": pos.notional
            }
            for pos in portfolio.positions.values()
        ])
        
        if positions_df.empty:
            return {"var_95": 0.0, "expected_shortfall": 0.0, "leverage": 0.0}
            
        total_notional = positions_df["notional"].abs().sum()
        leverage = total_notional / max(portfolio.cash, 1)
        
        returns = np.random.normal(0, 0.02, 252)
        portfolio_returns = returns * total_notional / max(portfolio.cash, 1)
        
        var_95 = np.percentile(portfolio_returns, 5)
        expected_shortfall = portfolio_returns[portfolio_returns <= var_95].mean()
        
        return {
            "var_95": var_95,
            "expected_shortfall": expected_shortfall,
            "leverage": leverage,
            "total_notional": total_notional
        }
    
    def _check_position_limits(self, order: Order, portfolio: Portfolio) -> bool:
        symbol = order.instrument.symbol
        current_pos = portfolio.get_position(symbol)
        current_qty = current_pos.quantity if current_pos else 0
        
        new_qty = current_qty + (order.quantity if order.side == OrderSide.BUY else -order.quantity)
        return abs(new_qty) <= self.max_position_size
    
    def _order_price(self, order: Order) -> float:
        if order.price:
            return order.price
        if self.price_source is not None:
            price = self.price_source(order.instrument)
            if price:
                return price
        return 100.0

    def _check_leverage_limits(self, order: Order, portfolio: Portfolio) -> bool:
        order_notional = order.quantity * self._order_price(order)
        total_notional = portfolio.total_notional + order_notional
        leverage = total_notional / max(portfolio.cash, 1)
        return leverage <= self.max_portfolio_leverage
    
    def _check_daily_loss_limits(self, portfolio: Portfolio) -> bool:
        return True


class YahooFinanceDataProvider(MarketDataProvider):
    """Quotes from yfinance (optional, network access required; falls back to simulated
    data when yfinance is not installed). Pull-only, like SimulatedMarketDataProvider.
    Not exercised by the test suite.
    """

    def __init__(self):
        self._subscribed_instruments: Set[str] = set()
        
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        try:
            import yfinance as yf
            ticker = yf.Ticker(instrument.symbol)
            data = ticker.history(period="1d", interval="1m")
            
            if data.empty:
                raise ValueError(f"No data for {instrument.symbol}")
                
            latest = data.iloc[-1]
            return MarketData(
                instrument=instrument,
                timestamp=datetime.utcnow(),
                last=float(latest['Close']),
                volume=int(latest['Volume']),
                bid=float(latest['Close']) * 0.999,
                ask=float(latest['Close']) * 1.001
            )
        except ImportError:
            return await SimulatedMarketDataProvider().get_market_data(instrument)
    
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        for instrument in instruments:
            self._subscribed_instruments.add(instrument.symbol)
            