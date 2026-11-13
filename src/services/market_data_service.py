from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable
from datetime import datetime
import asyncio

from src.core.models import Instrument, MarketData, MarketDataProvider
from src.core.event_bus import EventBus
from src.core.container import Injectable, service
from src.core.implementations import SimulatedMarketDataProvider, YahooFinanceDataProvider


class MarketDataServiceInterface(ABC):
    @abstractmethod
    async def subscribe_to_instruments(self, instruments: List[Instrument]) -> None:
        pass
    
    @abstractmethod
    async def get_latest_data(self, instrument: Instrument) -> Optional[MarketData]:
        pass
    
    @abstractmethod
    async def start_streaming(self) -> None:
        pass
    
    @abstractmethod
    async def stop_streaming(self) -> None:
        pass


@service("market_data_service")
class MarketDataService(MarketDataServiceInterface, Injectable):
    """Polls the provider for subscribed instruments and publishes each quote as a
    "market_data" event. This service is the only publisher of market data."""

    def __init__(self, event_bus: EventBus, provider: MarketDataProvider, poll_interval: float = 1.0):
        self.event_bus = event_bus
        self.provider = provider
        self.poll_interval = poll_interval
        self.subscribed_instruments: List[Instrument] = []
        self.latest_data: Dict[str, MarketData] = {}
        self.streaming_task: Optional[asyncio.Task] = None
        self.callbacks: Dict[str, List[Callable]] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Subscribe to the event bus. Safe to call more than once."""
        if self._initialized:
            return
        await self.event_bus.subscribe("market_data", self._handle_market_data)
        self._initialized = True
        
    async def subscribe_to_instruments(self, instruments: List[Instrument]) -> None:
        await self.initialize()
        new_instruments = [inst for inst in instruments if inst not in self.subscribed_instruments]
        if new_instruments:
            await self.provider.subscribe_market_data(new_instruments)
            self.subscribed_instruments.extend(new_instruments)
            
    async def get_latest_data(self, instrument: Instrument) -> Optional[MarketData]:
        if instrument.symbol in self.latest_data:
            return self.latest_data[instrument.symbol]
        return await self.provider.get_market_data(instrument)

    def get_latest_price(self, instrument: Instrument) -> Optional[float]:
        """Last traded (or mid) price from the most recent quote, if one has arrived."""
        market_data = self.latest_data.get(instrument.symbol)
        if market_data is None:
            return None
        return market_data.last or market_data.mid_price
    
    async def start_streaming(self) -> None:
        if self.streaming_task is None:
            self.streaming_task = asyncio.create_task(self._stream_data())
    
    async def stop_streaming(self) -> None:
        if self.streaming_task:
            self.streaming_task.cancel()
            try:
                await self.streaming_task
            except asyncio.CancelledError:
                pass
            self.streaming_task = None
    
    def add_callback(self, symbol: str, callback: Callable) -> None:
        if symbol not in self.callbacks:
            self.callbacks[symbol] = []
        self.callbacks[symbol].append(callback)
    
    async def _handle_market_data(self, data: Dict) -> None:
        symbol = data["symbol"]
        market_data = data["market_data"]
        
        self.latest_data[symbol] = market_data
        
        if symbol in self.callbacks:
            for callback in self.callbacks[symbol]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(market_data)
                    else:
                        callback(market_data)
                except Exception as e:
                    print(f"Callback error for {symbol}: {e}")
    
    async def _stream_data(self) -> None:
        while True:
            try:
                for instrument in self.subscribed_instruments:
                    market_data = await self.provider.get_market_data(instrument)
                    await self.event_bus.publish("market_data", {
                        "symbol": instrument.symbol,
                        "market_data": market_data
                    })
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Market data streaming error: {e}")
                await asyncio.sleep(5)


class MarketDataFactory:
    @staticmethod
    def create_provider(provider_type: str, seed: Optional[int] = None) -> MarketDataProvider:
        if provider_type == "yahoo":
            return YahooFinanceDataProvider()
        elif provider_type == "simulated":
            return SimulatedMarketDataProvider(seed=seed)
        return SimulatedMarketDataProvider(seed=seed)
    
    @staticmethod
    def create_service(
        event_bus: EventBus,
        provider_type: str = "simulated",
        poll_interval: float = 1.0,
        seed: Optional[int] = None,
    ) -> MarketDataService:
        provider = MarketDataFactory.create_provider(provider_type, seed=seed)
        return MarketDataService(event_bus, provider, poll_interval=poll_interval)