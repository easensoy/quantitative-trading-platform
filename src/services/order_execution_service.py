from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
import asyncio
import inspect

from src.core.models import Order, OrderStatus, OrderExecutionEngine, Fill
from src.core.event_bus import EventBus
from src.core.container import Injectable, service
from src.core.implementations import BasicOrderExecutionEngine, PriceSource


class OrderExecutionServiceInterface(ABC):
    @abstractmethod
    async def submit_order(self, order: Order) -> Optional[str]:
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass
    
    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        pass
    
    @abstractmethod
    async def get_active_orders(self) -> List[Order]:
        pass


@service("order_execution_service")
class OrderExecutionService(OrderExecutionServiceInterface, Injectable):
    def __init__(self, event_bus: EventBus, execution_engine: OrderExecutionEngine, commission_rate: float = 0.001):
        self.event_bus = event_bus
        self.execution_engine = execution_engine
        self.commission_rate = commission_rate
        self.order_history: Dict[str, Order] = {}
        self.rejected_orders: List[Order] = []
        self.fill_callbacks: List[Callable] = []
        self.order_callbacks: List[Callable] = []
        self.pre_trade_checks: List[Callable] = []
        self._initialized = False
        
    async def initialize(self) -> None:
        """Subscribe to execution events. Safe to call more than once."""
        if self._initialized:
            return
        await self.event_bus.subscribe("order_filled", self._handle_order_filled)
        await self.event_bus.subscribe("order_submitted", self._handle_order_submitted)
        await self.event_bus.subscribe("order_cancelled", self._handle_order_cancelled)
        self._initialized = True
    
    def add_pre_trade_check(self, check: Callable) -> None:
        """Register check(order) -> bool (sync or async), run before every submission."""
        self.pre_trade_checks.append(check)

    async def submit_order(self, order: Order) -> Optional[str]:
        """Run the pre-trade checks, then hand the order to the execution engine.

        Returns the engine's order id, or None when a check rejects the order. A rejected
        order never reaches the engine and is marked REJECTED.
        """
        for check in self.pre_trade_checks:
            approved = check(order)
            if inspect.isawaitable(approved):
                approved = await approved
            if not approved:
                order.status = OrderStatus.REJECTED
                self.rejected_orders.append(order)
                await self.event_bus.publish("order_lifecycle", {
                    "event": "rejected",
                    "order_id": order.id,
                    "order": order
                })
                return None

        order_id = await self.execution_engine.submit_order(order)
        self.order_history[order_id] = order
        
        await self.event_bus.publish("order_lifecycle", {
            "event": "submitted",
            "order_id": order_id,
            "order": order
        })
        
        return order_id
    
    async def cancel_order(self, order_id: str) -> bool:
        result = await self.execution_engine.cancel_order(order_id)
        
        if result:
            await self.event_bus.publish("order_lifecycle", {
                "event": "cancelled",
                "order_id": order_id
            })
        
        return result
    
    async def get_order_status(self, order_id: str) -> OrderStatus:
        return await self.execution_engine.get_order_status(order_id)
    
    async def get_active_orders(self) -> List[Order]:
        active_orders = []
        for order_id, order in self.order_history.items():
            status = await self.get_order_status(order_id)
            if status in [OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED]:
                active_orders.append(order)
        return active_orders
    
    def add_fill_callback(self, callback: Callable) -> None:
        self.fill_callbacks.append(callback)
    
    def add_order_callback(self, callback: Callable) -> None:
        self.order_callbacks.append(callback)
    
    async def _handle_order_filled(self, data: Dict) -> None:
        order = data["order"]
        fill_price = data["fill_price"]
        
        fill = Fill(
            order_id=order.id,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            timestamp=datetime.utcnow(),
            venue=order.venue or "default",
            trade_id=f"fill_{order.id}",
            commission=order.quantity * fill_price * self.commission_rate,
            strategy_id=order.strategy_id
        )
        
        for callback in self.fill_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(fill)
                else:
                    callback(fill)
            except Exception as e:
                print(f"Fill callback error: {e}")
    
    async def _handle_order_submitted(self, data: Dict) -> None:
        for callback in self.order_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("submitted", data)
                else:
                    callback("submitted", data)
            except Exception as e:
                print(f"Order callback error: {e}")
    
    async def _handle_order_cancelled(self, data: Dict) -> None:
        for callback in self.order_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback("cancelled", data)
                else:
                    callback("cancelled", data)
            except Exception as e:
                print(f"Order callback error: {e}")
    
    async def get_order_metrics(self) -> Dict:
        total_orders = len(self.order_history)
        filled_orders = 0
        cancelled_orders = 0
        
        for order_id in self.order_history:
            status = await self.get_order_status(order_id)
            if status == OrderStatus.FILLED:
                filled_orders += 1
            elif status == OrderStatus.CANCELLED:
                cancelled_orders += 1
        
        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "cancelled_orders": cancelled_orders,
            "rejected_orders": len(self.rejected_orders),
            "fill_rate": filled_orders / total_orders if total_orders > 0 else 0
        }


class OrderExecutionFactory:
    @staticmethod
    def create_engine(
        engine_type: str = "basic",
        event_bus: Optional[EventBus] = None,
        price_source: Optional[PriceSource] = None,
        slippage: float = 0.001,
        fill_delay: Tuple[float, float] = (0.1, 0.5),
    ) -> OrderExecutionEngine:
        # "basic" is the only engine implemented; any other value falls back to it.
        return BasicOrderExecutionEngine(
            event_bus=event_bus,
            price_source=price_source,
            slippage=slippage,
            fill_delay=fill_delay,
        )
    
    @staticmethod
    def create_service(
        event_bus: EventBus,
        engine_type: str = "basic",
        price_source: Optional[PriceSource] = None,
        commission_rate: float = 0.001,
        slippage: float = 0.001,
        fill_delay: Tuple[float, float] = (0.1, 0.5),
    ) -> OrderExecutionService:
        # The engine shares the service's event bus so its fill events reach the service.
        engine = OrderExecutionFactory.create_engine(
            engine_type, event_bus, price_source, slippage, fill_delay
        )
        return OrderExecutionService(event_bus, engine, commission_rate)