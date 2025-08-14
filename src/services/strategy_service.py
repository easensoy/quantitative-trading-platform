from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable
from datetime import datetime
import asyncio

from src.core.models import Strategy, Order, MarketData, Portfolio
from src.core.event_bus import EventBus
from src.core.container import Injectable, service


class StrategyServiceInterface(ABC):
    @abstractmethod
    async def register_strategy(self, strategy: Strategy, handler: Callable) -> None:
        pass
    
    @abstractmethod
    async def unregister_strategy(self, strategy_id: str) -> None:
        pass
    
    @abstractmethod
    async def execute_strategy(self, strategy_id: str, market_data: MarketData, portfolio: Portfolio) -> List[Order]:
        pass
    
    @abstractmethod
    async def get_active_strategies(self) -> List[Strategy]:
        pass


@service("strategy_service")
class StrategyService(StrategyServiceInterface, Injectable):
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.strategies: Dict[str, Strategy] = {}
        self.strategy_handlers: Dict[str, Callable] = {}
        self.strategy_performance: Dict[str, Dict] = {}
        self.strategy_callbacks: List[Callable] = []
        
        asyncio.create_task(self.event_bus.subscribe("market_data", self._handle_market_data))
        asyncio.create_task(self.event_bus.subscribe("position_updated", self._handle_position_update))
    
    async def register_strategy(self, strategy: Strategy, handler: Callable) -> None:
        self.strategies[strategy.id] = strategy
        self.strategy_handlers[strategy.id] = handler
        self.strategy_performance[strategy.id] = {
            "orders_generated": 0,
            "successful_orders": 0,
            "total_pnl": 0.0,
            "start_time": datetime.utcnow(),
            "last_execution": None,
            "errors": 0
        }
        
        await self.event_bus.publish("strategy_registered", {
            "strategy_id": strategy.id,
            "strategy": strategy,
            "timestamp": datetime.utcnow()
        })
        
        for callback in self.strategy_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("registered", strategy)
                else:
                    callback("registered", strategy)
            except Exception as e:
                print(f"Strategy callback error: {e}")
    
    async def unregister_strategy(self, strategy_id: str) -> None:
        if strategy_id in self.strategies:
            strategy = self.strategies[strategy_id]
            del self.strategies[strategy_id]
            del self.strategy_handlers[strategy_id]
            
            await self.event_bus.publish("strategy_unregistered", {
                "strategy_id": strategy_id,
                "timestamp": datetime.utcnow()
            })
            
            for callback in self.strategy_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback("unregistered", strategy)
                    else:
                        callback("unregistered", strategy)
                except Exception as e:
                    print(f"Strategy callback error: {e}")
    
    async def execute_strategy(self, strategy_id: str, market_data: MarketData, portfolio: Portfolio) -> List[Order]:
        if strategy_id not in self.strategy_handlers:
            return []
        
        handler = self.strategy_handlers[strategy_id]
        orders = []
        
        try:
            result = handler(market_data, portfolio)
            if asyncio.iscoroutinefunction(handler):
                result = await result
            
            if result:
                orders = result if isinstance(result, list) else [result]
                
                for order in orders:
                    order.strategy_id = strategy_id
                
                self.strategy_performance[strategy_id]["orders_generated"] += len(orders)
                self.strategy_performance[strategy_id]["last_execution"] = datetime.utcnow()
                
                await self.event_bus.publish("strategy_executed", {
                    "strategy_id": strategy_id,
                    "orders_count": len(orders),
                    "market_data": market_data,
                    "timestamp": datetime.utcnow()
                })
        
        except Exception as e:
            self.strategy_performance[strategy_id]["errors"] += 1
            
            await self.event_bus.publish("strategy_error", {
                "strategy_id": strategy_id,
                "error": str(e),
                "market_data": market_data,
                "timestamp": datetime.utcnow()
            })
            
            print(f"Strategy {strategy_id} execution error: {e}")
        
        return orders
    
    async def get_active_strategies(self) -> List[Strategy]:
        return [strategy for strategy in self.strategies.values() if strategy.is_active]
    
    async def pause_strategy(self, strategy_id: str) -> None:
        if strategy_id in self.strategies:
            self.strategies[strategy_id].is_active = False
            
            await self.event_bus.publish("strategy_paused", {
                "strategy_id": strategy_id,
                "timestamp": datetime.utcnow()
            })
    
    async def resume_strategy(self, strategy_id: str) -> None:
        if strategy_id in self.strategies:
            self.strategies[strategy_id].is_active = True
            
            await self.event_bus.publish("strategy_resumed", {
                "strategy_id": strategy_id,
                "timestamp": datetime.utcnow()
            })
    
    async def update_strategy_parameters(self, strategy_id: str, parameters: Dict) -> None:
        if strategy_id in self.strategies:
            self.strategies[strategy_id].parameters.update(parameters)
            self.strategies[strategy_id].updated_at = datetime.utcnow()
            
            await self.event_bus.publish("strategy_updated", {
                "strategy_id": strategy_id,
                "new_parameters": parameters,
                "timestamp": datetime.utcnow()
            })
    
    def add_strategy_callback(self, callback: Callable) -> None:
        self.strategy_callbacks.append(callback)
    
    async def get_strategy_performance(self, strategy_id: str) -> Optional[Dict]:
        return self.strategy_performance.get(strategy_id)
    
    async def get_all_strategy_performance(self) -> Dict[str, Dict]:
        return self.strategy_performance.copy()
    
    async def get_strategy_summary(self) -> Dict:
        active_count = len(await self.get_active_strategies())
        total_count = len(self.strategies)
        
        total_orders = sum(perf["orders_generated"] for perf in self.strategy_performance.values())
        total_errors = sum(perf["errors"] for perf in self.strategy_performance.values())
        
        return {
            "total_strategies": total_count,
            "active_strategies": active_count,
            "inactive_strategies": total_count - active_count,
            "total_orders_generated": total_orders,
            "total_errors": total_errors,
            "error_rate": total_errors / max(total_orders, 1)
        }
    
    async def _handle_market_data(self, data: Dict) -> None:
        symbol = data["symbol"]
        market_data = data["market_data"]
        
        for strategy_id, strategy in self.strategies.items():
            if strategy.is_active:
                try:
                    from src.core.container import ServiceRegistry
                    container = ServiceRegistry.get_container()
                    portfolio_service = container.get("portfolio_service")
                    portfolio = await portfolio_service.get_portfolio()
                    
                    orders = await self.execute_strategy(strategy_id, market_data, portfolio)
                    
                    if orders:
                        order_execution_service = container.get("order_execution_service")
                        for order in orders:
                            await order_execution_service.submit_order(order)
                
                except Exception as e:
                    print(f"Error handling market data for strategy {strategy_id}: {e}")
    
    async def _handle_position_update(self, data: Dict) -> None:
        fill = data.get("fill")
        if fill and hasattr(fill, 'strategy_id') and fill.strategy_id:
            strategy_id = fill.strategy_id
            if strategy_id in self.strategy_performance:
                self.strategy_performance[strategy_id]["successful_orders"] += 1


class StrategyFactory:
    @staticmethod
    def create_service(event_bus: EventBus) -> StrategyService:
        return StrategyService(event_bus)
    
    @staticmethod
    def create_momentum_strategy() -> Strategy:
        return Strategy(
            id="momentum_001",
            name="Simple Momentum Strategy",
            description="Buy high, sell higher momentum strategy",
            parameters={"threshold": 0.02, "position_size": 100}
        )
    
    @staticmethod
    def create_mean_reversion_strategy() -> Strategy:
        return Strategy(
            id="mean_reversion_001", 
            name="Mean Reversion Strategy",
            description="Buy low, sell high mean reversion strategy",
            parameters={"lookback": 20, "threshold": 2.0, "position_size": 50}
        )