from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

from src.core.models import (
    Instrument, MarketData, Order, OrderSide, OrderType, Strategy,
    FixedIncomeInstrument, YieldCurve, FixedIncomePricer
)
from src.data.fixed_income_provider import FixedIncomeDataProvider, YieldCurveAnalyzer


class FixedIncomeStrategy(ABC):
    def __init__(self, strategy_id: str, name: str):
        self.strategy_id = strategy_id
        self.name = name
        self.provider: Optional[FixedIncomeDataProvider] = None
        self.curve_analyzer: Optional[YieldCurveAnalyzer] = None
        
    @abstractmethod
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        pass
    
    def set_provider(self, provider: FixedIncomeDataProvider):
        self.provider = provider
        self.curve_analyzer = YieldCurveAnalyzer(provider)


class YieldCurveSteepenerStrategy(FixedIncomeStrategy):
    def __init__(self, steepening_threshold: float = 0.01):
        super().__init__("yield_curve_steepener", "Yield Curve Steepening Strategy")
        self.steepening_threshold = steepening_threshold
        self.curve_history: List[Tuple[datetime, float]] = []
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        if not self.curve_analyzer:
            return []
        
        orders = []
        
        try:
            curve_metrics = await self.curve_analyzer.calculate_curve_metrics("USD")
            current_steepness = curve_metrics['ten_two_spread']
            
            self.curve_history.append((datetime.utcnow(), current_steepness))
            
            cutoff_time = datetime.utcnow() - timedelta(days=30)
            self.curve_history = [(ts, val) for ts, val in self.curve_history if ts > cutoff_time]
            
            if len(self.curve_history) < 10:
                return []
            
            historical_steepness = [val for _, val in self.curve_history[:-1]]
            avg_steepness = np.mean(historical_steepness)
            steepness_change = current_steepness - avg_steepness
            
            if abs(steepness_change) > self.steepening_threshold:
                short_term_bonds = []
                long_term_bonds = []
                
                for symbol, data in market_data.items():
                    if isinstance(data.instrument, FixedIncomeInstrument):
                        bond = data.instrument
                        if bond.time_to_maturity <= 3:
                            short_term_bonds.append((bond, data))
                        elif bond.time_to_maturity >= 8:
                            long_term_bonds.append((bond, data))
                
                if steepness_change > self.steepening_threshold:
                    orders.extend(await self._create_steepening_orders(short_term_bonds, long_term_bonds))
                elif steepness_change < -self.steepening_threshold:
                    orders.extend(await self._create_flattening_orders(short_term_bonds, long_term_bonds))
        
        except Exception as e:
            print(f"Error in yield curve strategy: {e}")
        
        return orders
    
    async def _create_steepening_orders(self, short_term_bonds: List, long_term_bonds: List) -> List[Order]:
        orders = []
        
        for bond, data in short_term_bonds[:2]:
            order = Order(
                id=f"{self.strategy_id}_short_{bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=bond,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=1000000,
                price=data.mid_price,
                strategy_id=self.strategy_id
            )
            orders.append(order)
        
        for bond, data in long_term_bonds[:2]:
            order = Order(
                id=f"{self.strategy_id}_long_{bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=bond,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=1000000,
                price=data.mid_price,
                strategy_id=self.strategy_id
            )
            orders.append(order)
        
        return orders
    
    async def _create_flattening_orders(self, short_term_bonds: List, long_term_bonds: List) -> List[Order]:
        orders = []
        
        for bond, data in short_term_bonds[:2]:
            order = Order(
                id=f"{self.strategy_id}_short_{bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=bond,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=1000000,
                price=data.mid_price,
                strategy_id=self.strategy_id
            )
            orders.append(order)
        
        for bond, data in long_term_bonds[:2]:
            order = Order(
                id=f"{self.strategy_id}_long_{bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=bond,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=1000000,
                price=data.mid_price,
                strategy_id=self.strategy_id
            )
            orders.append(order)
        
        return orders


class CreditSpreadStrategy(FixedIncomeStrategy):
    def __init__(self, spread_threshold: float = 0.005):
        super().__init__("credit_spread", "Credit Spread Strategy")
        self.spread_threshold = spread_threshold
        self.spread_history: Dict[str, List[Tuple[datetime, float]]] = {}
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        if not self.provider:
            return []
        
        orders = []
        government_bonds = {}
        corporate_bonds = {}
        
        for symbol, data in market_data.items():
            if isinstance(data.instrument, FixedIncomeInstrument):
                bond = data.instrument
                maturity_bucket = self._get_maturity_bucket(bond.time_to_maturity)
                
                if bond.is_government:
                    government_bonds[maturity_bucket] = (bond, data)
                else:
                    if maturity_bucket not in corporate_bonds:
                        corporate_bonds[maturity_bucket] = []
                    corporate_bonds[maturity_bucket].append((bond, data))
        
        for maturity_bucket in government_bonds:
            if maturity_bucket in corporate_bonds:
                gov_bond, gov_data = government_bonds[maturity_bucket]
                
                for corp_bond, corp_data in corporate_bonds[maturity_bucket]:
                    signal = await self._analyze_credit_spread(gov_bond, gov_data, corp_bond, corp_data)
                    
                    if signal:
                        spread_orders = await self._create_spread_orders(signal, gov_bond, gov_data, corp_bond, corp_data)
                        orders.extend(spread_orders)
        
        return orders
    
    def _get_maturity_bucket(self, time_to_maturity: float) -> str:
        if time_to_maturity <= 3:
            return "short"
        elif time_to_maturity <= 7:
            return "medium"
        else:
            return "long"
    
    async def _analyze_credit_spread(self, gov_bond: FixedIncomeInstrument, gov_data: MarketData,
                                   corp_bond: FixedIncomeInstrument, corp_data: MarketData) -> Optional[Dict]:
        if not self.provider:
            return None
        
        try:
            gov_yield = await self.provider._get_yield_for_bond(gov_bond)
            corp_yield = await self.provider._get_yield_for_bond(corp_bond)
            
            current_spread = corp_yield - gov_yield
            spread_key = f"{corp_bond.credit_rating}_{self._get_maturity_bucket(corp_bond.time_to_maturity)}"
            
            if spread_key not in self.spread_history:
                self.spread_history[spread_key] = []
            
            self.spread_history[spread_key].append((datetime.utcnow(), current_spread))
            
            cutoff_time = datetime.utcnow() - timedelta(days=90)
            self.spread_history[spread_key] = [
                (ts, spread) for ts, spread in self.spread_history[spread_key] if ts > cutoff_time
            ]
            
            if len(self.spread_history[spread_key]) < 20:
                return None
            
            historical_spreads = [spread for _, spread in self.spread_history[spread_key]]
            mean_spread = np.mean(historical_spreads)
            std_spread = np.std(historical_spreads)
            
            z_score = (current_spread - mean_spread) / max(std_spread, 0.001)
            
            if abs(z_score) > 2.0:
                return {
                    'current_spread': current_spread,
                    'mean_spread': mean_spread,
                    'z_score': z_score,
                    'action': 'tighten' if z_score > 2.0 else 'widen',
                    'confidence': min(abs(z_score) / 3.0, 1.0)
                }
        
        except Exception as e:
            print(f"Error analyzing credit spread: {e}")
        
        return None
    
    async def _create_spread_orders(self, signal: Dict, gov_bond: FixedIncomeInstrument, gov_data: MarketData,
                                  corp_bond: FixedIncomeInstrument, corp_data: MarketData) -> List[Order]:
        orders = []
        quantity = int(signal['confidence'] * 5000000)
        
        if signal['action'] == 'tighten':
            gov_order = Order(
                id=f"{self.strategy_id}_gov_{gov_bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=gov_bond,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=gov_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            corp_order = Order(
                id=f"{self.strategy_id}_corp_{corp_bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=corp_bond,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=corp_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            orders.extend([gov_order, corp_order])
        
        elif signal['action'] == 'widen':
            gov_order = Order(
                id=f"{self.strategy_id}_gov_{gov_bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=gov_bond,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=gov_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            corp_order = Order(
                id=f"{self.strategy_id}_corp_{corp_bond.symbol}_{datetime.utcnow().timestamp()}",
                instrument=corp_bond,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                quantity=quantity,
                price=corp_data.mid_price,
                strategy_id=self.strategy_id
            )
            
            orders.extend([gov_order, corp_order])
        
        return orders


class DurationNeutralStrategy(FixedIncomeStrategy):
    def __init__(self, target_duration: float = 5.0, duration_tolerance: float = 0.2):
        super().__init__("duration_neutral", "Duration Neutral Strategy")
        self.target_duration = target_duration
        self.duration_tolerance = duration_tolerance
        self.portfolio_bonds: List[FixedIncomeInstrument] = []
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        if not self.curve_analyzer:
            return []
        
        orders = []
        
        current_bonds = [
            data.instrument for data in market_data.values() 
            if isinstance(data.instrument, FixedIncomeInstrument)
        ]
        
        try:
            duration_metrics = await self.curve_analyzer.calculate_duration_risk(current_bonds)
            current_duration = duration_metrics.get('portfolio_duration', 0)
            
            duration_deviation = current_duration - self.target_duration
            
            if abs(duration_deviation) > self.duration_tolerance:
                rebalancing_orders = await self._create_duration_rebalancing_orders(
                    market_data, duration_deviation
                )
                orders.extend(rebalancing_orders)
        
        except Exception as e:
            print(f"Error in duration neutral strategy: {e}")
        
        return orders
    
    async def _create_duration_rebalancing_orders(self, market_data: Dict[str, MarketData], 
                                                duration_deviation: float) -> List[Order]:
        orders = []
        
        short_duration_bonds = []
        long_duration_bonds = []
        
        for symbol, data in market_data.items():
            if isinstance(data.instrument, FixedIncomeInstrument):
                bond = data.instrument
                
                if bond.time_to_maturity <= 3:
                    short_duration_bonds.append((bond, data))
                elif bond.time_to_maturity >= 8:
                    long_duration_bonds.append((bond, data))
        
        if duration_deviation > self.duration_tolerance:
            for bond, data in short_duration_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_short_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=2000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
            
            for bond, data in long_duration_bonds[:2]:
                order = Order(
                    id=f"{self.strategy_id}_long_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
        
        elif duration_deviation < -self.duration_tolerance:
            for bond, data in long_duration_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_long_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
            
            for bond, data in short_duration_bonds[:2]:
                order = Order(
                    id=f"{self.strategy_id}_short_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=2000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
        
        return orders


class CarryRollDownStrategy(FixedIncomeStrategy):
    def __init__(self, min_carry_threshold: float = 0.01):
        super().__init__("carry_roll_down", "Carry and Roll Down Strategy")
        self.min_carry_threshold = min_carry_threshold
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        if not self.provider:
            return []
        
        orders = []
        
        for symbol, data in market_data.items():
            if isinstance(data.instrument, FixedIncomeInstrument):
                bond = data.instrument
                
                carry_analysis = await self._analyze_carry_and_rolldown(bond)
                
                if carry_analysis and carry_analysis['total_return'] > self.min_carry_threshold:
                    order = await self._create_carry_order(carry_analysis, bond, data)
                    if order:
                        orders.append(order)
        
        return orders
    
    async def _analyze_carry_and_rolldown(self, bond: FixedIncomeInstrument) -> Optional[Dict]:
        if not self.provider:
            return None
        
        try:
            current_yield = await self.provider._get_yield_for_bond(bond)
            current_price = FixedIncomePricer.calculate_bond_price(bond, current_yield)
            
            time_horizon = 0.25  # 3 months
            future_maturity = bond.time_to_maturity - time_horizon
            
            if future_maturity <= 0:
                return None
            
            curve = await self.provider.get_yield_curve(bond.currency)
            future_yield = curve.interpolate_yield(future_maturity)
            
            future_bond = FixedIncomeInstrument(
                symbol=bond.symbol,
                asset_type=bond.asset_type,
                exchange=bond.exchange,
                currency=bond.currency,
                maturity_date=bond.maturity_date,
                coupon_rate=bond.coupon_rate,
                face_value=bond.face_value,
                payment_frequency=bond.payment_frequency,
                credit_rating=bond.credit_rating
            )
            
            future_price = FixedIncomePricer.calculate_bond_price(future_bond, future_yield)
            
            coupon_income = bond.coupon_rate * bond.face_value * time_horizon
            
            price_appreciation = future_price - current_price
            total_return = (price_appreciation + coupon_income) / current_price
            
            return {
                'current_yield': current_yield,
                'future_yield': future_yield,
                'price_appreciation': price_appreciation,
                'coupon_income': coupon_income,
                'total_return': total_return,
                'carry_component': coupon_income / current_price,
                'rolldown_component': price_appreciation / current_price
            }
        
        except Exception as e:
            print(f"Error analyzing carry and rolldown: {e}")
            return None
    
    async def _create_carry_order(self, analysis: Dict, bond: FixedIncomeInstrument, 
                                data: MarketData) -> Optional[Order]:
        total_return = analysis['total_return']
        
        if total_return < self.min_carry_threshold:
            return None
        
        confidence = min(total_return / (self.min_carry_threshold * 2), 1.0)
        quantity = int(confidence * 10000000)
        
        return Order(
            id=f"{self.strategy_id}_{bond.symbol}_{datetime.utcnow().timestamp()}",
            instrument=bond,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=data.mid_price,
            strategy_id=self.strategy_id
        )


class InflationProtectedStrategy(FixedIncomeStrategy):
    def __init__(self, inflation_threshold: float = 0.02):
        super().__init__("inflation_protected", "Inflation Protected Strategy")
        self.inflation_threshold = inflation_threshold
        self.inflation_expectations: List[Tuple[datetime, float]] = []
        
    async def generate_signals(self, market_data: Dict[str, MarketData]) -> List[Order]:
        if not self.provider:
            return []
        
        orders = []
        
        try:
            inflation_signal = await self._analyze_inflation_expectations()
            
            if inflation_signal and abs(inflation_signal['change']) > self.inflation_threshold:
                nominal_bonds = []
                tips_bonds = []
                
                for symbol, data in market_data.items():
                    if isinstance(data.instrument, FixedIncomeInstrument):
                        bond = data.instrument
                        
                        if 'TIPS' in bond.symbol.upper() or 'INFLATION' in bond.symbol.upper():
                            tips_bonds.append((bond, data))
                        elif bond.is_government:
                            nominal_bonds.append((bond, data))
                
                if inflation_signal['direction'] == 'rising':
                    orders.extend(await self._create_inflation_protection_orders(nominal_bonds, tips_bonds, 'rising'))
                else:
                    orders.extend(await self._create_inflation_protection_orders(nominal_bonds, tips_bonds, 'falling'))
        
        except Exception as e:
            print(f"Error in inflation protected strategy: {e}")
        
        return orders
    
    async def _analyze_inflation_expectations(self) -> Optional[Dict]:
        current_breakeven = np.random.uniform(0.02, 0.04)
        
        self.inflation_expectations.append((datetime.utcnow(), current_breakeven))
        
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.inflation_expectations = [
            (ts, rate) for ts, rate in self.inflation_expectations if ts > cutoff_time
        ]
        
        if len(self.inflation_expectations) < 10:
            return None
        
        recent_rates = [rate for _, rate in self.inflation_expectations[-10:]]
        older_rates = [rate for _, rate in self.inflation_expectations[:-10]]
        
        recent_avg = np.mean(recent_rates)
        older_avg = np.mean(older_rates)
        
        change = recent_avg - older_avg
        
        return {
            'current_breakeven': current_breakeven,
            'change': change,
            'direction': 'rising' if change > 0 else 'falling',
            'magnitude': abs(change)
        }
    
    async def _create_inflation_protection_orders(self, nominal_bonds: List, tips_bonds: List, 
                                                direction: str) -> List[Order]:
        orders = []
        
        if direction == 'rising':
            for bond, data in nominal_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_nominal_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
            
            for bond, data in tips_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_tips_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=5000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
        
        else:
            for bond, data in tips_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_tips_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=5000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
            
            for bond, data in nominal_bonds[:3]:
                order = Order(
                    id=f"{self.strategy_id}_nominal_{bond.symbol}_{datetime.utcnow().timestamp()}",
                    instrument=bond,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=5000000,
                    price=data.mid_price,
                    strategy_id=self.strategy_id
                )
                orders.append(order)
        
        return orders