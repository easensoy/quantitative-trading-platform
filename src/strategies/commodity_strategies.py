from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from src.core.models import (
    Instrument, MarketData, Order, OrderSide, OrderType, Strategy,
    CommodityInstrument, CommodityFuturesPrice
)
from src.data.commodity_provider import CommodityDataProvider, CommodityCurveBuilder


class CommodityStrategy(ABC):
    def __init__(self, strategy_id: str, name: str):
        self.strategy_id = strategy_id
        self.name = name
        self.provider: Optional[CommodityDataProvider] = None
        self.curve_builder: Optional[CommodityCurveBuilder] = None
        
    @abstractmethod
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        pass
    
    def set_provider(self, provider: CommodityDataProvider):
        self.provider = provider
        self.curve_builder = CommodityCurveBuilder(provider)


class ContangoBackwardationStrategy(CommodityStrategy):
    def __init__(self, threshold: float = 0.05, lookback_days: int = 20):
        super().__init__("contango_backwardation", "Contango/Backwardation Strategy")
        self.threshold = threshold
        self.lookback_days = lookback_days
        self.price_history: Dict[str, List[float]] = {}
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        orders = []
        
        for symbol, data in market_data.items():
            if not isinstance(data.instrument, CommodityInstrument):
                continue
                
            instrument = data.instrument
            
            if self.curve_builder:
                curve = await self.curve_builder.build_futures_curve(instrument, months_out=6)
                signal = await self._analyze_curve_shape(curve, instrument)
                
                if signal:
                    order = await self._create_order(signal, instrument, data)
                    if order:
                        orders.append(order)
        
        return orders
    
    async def _analyze_curve_shape(self, curve: List[CommodityFuturesPrice], 
                                 instrument: CommodityInstrument) -> Optional[Dict]:
        if len(curve) < 3:
            return None
        
        near_month = curve[0]
        far_month = curve[-1]
        
        curve_slope = (far_month.futures_price - near_month.futures_price) / near_month.futures_price
        
        if curve_slope > self.threshold:
            return {
                'action': 'sell_calendar',
                'reason': 'steep_contango',
                'confidence': min(abs(curve_slope) / self.threshold, 1.0),
                'front_month': near_month,
                'back_month': far_month
            }
        elif curve_slope < -self.threshold:
            return {
                'action': 'buy_calendar',
                'reason': 'backwardation',
                'confidence': min(abs(curve_slope) / self.threshold, 1.0),
                'front_month': near_month,
                'back_month': far_month
            }
        
        return None
    
    async def _create_order(self, signal: Dict, instrument: CommodityInstrument, 
                          data: MarketData) -> Optional[Order]:
        if signal['confidence'] < 0.6:
            return None
        
        quantity = int(10 * signal['confidence'])
        
        if signal['action'] == 'sell_calendar':
            side = OrderSide.SELL
        else:
            side = OrderSide.BUY
        
        return Order(
            id=f"{self.strategy_id}_{instrument.symbol}_{datetime.utcnow().timestamp()}",
            instrument=instrument,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=data.mid_price,
            strategy_id=self.strategy_id
        )


class SeasonalityStrategy(CommodityStrategy):
    def __init__(self):
        super().__init__("seasonality", "Commodity Seasonality Strategy")
        self.seasonal_patterns = self._load_seasonal_patterns()
        
    def _load_seasonal_patterns(self) -> Dict[str, List[float]]:
        return {
            'NG': [1.2, 1.1, 0.9, 0.8, 0.7, 0.8, 0.9, 0.9, 1.0, 1.1, 1.2, 1.3],
            'HO': [1.1, 1.1, 1.0, 0.9, 0.9, 0.9, 0.9, 1.0, 1.0, 1.1, 1.1, 1.1],
            'C': [0.9, 0.9, 1.0, 1.1, 1.2, 1.2, 1.1, 1.0, 0.9, 0.8, 0.9, 0.9],
            'W': [1.0, 1.0, 1.1, 1.2, 1.2, 1.1, 1.0, 0.9, 0.9, 0.9, 1.0, 1.0],
            'S': [0.9, 0.9, 1.0, 1.1, 1.1, 1.2, 1.2, 1.1, 1.0, 0.9, 0.9, 0.9]
        }
    
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        orders = []
        current_month = datetime.now().month
        
        for symbol, data in market_data.items():
            if not isinstance(data.instrument, CommodityInstrument):
                continue
            
            instrument = data.instrument
            symbol_upper = instrument.symbol.upper()
            
            if symbol_upper not in self.seasonal_patterns:
                continue
            
            pattern = self.seasonal_patterns[symbol_upper]
            current_factor = pattern[current_month - 1]
            next_month_factor = pattern[current_month % 12]
            
            seasonal_signal = next_month_factor - current_factor
            
            if abs(seasonal_signal) > 0.1:
                order = await self._create_seasonal_order(seasonal_signal, instrument, data)
                if order:
                    orders.append(order)
        
        return orders
    
    async def _create_seasonal_order(self, signal: float, instrument: CommodityInstrument, 
                                   data: MarketData) -> Optional[Order]:
        if abs(signal) < 0.1:
            return None
        
        side = OrderSide.BUY if signal > 0 else OrderSide.SELL
        quantity = int(abs(signal) * 50)
        
        return Order(
            id=f"{self.strategy_id}_{instrument.symbol}_{datetime.utcnow().timestamp()}",
            instrument=instrument,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=data.mid_price,
            strategy_id=self.strategy_id
        )


class CommodityMomentumStrategy(CommodityStrategy):
    def __init__(self, lookback_period: int = 20, threshold: float = 0.02):
        super().__init__("commodity_momentum", "Commodity Momentum Strategy")
        self.lookback_period = lookback_period
        self.threshold = threshold
        self.price_history: Dict[str, List[Tuple[datetime, float]]] = {}
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        orders = []
        
        for symbol, data in market_data.items():
            if not isinstance(data.instrument, CommodityInstrument):
                continue
            
            self._update_price_history(symbol, data)
            
            momentum_signal = self._calculate_momentum(symbol)
            
            if momentum_signal and abs(momentum_signal['strength']) > self.threshold:
                order = await self._create_momentum_order(momentum_signal, data.instrument, data)
                if order:
                    orders.append(order)
        
        return orders
    
    def _update_price_history(self, symbol: str, data: MarketData):
        if symbol not in self.price_history:
            self.price_history[symbol] = []
        
        self.price_history[symbol].append((data.timestamp, data.mid_price))
        
        cutoff_time = datetime.utcnow() - timedelta(days=self.lookback_period + 5)
        self.price_history[symbol] = [
            (ts, price) for ts, price in self.price_history[symbol] 
            if ts > cutoff_time
        ]
    
    def _calculate_momentum(self, symbol: str) -> Optional[Dict]:
        if symbol not in self.price_history or len(self.price_history[symbol]) < 10:
            return None
        
        prices = [price for _, price in self.price_history[symbol]]
        
        if len(prices) < self.lookback_period:
            return None
        
        recent_prices = prices[-10:]
        older_prices = prices[-self.lookback_period:-10]
        
        recent_avg = np.mean(recent_prices)
        older_avg = np.mean(older_prices)
        
        momentum_strength = (recent_avg - older_avg) / older_avg
        
        volatility = np.std(prices[-20:]) / np.mean(prices[-20:])
        
        risk_adjusted_momentum = momentum_strength / max(volatility, 0.01)
        
        return {
            'strength': momentum_strength,
            'direction': 'up' if momentum_strength > 0 else 'down',
            'risk_adjusted': risk_adjusted_momentum,
            'volatility': volatility
        }
    
    async def _create_momentum_order(self, signal: Dict, instrument: CommodityInstrument, 
                                   data: MarketData) -> Optional[Order]:
        if abs(signal['risk_adjusted']) < 0.5:
            return None
        
        side = OrderSide.BUY if signal['direction'] == 'up' else OrderSide.SELL
        
        confidence = min(abs(signal['risk_adjusted']) / 2.0, 1.0)
        quantity = int(confidence * 20)
        
        return Order(
            id=f"{self.strategy_id}_{instrument.symbol}_{datetime.utcnow().timestamp()}",
            instrument=instrument,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=data.mid_price,
            strategy_id=self.strategy_id
        )


class EnergySpreadStrategy(CommodityStrategy):
    def __init__(self):
        super().__init__("energy_spread", "Energy Spread Strategy")
        self.spread_history: Dict[str, List[float]] = {}
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        orders = []
        
        crude_data = None
        gasoline_data = None
        heating_oil_data = None
        
        for symbol, data in market_data.items():
            if data.instrument.symbol.upper() == 'CL':
                crude_data = data
            elif data.instrument.symbol.upper() == 'RB':
                gasoline_data = data
            elif data.instrument.symbol.upper() == 'HO':
                heating_oil_data = data
        
        if crude_data and gasoline_data:
            crack_spread_signal = await self._analyze_crack_spread(crude_data, gasoline_data, 'gasoline')
            if crack_spread_signal:
                orders.extend(crack_spread_signal)
        
        if crude_data and heating_oil_data:
            crack_spread_signal = await self._analyze_crack_spread(crude_data, heating_oil_data, 'heating_oil')
            if crack_spread_signal:
                orders.extend(crack_spread_signal)
        
        return orders
    
    async def _analyze_crack_spread(self, crude_data: MarketData, product_data: MarketData, 
                                  product_type: str) -> List[Order]:
        spread = product_data.mid_price - crude_data.mid_price
        spread_key = f"{product_type}_crack"
        
        if spread_key not in self.spread_history:
            self.spread_history[spread_key] = []
        
        self.spread_history[spread_key].append(spread)
        
        if len(self.spread_history[spread_key]) > 50:
            self.spread_history[spread_key] = self.spread_history[spread_key][-50:]
        
        if len(self.spread_history[spread_key]) < 20:
            return []
        
        recent_spreads = self.spread_history[spread_key]
        mean_spread = np.mean(recent_spreads)
        std_spread = np.std(recent_spreads)
        
        z_score = (spread - mean_spread) / max(std_spread, 0.01)
        
        orders = []
        
        if z_score > 2.0:
            crude_order = Order(
                id=f"{self.strategy_id}_crude_{datetime.utcnow().timestamp()}",
                instrument=crude_data.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=crude_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            product_order = Order(
                id=f"{self.strategy_id}_{product_type}_{datetime.utcnow().timestamp()}",
                instrument=product_data.instrument,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=product_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            orders.extend([crude_order, product_order])
        
        elif z_score < -2.0:
            crude_order = Order(
                id=f"{self.strategy_id}_crude_{datetime.utcnow().timestamp()}",
                instrument=crude_data.instrument,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=crude_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            product_order = Order(
                id=f"{self.strategy_id}_{product_type}_{datetime.utcnow().timestamp()}",
                instrument=product_data.instrument,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=product_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            orders.extend([crude_order, product_order])
        
        return orders


class CommodityCarryTradeStrategy(CommodityStrategy):
    def __init__(self, min_carry_threshold: float = 0.02):
        super().__init__("commodity_carry", "Commodity Carry Trade Strategy")
        self.min_carry_threshold = min_carry_threshold
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        orders = []
        
        for symbol, data in market_data.items():
            if not isinstance(data.instrument, CommodityInstrument):
                continue
            
            instrument = data.instrument
            
            if self.curve_builder:
                carry_analysis = await self._analyze_carry_trade(instrument)
                
                if carry_analysis and abs(carry_analysis['expected_return']) > self.min_carry_threshold:
                    order = await self._create_carry_order(carry_analysis, instrument, data)
                    if order:
                        orders.append(order)
        
        return orders
    
    async def _analyze_carry_trade(self, instrument: CommodityInstrument) -> Optional[Dict]:
        if not self.curve_builder:
            return None
        
        curve = await self.curve_builder.build_futures_curve(instrument, months_out=6)
        
        if len(curve) < 2:
            return None
        
        front_month = curve[0]
        back_month = curve[1]
        
        storage_cost_annualized = front_month.storage_cost
        convenience_yield_annualized = front_month.convenience_yield
        risk_free_rate = front_month.risk_free_rate
        
        expected_return = convenience_yield_annualized - storage_cost_annualized
        
        price_convergence = (front_month.futures_price - back_month.futures_price) / back_month.time_to_maturity
        
        total_expected_return = expected_return + price_convergence / front_month.futures_price
        
        return {
            'expected_return': total_expected_return,
            'storage_cost': storage_cost_annualized,
            'convenience_yield': convenience_yield_annualized,
            'price_convergence': price_convergence,
            'front_month_price': front_month.futures_price,
            'back_month_price': back_month.futures_price
        }
    
    async def _create_carry_order(self, analysis: Dict, instrument: CommodityInstrument, 
                                data: MarketData) -> Optional[Order]:
        expected_return = analysis['expected_return']
        
        if abs(expected_return) < self.min_carry_threshold:
            return None
        
        side = OrderSide.BUY if expected_return > 0 else OrderSide.SELL
        
        confidence = min(abs(expected_return) / (self.min_carry_threshold * 2), 1.0)
        quantity = int(confidence * 15)
        
        return Order(
            id=f"{self.strategy_id}_{instrument.symbol}_{datetime.utcnow().timestamp()}",
            instrument=instrument,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=data.mid_price,
            strategy_id=self.strategy_id
        )