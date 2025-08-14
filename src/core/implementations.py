import asyncio
import random
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from src.core.models import (
    MarketDataProvider, OrderExecutionEngine, RiskManager,
    Instrument, MarketData, Order, Portfolio, OrderStatus, OrderSide, Venue
)
from src.core.event_bus import create_event_bus
from src.core.config import get_config


class SimulatedMarketDataProvider(MarketDataProvider):
    def __init__(self):
        self.event_bus = create_event_bus()
        self._subscribed_instruments = set()
        
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        base_price = 100.0 + random.gauss(0, 5)
        spread = base_price * 0.001
        
        return MarketData(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=base_price - spread/2,
            ask=base_price + spread/2,
            last=base_price,
            volume=random.randint(1000, 10000),
            bid_size=random.randint(100, 1000),
            ask_size=random.randint(100, 1000)
        )
    
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        for instrument in instruments:
            if instrument.symbol not in self._subscribed_instruments:
                self._subscribed_instruments.add(instrument.symbol)
                asyncio.create_task(self._stream_data(instrument))
                
    async def _stream_data(self, instrument: Instrument):
        while instrument.symbol in self._subscribed_instruments:
            market_data = await self.get_market_data(instrument)
            await self.event_bus.publish("market_data", {
                "symbol": instrument.symbol,
                "market_data": market_data
            })
            await asyncio.sleep(1)


class BasicOrderExecutionEngine(OrderExecutionEngine):
    def __init__(self):
        self.event_bus = create_event_bus()
        self.pending_orders: Dict[str, Order] = {}
        self.order_counter = 0
        
    async def submit_order(self, order: Order) -> str:
        order.id = f"order_{self.order_counter}"
        self.order_counter += 1
        order.status = OrderStatus.SUBMITTED
        
        self.pending_orders[order.id] = order
        
        await self.event_bus.publish("order_submitted", {
            "order_id": order.id,
            "order": order
        })
        
        asyncio.create_task(self._process_order(order))
        return order.id
    
    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self.pending_orders:
            order = self.pending_orders[order_id]
            order.status = OrderStatus.CANCELLED
            del self.pending_orders[order_id]
            
            await self.event_bus.publish("order_cancelled", {
                "order_id": order_id,
                "order": order
            })
            return True
        return False
    
    async def get_order_status(self, order_id: str) -> OrderStatus:
        if order_id in self.pending_orders:
            return self.pending_orders[order_id].status
        return OrderStatus.REJECTED
        
    async def _process_order(self, order: Order):
        await asyncio.sleep(random.uniform(0.1, 0.5))
        
        if order.id not in self.pending_orders:
            return
            
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = self._calculate_fill_price(order)
        
        del self.pending_orders[order.id]
        
        await self.event_bus.publish("order_filled", {
            "order_id": order.id,
            "order": order,
            "fill_price": order.avg_fill_price
        })
        
    def _calculate_fill_price(self, order: Order) -> float:
        base_price = order.price or 100.0
        slippage = 0.001 if order.side == OrderSide.BUY else -0.001
        return base_price * (1 + slippage)


class BasicRiskManager(RiskManager):
    def __init__(self):
        self.config = get_config()
        self.max_position_size = self.config.get("risk", {}).get("max_position_size", 10000)
        self.max_portfolio_leverage = self.config.get("risk", {}).get("max_portfolio_leverage", 3.0)
        self.max_daily_loss = self.config.get("risk", {}).get("max_daily_loss", 0.05)
        
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
    
    def _check_leverage_limits(self, order: Order, portfolio: Portfolio) -> bool:
        order_notional = order.quantity * (order.price or 100.0)
        total_notional = portfolio.total_notional + order_notional
        leverage = total_notional / max(portfolio.cash, 1)
        return leverage <= self.max_portfolio_leverage
    
    def _check_daily_loss_limits(self, portfolio: Portfolio) -> bool:
        return True


class YahooFinanceDataProvider(MarketDataProvider):
    def __init__(self):
        self.event_bus = create_event_bus()
        
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
            asyncio.create_task(self._stream_real_data(instrument))
            
    async def _stream_real_data(self, instrument: Instrument):
        while True:
            try:
                market_data = await self.get_market_data(instrument)
                await self.event_bus.publish("market_data", {
                    "symbol": instrument.symbol,
                    "market_data": market_data
                })
            except Exception as e:
                print(f"Data error for {instrument.symbol}: {e}")
            await asyncio.sleep(60)