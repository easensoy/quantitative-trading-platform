from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Dict, List, Optional, Callable
from datetime import datetime
import asyncio

from src.core.models import Portfolio, Position, Fill, MarketData
from src.core.event_bus import EventBus
from src.core.container import Injectable, service


class PortfolioServiceInterface(ABC):
    @abstractmethod
    async def update_position(self, fill: Fill) -> None:
        pass
    
    @abstractmethod
    async def get_portfolio(self) -> Portfolio:
        pass
    
    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        pass
    
    @abstractmethod
    async def calculate_portfolio_value(self, market_data: Dict[str, MarketData]) -> float:
        pass


@service("portfolio_service")
class PortfolioService(PortfolioServiceInterface, Injectable):
    def __init__(self, event_bus: EventBus, initial_cash: float = 1000000.0):
        self.event_bus = event_bus
        self.initial_cash = initial_cash
        self.portfolio = Portfolio(
            id="main_portfolio",
            name="Trading Portfolio",
            cash=initial_cash
        )
        self.position_callbacks: List[Callable] = []
        self.value_callbacks: List[Callable] = []
        self.last_portfolio_value = initial_cash
        self.latest_market_data: Dict[str, MarketData] = {}
        self._initialized = False
        
    async def initialize(self) -> None:
        """Subscribe to the event bus. Safe to call more than once."""
        if self._initialized:
            return
        await self.event_bus.subscribe("fill_executed", self._handle_fill)
        await self.event_bus.subscribe("market_data", self._handle_market_data)
        self._initialized = True
    
    async def update_position(self, fill: Fill) -> None:
        old_position = self.portfolio.get_position(fill.instrument.symbol)
        # Snapshot: Portfolio.update_position mutates the existing Position in place.
        old_position = replace(old_position) if old_position is not None else None
        
        self.portfolio.apply_fill(fill)
        
        new_position = self.portfolio.get_position(fill.instrument.symbol)
        
        await self.event_bus.publish("position_updated", {
            "portfolio_id": self.portfolio.id,
            "portfolio": self.portfolio,
            "symbol": fill.instrument.symbol,
            "old_position": old_position,
            "new_position": new_position,
            "fill": fill
        })
        
        for callback in self.position_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(new_position, fill)
                else:
                    callback(new_position, fill)
            except Exception as e:
                print(f"Position callback error: {e}")
    
    async def get_portfolio(self) -> Portfolio:
        return self.portfolio
    
    async def get_position(self, symbol: str) -> Optional[Position]:
        return self.portfolio.get_position(symbol)
    
    async def calculate_portfolio_value(self, market_data: Dict[str, MarketData]) -> float:
        """Cash plus positions at their latest price; positions without a quote count at cost."""
        total_value = self.portfolio.cash
        
        for symbol, position in self.portfolio.positions.items():
            current_price = None
            if symbol in market_data:
                current_price = market_data[symbol].last or market_data[symbol].mid_price
            total_value += position.quantity * (current_price or position.avg_price)
        
        return total_value
    
    def add_position_callback(self, callback: Callable) -> None:
        self.position_callbacks.append(callback)
    
    def add_value_callback(self, callback: Callable) -> None:
        self.value_callbacks.append(callback)
    
    async def get_portfolio_metrics(self, market_data: Dict[str, MarketData]) -> Dict:
        current_value = await self.calculate_portfolio_value(market_data)
        initial_capital = self.initial_cash
        
        total_return = (current_value - initial_capital) / initial_capital if initial_capital else 0.0
        
        long_positions = sum(1 for pos in self.portfolio.positions.values() if pos.is_long)
        short_positions = sum(1 for pos in self.portfolio.positions.values() if pos.is_short)
        
        total_notional = 0
        for symbol, position in self.portfolio.positions.items():
            if symbol in market_data:
                current_price = market_data[symbol].last or market_data[symbol].mid_price or 0
                total_notional += abs(position.quantity * current_price)
        
        leverage = total_notional / current_value if current_value > 0 else 0
        
        return {
            "current_value": current_value,
            "cash": self.portfolio.cash,
            "total_return": total_return,
            "positions_count": len(self.portfolio.positions),
            "long_positions": long_positions,
            "short_positions": short_positions,
            "leverage": leverage,
            "total_notional": total_notional
        }
    
    async def get_position_summary(self, market_data: Dict[str, MarketData]) -> List[Dict]:
        positions = []
        
        for symbol, position in self.portfolio.positions.items():
            current_price = 0
            unrealized_pnl = 0
            
            if symbol in market_data:
                current_price = market_data[symbol].last or market_data[symbol].mid_price or 0
                unrealized_pnl = position.quantity * (current_price - position.avg_price)
            
            positions.append({
                "symbol": symbol,
                "quantity": position.quantity,
                "avg_price": position.avg_price,
                "current_price": current_price,
                "market_value": position.quantity * current_price,
                "unrealized_pnl": unrealized_pnl,
                "side": "long" if position.is_long else "short" if position.is_short else "flat"
            })
        
        return positions
    
    async def _handle_fill(self, data: Dict) -> None:
        fill = data["fill"]
        await self.update_position(fill)
    
    async def _handle_market_data(self, data: Dict) -> None:
        market_data = {data["symbol"]: data["market_data"]}
        # Value the whole portfolio from the latest quote of every symbol, not just this one.
        self.latest_market_data.update(market_data)
        current_value = await self.calculate_portfolio_value(self.latest_market_data)
        
        if abs(current_value - self.last_portfolio_value) > 1000:
            self.last_portfolio_value = current_value
            
            for callback in self.value_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(current_value, market_data)
                    else:
                        callback(current_value, market_data)
                except Exception as e:
                    print(f"Value callback error: {e}")


class PortfolioFactory:
    @staticmethod
    def create_service(event_bus: EventBus, initial_cash: float = 1000000.0) -> PortfolioService:
        return PortfolioService(event_bus, initial_cash)