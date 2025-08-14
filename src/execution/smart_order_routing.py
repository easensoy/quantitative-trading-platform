from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable
import asyncio
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

from src.core.models import (
    Order, Fill, Instrument, MarketData, OrderSide, OrderType, 
    OrderStatus, Venue, OrderExecutionEngine
)
from src.core.exceptions import ExecutionError


class RoutingStrategy(Enum):
    TWAP = "twap"
    VWAP = "vwap"
    IMPLEMENTATION_SHORTFALL = "implementation_shortfall"
    PARTICIPATION_RATE = "participation_rate"
    ARRIVAL_PRICE = "arrival_price"
    AGGRESSIVE = "aggressive"


@dataclass
class VenueInfo:
    venue: Venue
    market_data: MarketData
    fees: float
    rebates: float
    latency_ms: float
    fill_probability: float
    dark_pool: bool = False
    min_size: int = 1
    max_size: Optional[int] = None


@dataclass
class RoutingParameters:
    strategy: RoutingStrategy
    max_participation_rate: float = 0.2
    target_completion_time: timedelta = timedelta(minutes=30)
    max_slippage_bps: float = 50.0
    prefer_dark_pools: bool = True
    aggressive_timeout: timedelta = timedelta(seconds=30)
    min_fill_size: int = 100


@dataclass
class OrderSlice:
    original_order_id: str
    slice_id: str
    instrument: Instrument
    side: OrderSide
    quantity: int
    price: Optional[float]
    venue: Venue
    order_type: OrderType
    timestamp: datetime
    parent_strategy: RoutingStrategy
    urgency_score: float = 0.0


class VenueSelector(ABC):
    @abstractmethod
    def select_venues(
        self,
        order: Order,
        venue_info: Dict[Venue, VenueInfo],
        routing_params: RoutingParameters
    ) -> List[Tuple[Venue, float]]:
        pass


class CostBasedVenueSelector(VenueSelector):
    def select_venues(
        self,
        order: Order,
        venue_info: Dict[Venue, VenueInfo],
        routing_params: RoutingParameters
    ) -> List[Tuple[Venue, float]]:
        venue_scores = []
        
        for venue, info in venue_info.items():
            if not self._is_venue_suitable(order, info):
                continue
            
            cost_score = self._calculate_cost_score(order, info)
            liquidity_score = self._calculate_liquidity_score(order, info)
            execution_probability = info.fill_probability
            
            if routing_params.prefer_dark_pools and info.dark_pool:
                dark_pool_bonus = 0.2
            else:
                dark_pool_bonus = 0.0
            
            total_score = (
                0.4 * cost_score +
                0.3 * liquidity_score +
                0.2 * execution_probability +
                dark_pool_bonus
            )
            
            venue_scores.append((venue, total_score))
        
        venue_scores.sort(key=lambda x: x[1], reverse=True)
        
        return venue_scores[:5]

    def _is_venue_suitable(self, order: Order, venue_info: VenueInfo) -> bool:
        if order.quantity < venue_info.min_size:
            return False
        
        if venue_info.max_size and order.quantity > venue_info.max_size:
            return False
        
        return True

    def _calculate_cost_score(self, order: Order, venue_info: VenueInfo) -> float:
        market_data = venue_info.market_data
        
        if market_data.spread is None or market_data.spread <= 0:
            spread_cost = 0.001
        else:
            spread_cost = market_data.spread / (market_data.mid_price or 1)
        
        total_cost = spread_cost + venue_info.fees - venue_info.rebates
        
        return max(0, 1 - (total_cost * 10000))

    def _calculate_liquidity_score(self, order: Order, venue_info: VenueInfo) -> float:
        market_data = venue_info.market_data
        
        if order.side == OrderSide.BUY:
            available_size = market_data.ask_size or 0
        else:
            available_size = market_data.bid_size or 0
        
        if available_size == 0:
            return 0.0
        
        size_ratio = min(order.quantity / available_size, 1.0)
        return 1.0 - size_ratio


class TWAPSlicer:
    def __init__(self, time_horizon: timedelta, num_slices: int = 10):
        self.time_horizon = time_horizon
        self.num_slices = num_slices

    def slice_order(
        self,
        order: Order,
        venues: List[Tuple[Venue, float]]
    ) -> List[OrderSlice]:
        slice_size = order.quantity // self.num_slices
        remaining_quantity = order.quantity
        slices = []
        
        slice_interval = self.time_horizon / self.num_slices
        
        for i in range(self.num_slices):
            if i == self.num_slices - 1:
                current_slice_size = remaining_quantity
            else:
                current_slice_size = min(slice_size, remaining_quantity)
            
            if current_slice_size <= 0:
                break
            
            venue = venues[i % len(venues)][0] if venues else Venue.NYSE
            
            slice_timestamp = datetime.utcnow() + (i * slice_interval)
            
            slice_order = OrderSlice(
                original_order_id=order.id,
                slice_id=f"{order.id}_slice_{i}",
                instrument=order.instrument,
                side=order.side,
                quantity=current_slice_size,
                price=order.price,
                venue=venue,
                order_type=order.order_type,
                timestamp=slice_timestamp,
                parent_strategy=RoutingStrategy.TWAP
            )
            
            slices.append(slice_order)
            remaining_quantity -= current_slice_size
        
        return slices


class VWAPSlicer:
    def __init__(self, historical_volume_profile: Optional[pd.Series] = None):
        self.volume_profile = historical_volume_profile

    def slice_order(
        self,
        order: Order,
        venues: List[Tuple[Venue, float]],
        market_data: Dict[Venue, VenueInfo]
    ) -> List[OrderSlice]:
        if self.volume_profile is None:
            return self._equal_slices(order, venues)
        
        return self._volume_weighted_slices(order, venues, market_data)

    def _equal_slices(self, order: Order, venues: List[Tuple[Venue, float]]) -> List[OrderSlice]:
        num_slices = 10
        slice_size = order.quantity // num_slices
        remaining_quantity = order.quantity
        slices = []
        
        for i in range(num_slices):
            if i == num_slices - 1:
                current_slice_size = remaining_quantity
            else:
                current_slice_size = min(slice_size, remaining_quantity)
            
            if current_slice_size <= 0:
                break
            
            venue = venues[i % len(venues)][0] if venues else Venue.NYSE
            
            slice_order = OrderSlice(
                original_order_id=order.id,
                slice_id=f"{order.id}_vwap_slice_{i}",
                instrument=order.instrument,
                side=order.side,
                quantity=current_slice_size,
                price=order.price,
                venue=venue,
                order_type=order.order_type,
                timestamp=datetime.utcnow(),
                parent_strategy=RoutingStrategy.VWAP
            )
            
            slices.append(slice_order)
            remaining_quantity -= current_slice_size
        
        return slices

    def _volume_weighted_slices(
        self,
        order: Order,
        venues: List[Tuple[Venue, float]],
        market_data: Dict[Venue, VenueInfo]
    ) -> List[OrderSlice]:
        total_volume = sum(info.market_data.volume or 0 for info in market_data.values())
        
        if total_volume == 0:
            return self._equal_slices(order, venues)
        
        slices = []
        remaining_quantity = order.quantity
        
        for i, (venue, score) in enumerate(venues):
            if venue in market_data:
                venue_volume = market_data[venue].market_data.volume or 0
                volume_proportion = venue_volume / total_volume
                slice_quantity = int(order.quantity * volume_proportion)
                
                if slice_quantity > 0 and remaining_quantity > 0:
                    actual_slice_quantity = min(slice_quantity, remaining_quantity)
                    
                    slice_order = OrderSlice(
                        original_order_id=order.id,
                        slice_id=f"{order.id}_vwap_slice_{i}",
                        instrument=order.instrument,
                        side=order.side,
                        quantity=actual_slice_quantity,
                        price=order.price,
                        venue=venue,
                        order_type=order.order_type,
                        timestamp=datetime.utcnow(),
                        parent_strategy=RoutingStrategy.VWAP
                    )
                    
                    slices.append(slice_order)
                    remaining_quantity -= actual_slice_quantity
        
        if remaining_quantity > 0 and venues:
            last_slice = slices[-1] if slices else None
            if last_slice:
                last_slice.quantity += remaining_quantity
            else:
                cleanup_slice = OrderSlice(
                    original_order_id=order.id,
                    slice_id=f"{order.id}_vwap_cleanup",
                    instrument=order.instrument,
                    side=order.side,
                    quantity=remaining_quantity,
                    price=order.price,
                    venue=venues[0][0],
                    order_type=order.order_type,
                    timestamp=datetime.utcnow(),
                    parent_strategy=RoutingStrategy.VWAP
                )
                slices.append(cleanup_slice)
        
        return slices


class ImplementationShortfallSlicer:
    def __init__(self, risk_aversion: float = 0.5):
        self.risk_aversion = risk_aversion

    def slice_order(
        self,
        order: Order,
        venues: List[Tuple[Venue, float]],
        market_data: Dict[Venue, VenueInfo],
        volatility: float = 0.02
    ) -> List[OrderSlice]:
        optimal_rate = self._calculate_optimal_participation_rate(
            order.quantity, volatility, market_data
        )
        
        total_expected_volume = sum(
            info.market_data.volume or 0 for info in market_data.values()
        )
        
        if total_expected_volume == 0:
            return self._fallback_slicing(order, venues)
        
        target_completion_volume = order.quantity / optimal_rate
        num_slices = min(10, max(3, int(target_completion_volume / 1000)))
        
        slices = []
        remaining_quantity = order.quantity
        
        for i in range(num_slices):
            slice_size = int(remaining_quantity / (num_slices - i))
            
            if slice_size <= 0:
                break
            
            venue = venues[i % len(venues)][0] if venues else Venue.NYSE
            urgency = (i + 1) / num_slices
            
            slice_order = OrderSlice(
                original_order_id=order.id,
                slice_id=f"{order.id}_is_slice_{i}",
                instrument=order.instrument,
                side=order.side,
                quantity=slice_size,
                price=order.price,
                venue=venue,
                order_type=order.order_type,
                timestamp=datetime.utcnow(),
                parent_strategy=RoutingStrategy.IMPLEMENTATION_SHORTFALL,
                urgency_score=urgency
            )
            
            slices.append(slice_order)
            remaining_quantity -= slice_size
        
        return slices

    def _calculate_optimal_participation_rate(
        self,
        order_size: int,
        volatility: float,
        market_data: Dict[Venue, VenueInfo]
    ) -> float:
        total_volume = sum(info.market_data.volume or 0 for info in market_data.values())
        
        if total_volume == 0:
            return 0.1
        
        gamma = self.risk_aversion
        sigma = volatility
        
        optimal_rate = np.sqrt(gamma * sigma / (2 * order_size / total_volume))
        
        return min(max(optimal_rate, 0.05), 0.5)

    def _fallback_slicing(self, order: Order, venues: List[Tuple[Venue, float]]) -> List[OrderSlice]:
        slicer = TWAPSlicer(timedelta(minutes=30))
        return slicer.slice_order(order, venues)


class SmartOrderRouter:
    def __init__(self):
        self.venue_selector = CostBasedVenueSelector()
        self.slicers = {
            RoutingStrategy.TWAP: TWAPSlicer(timedelta(minutes=30)),
            RoutingStrategy.VWAP: VWAPSlicer(),
            RoutingStrategy.IMPLEMENTATION_SHORTFALL: ImplementationShortfallSlicer()
        }
        self.active_orders: Dict[str, List[OrderSlice]] = {}
        self.execution_engines: Dict[Venue, OrderExecutionEngine] = {}

    def route_order(
        self,
        order: Order,
        venue_info: Dict[Venue, VenueInfo],
        routing_params: RoutingParameters
    ) -> List[OrderSlice]:
        selected_venues = self.venue_selector.select_venues(
            order, venue_info, routing_params
        )
        
        if not selected_venues:
            raise ExecutionError(f"No suitable venues found for order {order.id}")
        
        slicer = self.slicers.get(routing_params.strategy)
        if not slicer:
            slicer = self.slicers[RoutingStrategy.TWAP]
        
        if routing_params.strategy == RoutingStrategy.VWAP:
            slices = slicer.slice_order(order, selected_venues, venue_info)
        elif routing_params.strategy == RoutingStrategy.IMPLEMENTATION_SHORTFALL:
            volatility = self._estimate_volatility(order.instrument, venue_info)
            slices = slicer.slice_order(order, selected_venues, venue_info, volatility)
        else:
            slices = slicer.slice_order(order, selected_venues)
        
        self.active_orders[order.id] = slices
        
        return slices

    async def execute_slices(
        self,
        slices: List[OrderSlice],
        routing_params: RoutingParameters
    ) -> List[Fill]:
        fills = []
        
        if routing_params.strategy == RoutingStrategy.AGGRESSIVE:
            fills = await self._execute_aggressive(slices)
        else:
            fills = await self._execute_with_timing(slices, routing_params)
        
        return fills

    async def _execute_aggressive(self, slices: List[OrderSlice]) -> List[Fill]:
        tasks = []
        
        for slice_order in slices:
            if slice_order.venue in self.execution_engines:
                engine = self.execution_engines[slice_order.venue]
                task = asyncio.create_task(self._execute_single_slice(engine, slice_order))
                tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        fills = []
        for result in results:
            if isinstance(result, Fill):
                fills.append(result)
            elif isinstance(result, Exception):
                print(f"Execution error: {result}")
        
        return fills

    async def _execute_with_timing(
        self,
        slices: List[OrderSlice],
        routing_params: RoutingParameters
    ) -> List[Fill]:
        fills = []
        
        for slice_order in slices:
            if slice_order.timestamp > datetime.utcnow():
                delay = (slice_order.timestamp - datetime.utcnow()).total_seconds()
                await asyncio.sleep(max(0, delay))
            
            if slice_order.venue in self.execution_engines:
                engine = self.execution_engines[slice_order.venue]
                try:
                    fill = await self._execute_single_slice(engine, slice_order)
                    if fill:
                        fills.append(fill)
                except Exception as e:
                    print(f"Failed to execute slice {slice_order.slice_id}: {e}")
        
        return fills

    async def _execute_single_slice(
        self,
        engine: OrderExecutionEngine,
        slice_order: OrderSlice
    ) -> Optional[Fill]:
        order = Order(
            id=slice_order.slice_id,
            instrument=slice_order.instrument,
            side=slice_order.side,
            order_type=slice_order.order_type,
            quantity=slice_order.quantity,
            price=slice_order.price,
            venue=slice_order.venue
        )
        
        try:
            order_id = await engine.submit_order(order)
            
            max_wait_time = 30
            wait_time = 0
            
            while wait_time < max_wait_time:
                status = await engine.get_order_status(order_id)
                
                if status == OrderStatus.FILLED:
                    return Fill(
                        order_id=order_id,
                        instrument=slice_order.instrument,
                        side=slice_order.side,
                        quantity=slice_order.quantity,
                        price=slice_order.price or 0,
                        timestamp=datetime.utcnow(),
                        venue=slice_order.venue,
                        trade_id=f"trade_{order_id}"
                    )
                elif status in [OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                    break
                
                await asyncio.sleep(1)
                wait_time += 1
            
            await engine.cancel_order(order_id)
            
        except Exception as e:
            raise ExecutionError(f"Failed to execute slice: {e}")
        
        return None

    def _estimate_volatility(
        self,
        instrument: Instrument,
        venue_info: Dict[Venue, VenueInfo]
    ) -> float:
        spreads = []
        
        for info in venue_info.values():
            if info.market_data.spread and info.market_data.mid_price:
                relative_spread = info.market_data.spread / info.market_data.mid_price
                spreads.append(relative_spread)
        
        if spreads:
            return np.mean(spreads) * 10
        else:
            return 0.02

    def add_execution_engine(self, venue: Venue, engine: OrderExecutionEngine) -> None:
        self.execution_engines[venue] = engine

    def get_order_status(self, order_id: str) -> Dict[str, str]:
        if order_id not in self.active_orders:
            return {"status": "not_found"}
        
        slices = self.active_orders[order_id]
        slice_statuses = {}
        
        for slice_order in slices:
            slice_statuses[slice_order.slice_id] = "pending"
        
        return {
            "status": "active",
            "total_slices": len(slices),
            "slice_statuses": slice_statuses
        }

    async def cancel_order(self, order_id: str) -> bool:
        if order_id not in self.active_orders:
            return False
        
        slices = self.active_orders[order_id]
        cancellation_tasks = []
        
        for slice_order in slices:
            if slice_order.venue in self.execution_engines:
                engine = self.execution_engines[slice_order.venue]
                task = asyncio.create_task(engine.cancel_order(slice_order.slice_id))
                cancellation_tasks.append(task)
        
        results = await asyncio.gather(*cancellation_tasks, return_exceptions=True)
        
        del self.active_orders[order_id]
        
        return any(isinstance(result, bool) and result for result in results)


class OrderRoutingEngine:
    def __init__(self):
        self.router = SmartOrderRouter()
        self.venue_monitor = VenueMonitor()
        
    async def route_and_execute(
        self,
        order: Order,
        routing_params: Optional[RoutingParameters] = None
    ) -> List[Fill]:
        if routing_params is None:
            routing_params = RoutingParameters(strategy=RoutingStrategy.TWAP)
        
        venue_info = await self.venue_monitor.get_venue_information(order.instrument)
        
        slices = self.router.route_order(order, venue_info, routing_params)
        
        fills = await self.router.execute_slices(slices, routing_params)
        
        return fills


class VenueMonitor:
    def __init__(self):
        self.venue_data: Dict[Venue, VenueInfo] = {}
        self.last_update: Optional[datetime] = None
        
    async def get_venue_information(self, instrument: Instrument) -> Dict[Venue, VenueInfo]:
        if self._needs_update():
            await self._update_venue_data(instrument)
        
        return self.venue_data.copy()
    
    def _needs_update(self) -> bool:
        if self.last_update is None:
            return True
        
        time_since_update = datetime.utcnow() - self.last_update
        return time_since_update > timedelta(seconds=30)
    
    async def _update_venue_data(self, instrument: Instrument) -> None:
        mock_venues = [Venue.NYSE, Venue.NASDAQ, Venue.BATS, Venue.ARCA, Venue.IEX]
        
        for venue in mock_venues:
            mock_market_data = MarketData(
                instrument=instrument,
                timestamp=datetime.utcnow(),
                bid=100.0 + np.random.normal(0, 0.1),
                ask=100.1 + np.random.normal(0, 0.1),
                last=100.05 + np.random.normal(0, 0.1),
                volume=np.random.randint(1000, 10000),
                bid_size=np.random.randint(100, 1000),
                ask_size=np.random.randint(100, 1000)
            )
            
            venue_info = VenueInfo(
                venue=venue,
                market_data=mock_market_data,
                fees=0.001 + np.random.uniform(0, 0.002),
                rebates=0.0005 + np.random.uniform(0, 0.001),
                latency_ms=np.random.uniform(1, 10),
                fill_probability=0.8 + np.random.uniform(0, 0.2),
                dark_pool=venue == Venue.DARK_POOL
            )
            
            self.venue_data[venue] = venue_info
        
        self.last_update = datetime.utcnow()