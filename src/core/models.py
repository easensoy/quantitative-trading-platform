from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field
import numpy as np
import pandas as pd


class AssetType(Enum):
    EQUITY = "equity"
    BOND = "bond"
    OPTION = "option"
    FUTURE = "future"
    FX = "fx"
    CRYPTO = "crypto"
    COMMODITY = "commodity"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Venue(Enum):
    NYSE = "nyse"
    NASDAQ = "nasdaq"
    BATS = "bats"
    ARCA = "arca"
    IEX = "iex"
    DARK_POOL = "dark_pool"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_type: AssetType
    exchange: str
    currency: str = "USD"
    multiplier: float = 1.0
    tick_size: float = 0.01
    lot_size: int = 1
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("Symbol cannot be empty")


@dataclass
class MarketData:
    instrument: Instrument
    timestamp: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    
    @property
    def mid_price(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last
    
    @property
    def spread(self) -> Optional[float]:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None


@dataclass
class Order:
    id: str
    instrument: Instrument
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Optional[float] = None
    stop_price: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: Optional[float] = None
    venue: Optional[Venue] = None
    strategy_id: Optional[str] = None
    
    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity
    
    @property
    def is_complete(self) -> bool:
        return self.filled_quantity >= self.quantity


@dataclass
class Fill:
    order_id: str
    instrument: Instrument
    side: OrderSide
    quantity: int
    price: float
    timestamp: datetime
    venue: Venue
    trade_id: str
    commission: float = 0.0
    
    @property
    def notional(self) -> float:
        return self.quantity * self.price


@dataclass
class Position:
    instrument: Instrument
    quantity: int
    avg_price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    strategy_id: Optional[str] = None
    
    @property
    def notional(self) -> float:
        return self.quantity * self.avg_price
    
    @property
    def is_long(self) -> bool:
        return self.quantity > 0
    
    @property
    def is_short(self) -> bool:
        return self.quantity < 0
    
    @property
    def is_flat(self) -> bool:
        return self.quantity == 0


class Portfolio(BaseModel):
    id: str
    name: str
    positions: Dict[str, Position] = Field(default_factory=dict)
    cash: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    def add_position(self, position: Position) -> None:
        self.positions[position.instrument.symbol] = position
    
    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
    
    def update_position(self, fill: Fill) -> None:
        symbol = fill.instrument.symbol
        current_pos = self.positions.get(symbol)
        
        if current_pos is None:
            new_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            self.positions[symbol] = Position(
                instrument=fill.instrument,
                quantity=new_qty,
                avg_price=fill.price,
                strategy_id=None
            )
        else:
            fill_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            new_qty = current_pos.quantity + fill_qty
            
            if new_qty == 0:
                del self.positions[symbol]
            else:
                if (current_pos.quantity > 0 and fill_qty > 0) or (current_pos.quantity < 0 and fill_qty < 0):
                    total_cost = (current_pos.quantity * current_pos.avg_price) + (fill_qty * fill.price)
                    new_avg_price = total_cost / new_qty
                else:
                    new_avg_price = fill.price
                
                current_pos.quantity = new_qty
                current_pos.avg_price = new_avg_price
    
    @property
    def total_notional(self) -> float:
        return sum(pos.notional for pos in self.positions.values())


@dataclass
class Strategy:
    id: str
    name: str
    description: str
    parameters: Dict = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class MarketDataProvider(ABC):
    @abstractmethod
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        pass
    
    @abstractmethod
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        pass


class OrderExecutionEngine(ABC):
    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass
    
    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderStatus:
        pass


class RiskManager(ABC):
    @abstractmethod
    def validate_order(self, order: Order, portfolio: Portfolio) -> bool:
        pass
    
    @abstractmethod
    def calculate_risk_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        pass


@dataclass
class BacktestResult:
    strategy_id: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    pnl_series: pd.Series
    positions_history: List[Position]
    
    @property
    def annualized_return(self) -> float:
        days = (self.end_date - self.start_date).days
        return (self.final_capital / self.initial_capital) ** (365.25 / days) - 1


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event_type: str, data: Dict) -> None:
        pass
    
    @abstractmethod
    async def subscribe(self, event_type: str, callback) -> None:
        pass


@dataclass
class PnLAttribution:
    strategy_id: str
    timestamp: datetime
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    attribution_factors: Dict[str, float] = field(default_factory=dict)