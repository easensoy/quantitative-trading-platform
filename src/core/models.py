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
    GOVERNMENT_BOND = "government_bond"
    CORPORATE_BOND = "corporate_bond"
    COMMODITY_FUTURE = "commodity_future"
    INTEREST_RATE_FUTURE = "interest_rate_future"


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


@dataclass(frozen=True)
class FixedIncomeInstrument(Instrument):
    maturity_date: datetime
    coupon_rate: float
    face_value: float = 1000.0
    payment_frequency: int = 2
    day_count_convention: str = "30/360"
    credit_rating: Optional[str] = None
    yield_to_maturity: Optional[float] = None
    duration: Optional[float] = None
    convexity: Optional[float] = None
    
    @property
    def time_to_maturity(self) -> float:
        return (self.maturity_date - datetime.utcnow()).days / 365.25
    
    @property
    def is_government(self) -> bool:
        return self.asset_type == AssetType.GOVERNMENT_BOND


@dataclass(frozen=True)
class CommodityInstrument(Instrument):
    contract_month: str
    delivery_date: datetime
    grade: str
    delivery_location: str
    lot_size_unit: str
    storage_cost_rate: float = 0.0
    convenience_yield: float = 0.0
    
    @property
    def time_to_delivery(self) -> float:
        return (self.delivery_date - datetime.utcnow()).days / 365.25
    
    @property
    def is_energy(self) -> bool:
        return self.symbol.upper() in ['CL', 'NG', 'HO', 'RB', 'BZ']
    
    @property
    def is_metals(self) -> bool:
        return self.symbol.upper() in ['GC', 'SI', 'HG', 'PL', 'PA']
    
    @property
    def is_agriculture(self) -> bool:
        return self.symbol.upper() in ['C', 'W', 'S', 'SM', 'BO', 'CC', 'KC', 'SB', 'CT']


@dataclass
class YieldCurvePoint:
    maturity: float
    yield_rate: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


class YieldCurve:
    def __init__(self, points: List[YieldCurvePoint], currency: str = "USD"):
        self.points = sorted(points, key=lambda x: x.maturity)
        self.currency = currency
        self.timestamp = datetime.utcnow()
    
    def interpolate_yield(self, maturity: float) -> float:
        if not self.points:
            raise ValueError("No yield curve points available")
        
        if maturity <= self.points[0].maturity:
            return self.points[0].yield_rate
        
        if maturity >= self.points[-1].maturity:
            return self.points[-1].yield_rate
        
        for i in range(len(self.points) - 1):
            if self.points[i].maturity <= maturity <= self.points[i + 1].maturity:
                t1, y1 = self.points[i].maturity, self.points[i].yield_rate
                t2, y2 = self.points[i + 1].maturity, self.points[i + 1].yield_rate
                
                weight = (maturity - t1) / (t2 - t1)
                return y1 + weight * (y2 - y1)
        
        return self.points[-1].yield_rate
    
    def get_forward_rate(self, start_maturity: float, end_maturity: float) -> float:
        r1 = self.interpolate_yield(start_maturity)
        r2 = self.interpolate_yield(end_maturity)
        
        return ((1 + r2) ** end_maturity / (1 + r1) ** start_maturity) ** (1 / (end_maturity - start_maturity)) - 1


@dataclass
class CommodityFuturesPrice:
    spot_price: float
    futures_price: float
    time_to_maturity: float
    risk_free_rate: float
    storage_cost: float = 0.0
    convenience_yield: float = 0.0
    
    @property
    def cost_of_carry(self) -> float:
        return self.risk_free_rate + self.storage_cost - self.convenience_yield
    
    @property
    def theoretical_price(self) -> float:
        return self.spot_price * np.exp(self.cost_of_carry * self.time_to_maturity)
    
    @property
    def basis(self) -> float:
        return self.futures_price - self.spot_price
    
    @property
    def contango_backwardation(self) -> str:
        return "contango" if self.futures_price > self.spot_price else "backwardation"


class FixedIncomePricer:
    @staticmethod
    def calculate_bond_price(bond: FixedIncomeInstrument, yield_rate: float) -> float:
        if bond.time_to_maturity <= 0:
            return bond.face_value
        
        coupon_payment = bond.face_value * bond.coupon_rate / bond.payment_frequency
        periods = int(bond.time_to_maturity * bond.payment_frequency)
        
        pv_coupons = sum(
            coupon_payment / (1 + yield_rate / bond.payment_frequency) ** i
            for i in range(1, periods + 1)
        )
        
        pv_principal = bond.face_value / (1 + yield_rate / bond.payment_frequency) ** periods
        
        return pv_coupons + pv_principal
    
    @staticmethod
    def calculate_duration(bond: FixedIncomeInstrument, yield_rate: float) -> float:
        coupon_payment = bond.face_value * bond.coupon_rate / bond.payment_frequency
        periods = int(bond.time_to_maturity * bond.payment_frequency)
        
        weighted_cf = sum(
            (i / bond.payment_frequency) * coupon_payment / (1 + yield_rate / bond.payment_frequency) ** i
            for i in range(1, periods + 1)
        )
        
        weighted_cf += (periods / bond.payment_frequency) * bond.face_value / (1 + yield_rate / bond.payment_frequency) ** periods
        
        bond_price = FixedIncomePricer.calculate_bond_price(bond, yield_rate)
        
        return weighted_cf / bond_price
    
    @staticmethod
    def calculate_convexity(bond: FixedIncomeInstrument, yield_rate: float) -> float:
        coupon_payment = bond.face_value * bond.coupon_rate / bond.payment_frequency
        periods = int(bond.time_to_maturity * bond.payment_frequency)
        
        weighted_cf = sum(
            i * (i + 1) * coupon_payment / (1 + yield_rate / bond.payment_frequency) ** (i + 2)
            for i in range(1, periods + 1)
        )
        
        weighted_cf += periods * (periods + 1) * bond.face_value / (1 + yield_rate / bond.payment_frequency) ** (periods + 2)
        
        bond_price = FixedIncomePricer.calculate_bond_price(bond, yield_rate)
        
        return weighted_cf / (bond_price * bond.payment_frequency ** 2)