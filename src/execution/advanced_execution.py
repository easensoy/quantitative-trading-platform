from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import numpy as np
import pandas as pd
from collections import deque
from src.core.models import Order, OrderSide, OrderType, OrderStatus, Venue, Instrument, MarketData, Fill
from src.core.event_bus import EventBus
class ExecutionAlgorithm(Enum):
    TWAP = "twap"
    VWAP = "vwap"
    IMPLEMENTATION_SHORTFALL = "implementation_shortfall"
    POV = "participation_of_volume"
    SMART_ROUTING = "smart_routing"
    ICEBERG = "iceberg"
    SNIPER = "sniper"
@dataclass
class ExecutionParameters:
    algorithm: ExecutionAlgorithm
    total_quantity: int
    time_horizon_minutes: int
    participation_rate: float = 0.2
    urgency: float = 0.5
    max_percentage_volume: float = 0.3
    min_fill_size: int = 100
    randomization_factor: float = 0.1
    dark_pool_preference: float = 0.3
    price_improvement_threshold: float = 0.0001
    def __post_init__(self):
        self.participation_rate = max(0.01, min(0.5, self.participation_rate))
        self.urgency = max(0.1, min(1.0, self.urgency))
@dataclass
class ExecutionSlice:
    slice_id: str
    quantity: int
    expected_execution_time: datetime
    venue_preference: List[Venue]
    order_type: OrderType = OrderType.LIMIT
    limit_price: Optional[float] = None
    is_executed: bool = False
@dataclass
class VenueMetrics:
    venue: Venue
    fill_rate: float
    average_fill_time_seconds: float
    price_improvement_bps: float
    market_impact_bps: float
    last_update: datetime
    @property
    def quality_score(self) -> float:
        return (self.fill_rate * 0.3 + 
                (1.0 / max(self.average_fill_time_seconds, 1)) * 0.2 + 
                max(0, self.price_improvement_bps) * 0.3 + 
                (1.0 / max(abs(self.market_impact_bps), 0.1)) * 0.2)
class MarketImpactModel:
    def __init__(self):
        self.temporary_impact_decay = 0.5
        self.permanent_impact_factor = 0.1
        self.volume_history: Dict[str, deque] = {}
    def estimate_impact(self, symbol: str, quantity: int, current_volume: int, 
                       volatility: float, spread_bps: float) -> Tuple[float, float]:
        participation_rate = quantity / max(current_volume, 1)
        temporary_impact_bps = (participation_rate ** 0.5) * volatility * 100
        permanent_impact_bps = self.permanent_impact_factor * (participation_rate ** 0.6) * spread_bps
        return temporary_impact_bps, permanent_impact_bps
    def update_volume_history(self, symbol: str, volume: int):
        if symbol not in self.volume_history:
            self.volume_history[symbol] = deque(maxlen=100)
        self.volume_history[symbol].append(volume)
    def get_typical_volume(self, symbol: str) -> int:
        if symbol not in self.volume_history or not self.volume_history[symbol]:
            return 100000  
        return int(np.percentile(list(self.volume_history[symbol]), 50))
class AdvancedExecutionEngine:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.impact_model = MarketImpactModel()
        self.venue_metrics: Dict[Venue, VenueMetrics] = {}
        self.active_executions: Dict[str, 'SmartExecution'] = {}
        self.execution_history: List[Dict] = []
        self.dark_pools: List[Venue] = [Venue.DARK_POOL]
        self.lit_venues: List[Venue] = [Venue.NYSE, Venue.NASDAQ, Venue.BATS, Venue.ARCA, Venue.IEX]
    async def initialize(self):
        await self.event_bus.subscribe("market_data", self._handle_market_data)
        await self.event_bus.subscribe("fill", self._handle_fill)
        for venue in list(Venue):
            self.venue_metrics[venue] = VenueMetrics(
                venue=venue,
                fill_rate=np.random.uniform(0.7, 0.95),
                average_fill_time_seconds=np.random.uniform(0.1, 2.0),
                price_improvement_bps=np.random.uniform(-1, 3),
                market_impact_bps=np.random.uniform(0.5, 3.0),
                last_update=datetime.utcnow()
            )
    async def execute_order(self, parent_order: Order, params: ExecutionParameters) -> str:
        execution_id = f"exec_{parent_order.id}_{datetime.utcnow().timestamp()}"
        execution = SmartExecution(
            execution_id=execution_id,
            parent_order=parent_order,
            parameters=params,
            impact_model=self.impact_model,
            venue_metrics=self.venue_metrics,
            event_bus=self.event_bus
        )
        self.active_executions[execution_id] = execution
        asyncio.create_task(execution.run())
        return execution_id
    async def _handle_market_data(self, data: Dict):
        symbol = data["symbol"]
        market_data = data["market_data"]
        if market_data.volume:
            self.impact_model.update_volume_history(symbol, market_data.volume)
        for execution in self.active_executions.values():
            if execution.parent_order.instrument.symbol == symbol:
                await execution.update_market_data(market_data)
    async def _handle_fill(self, data: Dict):
        fill = data["fill"]
        await self._update_venue_metrics(fill)
        for execution in self.active_executions.values():
            if execution.parent_order.id == fill.order_id:
                await execution.handle_fill(fill)
    async def _update_venue_metrics(self, fill: Fill):
        venue = fill.venue
        if venue in self.venue_metrics:
            metrics = self.venue_metrics[venue]
            metrics.fill_rate = 0.9 * metrics.fill_rate + 0.1 * 1.0  
            metrics.last_update = datetime.utcnow()
    def get_execution_status(self, execution_id: str) -> Optional[Dict]:
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            return execution.get_status()
        return None
    def cancel_execution(self, execution_id: str) -> bool:
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            asyncio.create_task(execution.cancel())
            return True
        return False
class SmartExecution:
    def __init__(self, execution_id: str, parent_order: Order, parameters: ExecutionParameters,
                 impact_model: MarketImpactModel, venue_metrics: Dict[Venue, VenueMetrics],
                 event_bus: EventBus):
        self.execution_id = execution_id
        self.parent_order = parent_order
        self.parameters = parameters
        self.impact_model = impact_model
        self.venue_metrics = venue_metrics
        self.event_bus = event_bus
        self.slices: List[ExecutionSlice] = []
        self.current_market_data: Optional[MarketData] = None
        self.filled_quantity = 0
        self.total_cost = 0.0
        self.start_time = datetime.utcnow()
        self.is_cancelled = False
        self.active_child_orders: Dict[str, Order] = {}
    async def run(self):
        try:
            await self._generate_execution_schedule()
            await self._execute_schedule()
        except Exception as e:
            print(f"Execution {self.execution_id} failed: {e}")
        finally:
            await self._cleanup()
    async def _generate_execution_schedule(self):
        if self.parameters.algorithm == ExecutionAlgorithm.TWAP:
            await self._generate_twap_schedule()
        elif self.parameters.algorithm == ExecutionAlgorithm.VWAP:
            await self._generate_vwap_schedule()
        elif self.parameters.algorithm == ExecutionAlgorithm.IMPLEMENTATION_SHORTFALL:
            await self._generate_is_schedule()
        elif self.parameters.algorithm == ExecutionAlgorithm.POV:
            await self._generate_pov_schedule()
        else:
            await self._generate_twap_schedule()  
    async def _generate_twap_schedule(self):
        total_minutes = self.parameters.time_horizon_minutes
        slice_interval = max(1, total_minutes // 20)  
        num_slices = total_minutes // slice_interval
        base_slice_size = self.parameters.total_quantity // num_slices
        remaining_quantity = self.parameters.total_quantity
        for i in range(num_slices):
            randomization = np.random.uniform(-self.parameters.randomization_factor, 
                                            self.parameters.randomization_factor)
            slice_size = int(base_slice_size * (1 + randomization))
            slice_size = min(slice_size, remaining_quantity)
            if slice_size <= 0:
                break
            execution_time = self.start_time + timedelta(minutes=i * slice_interval)
            slice_obj = ExecutionSlice(
                slice_id=f"{self.execution_id}_slice_{i}",
                quantity=slice_size,
                expected_execution_time=execution_time,
                venue_preference=self._select_venues()
            )
            self.slices.append(slice_obj)
            remaining_quantity -= slice_size
        if remaining_quantity > 0 and self.slices:
            self.slices[-1].quantity += remaining_quantity
    async def _generate_vwap_schedule(self):
        total_minutes = self.parameters.time_horizon_minutes
        volume_profile = []
        for i in range(total_minutes):
            if i < total_minutes * 0.25 or i > total_minutes * 0.75:
                volume_weight = 1.5  
            else:
                volume_weight = 1.0
            volume_profile.append(volume_weight)
        total_weight = sum(volume_profile)
        for i, weight in enumerate(volume_profile):
            if i % 5 == 0:  
                slice_quantity = int((weight / total_weight) * self.parameters.total_quantity)
                if slice_quantity > 0:
                    execution_time = self.start_time + timedelta(minutes=i)
                    slice_obj = ExecutionSlice(
                        slice_id=f"{self.execution_id}_vwap_slice_{i}",
                        quantity=slice_quantity,
                        expected_execution_time=execution_time,
                        venue_preference=self._select_venues()
                    )
                    self.slices.append(slice_obj)
    async def _generate_is_schedule(self):
        urgency_factor = self.parameters.urgency
        total_minutes = self.parameters.time_horizon_minutes
        decay_rate = 2.0 * urgency_factor  
        quantities = []
        for i in range(total_minutes):
            weight = np.exp(-decay_rate * i / total_minutes)
            quantities.append(weight)
        total_weight = sum(quantities)
        remaining_quantity = self.parameters.total_quantity
        for i, weight in enumerate(quantities):
            if i % 3 == 0:  
                slice_quantity = int((weight / total_weight) * self.parameters.total_quantity)
                slice_quantity = min(slice_quantity, remaining_quantity)
                if slice_quantity > 0:
                    execution_time = self.start_time + timedelta(minutes=i)
                    slice_obj = ExecutionSlice(
                        slice_id=f"{self.execution_id}_is_slice_{i}",
                        quantity=slice_quantity,
                        expected_execution_time=execution_time,
                        venue_preference=self._select_venues_by_urgency(urgency_factor)
                    )
                    self.slices.append(slice_obj)
                    remaining_quantity -= slice_quantity
    async def _generate_pov_schedule(self):
        await self._generate_twap_schedule()  
        for slice_obj in self.slices:
            pass
    def _select_venues(self) -> List[Venue]:
        venue_scores = []
        for venue, metrics in self.venue_metrics.items():
            score = metrics.quality_score
            if venue in [Venue.DARK_POOL] and self.parameters.dark_pool_preference > 0:
                score *= (1 + self.parameters.dark_pool_preference)
            venue_scores.append((venue, score))
        venue_scores.sort(key=lambda x: x[1], reverse=True)
        return [venue for venue, score in venue_scores[:3]]
    def _select_venues_by_urgency(self, urgency: float) -> List[Venue]:
        venues = self._select_venues()
        if urgency > 0.7:
            lit_venues = [v for v in venues if v not in [Venue.DARK_POOL]]
            return lit_venues + [v for v in venues if v not in lit_venues]
        return venues
    async def _execute_schedule(self):
        while self.slices and not self.is_cancelled:
            current_time = datetime.utcnow()
            ready_slices = [s for s in self.slices 
                          if s.expected_execution_time <= current_time and not s.is_executed]
            for slice_obj in ready_slices:
                await self._execute_slice(slice_obj)
                slice_obj.is_executed = True
            await asyncio.sleep(1)
    async def _execute_slice(self, slice_obj: ExecutionSlice):
        if self.current_market_data is None:
            return
        venue = slice_obj.venue_preference[0] if slice_obj.venue_preference else Venue.NYSE
        if self.parent_order.side == OrderSide.BUY:
            limit_price = self.current_market_data.ask
            if limit_price and self.parameters.price_improvement_threshold > 0:
                limit_price -= self.parameters.price_improvement_threshold
        else:
            limit_price = self.current_market_data.bid
            if limit_price and self.parameters.price_improvement_threshold > 0:
                limit_price += self.parameters.price_improvement_threshold
        child_order = Order(
            id=f"{slice_obj.slice_id}_order",
            instrument=self.parent_order.instrument,
            side=self.parent_order.side,
            order_type=OrderType.LIMIT,
            quantity=slice_obj.quantity,
            price=limit_price,
            venue=venue,
            strategy_id=self.parent_order.strategy_id
        )
        self.active_child_orders[child_order.id] = child_order
        await self.event_bus.publish("submit_order", {"order": child_order})
    async def update_market_data(self, market_data: MarketData):
        self.current_market_data = market_data
        await self._adapt_to_market_conditions()
    async def _adapt_to_market_conditions(self):
        if not self.current_market_data:
            return
        spread = self.current_market_data.spread
        if spread and spread > 0.01:  
            pass
    async def handle_fill(self, fill: Fill):
        self.filled_quantity += fill.quantity
        self.total_cost += fill.notional
        if fill.order_id in self.active_child_orders:
            del self.active_child_orders[fill.order_id]
        if self.filled_quantity >= self.parameters.total_quantity:
            await self._complete_execution()
    async def _complete_execution(self):
        execution_time = (datetime.utcnow() - self.start_time).total_seconds() / 60
        avg_price = self.total_cost / self.filled_quantity if self.filled_quantity > 0 else 0
        completion_data = {
            "execution_id": self.execution_id,
            "parent_order_id": self.parent_order.id,
            "total_filled": self.filled_quantity,
            "avg_fill_price": avg_price,
            "execution_time_minutes": execution_time,
            "algorithm_used": self.parameters.algorithm.value
        }
        await self.event_bus.publish("execution_complete", completion_data)
    async def cancel(self):
        self.is_cancelled = True
        for order_id, order in self.active_child_orders.items():
            await self.event_bus.publish("cancel_order", {"order_id": order_id})
    async def _cleanup(self):
        pass
    def get_status(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "parent_order_id": self.parent_order.id,
            "algorithm": self.parameters.algorithm.value,
            "total_quantity": self.parameters.total_quantity,
            "filled_quantity": self.filled_quantity,
            "fill_rate": self.filled_quantity / self.parameters.total_quantity,
            "avg_fill_price": self.total_cost / self.filled_quantity if self.filled_quantity > 0 else 0,
            "execution_time_minutes": (datetime.utcnow() - self.start_time).total_seconds() / 60,
            "slices_total": len(self.slices),
            "slices_executed": sum(1 for s in self.slices if s.is_executed),
            "active_child_orders": len(self.active_child_orders),
            "is_cancelled": self.is_cancelled
        }