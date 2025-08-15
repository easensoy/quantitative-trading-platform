from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import asyncio
import numpy as np
from scipy.interpolate import CubicSpline

from src.core.models import (
    Instrument, MarketData, MarketDataProvider, FixedIncomeInstrument, 
    YieldCurve, YieldCurvePoint, FixedIncomePricer
)


class FixedIncomeDataProvider(MarketDataProvider):
    def __init__(self):
        self.subscribed_instruments: List[FixedIncomeInstrument] = []
        self.yield_curves: Dict[str, YieldCurve] = {}
        self.credit_spreads: Dict[str, Dict[str, float]] = {}
        
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        if not isinstance(instrument, FixedIncomeInstrument):
            raise ValueError("Instrument must be FixedIncomeInstrument type")
            
        return await self._fetch_bond_data(instrument)
    
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        fi_instruments = [inst for inst in instruments if isinstance(inst, FixedIncomeInstrument)]
        self.subscribed_instruments.extend(fi_instruments)
    
    async def _fetch_bond_data(self, instrument: FixedIncomeInstrument) -> MarketData:
        price_data = await self._calculate_bond_price(instrument)
        
        return MarketData(
            instrument=instrument,
            timestamp=datetime.utcnow(),
            bid=price_data.get('bid'),
            ask=price_data.get('ask'),
            last=price_data.get('last'),
            volume=price_data.get('volume'),
            bid_size=price_data.get('bid_size'),
            ask_size=price_data.get('ask_size')
        )
    
    async def _calculate_bond_price(self, instrument: FixedIncomeInstrument) -> Dict:
        yield_rate = await self._get_yield_for_bond(instrument)
        
        theoretical_price = FixedIncomePricer.calculate_bond_price(instrument, yield_rate)
        
        bid_ask_spread = 0.05
        bid_price = theoretical_price - bid_ask_spread / 2
        ask_price = theoretical_price + bid_ask_spread / 2
        
        return {
            'bid': round(bid_price, 4),
            'ask': round(ask_price, 4),
            'last': round(theoretical_price, 4),
            'volume': np.random.randint(1000000, 50000000),
            'bid_size': np.random.randint(1000000, 10000000),
            'ask_size': np.random.randint(1000000, 10000000)
        }
    
    async def _get_yield_for_bond(self, instrument: FixedIncomeInstrument) -> float:
        curve = await self._get_yield_curve(instrument.currency)
        base_yield = curve.interpolate_yield(instrument.time_to_maturity)
        
        if not instrument.is_government:
            credit_spread = await self._get_credit_spread(instrument.credit_rating, instrument.time_to_maturity)
            base_yield += credit_spread
        
        return base_yield
    
    async def _get_yield_curve(self, currency: str = "USD") -> YieldCurve:
        if currency in self.yield_curves:
            curve = self.yield_curves[currency]
            if (datetime.utcnow() - curve.timestamp).seconds < 300:
                return curve
        
        curve = await self._build_yield_curve(currency)
        self.yield_curves[currency] = curve
        return curve
    
    async def _build_yield_curve(self, currency: str) -> YieldCurve:
        treasury_rates = await self._fetch_treasury_rates(currency)
        
        points = [
            YieldCurvePoint(maturity=maturity, yield_rate=rate)
            for maturity, rate in treasury_rates.items()
        ]
        
        return YieldCurve(points, currency)
    
    async def _fetch_treasury_rates(self, currency: str) -> Dict[float, float]:
        base_rates = {
            "USD": {
                0.25: 0.025,   # 3M
                0.5: 0.028,    # 6M
                1.0: 0.035,    # 1Y
                2.0: 0.042,    # 2Y
                3.0: 0.048,    # 3Y
                5.0: 0.055,    # 5Y
                7.0: 0.058,    # 7Y
                10.0: 0.060,   # 10Y
                20.0: 0.065,   # 20Y
                30.0: 0.068    # 30Y
            },
            "EUR": {
                0.25: -0.005,
                0.5: -0.002,
                1.0: 0.005,
                2.0: 0.015,
                3.0: 0.025,
                5.0: 0.035,
                7.0: 0.040,
                10.0: 0.045,
                20.0: 0.050,
                30.0: 0.052
            }
        }
        
        rates = base_rates.get(currency, base_rates["USD"])
        
        noisy_rates = {}
        for maturity, rate in rates.items():
            noise = np.random.normal(0, 0.002)
            noisy_rates[maturity] = max(rate + noise, -0.01)
        
        return noisy_rates
    
    async def _get_credit_spread(self, rating: Optional[str], maturity: float) -> float:
        if not rating:
            return 0.001
        
        base_spreads = {
            'AAA': 0.0005,
            'AA+': 0.001,
            'AA': 0.0015,
            'AA-': 0.002,
            'A+': 0.0025,
            'A': 0.003,
            'A-': 0.004,
            'BBB+': 0.006,
            'BBB': 0.008,
            'BBB-': 0.012,
            'BB+': 0.020,
            'BB': 0.030,
            'BB-': 0.045,
            'B+': 0.060,
            'B': 0.080,
            'B-': 0.120,
            'CCC': 0.200
        }
        
        base_spread = base_spreads.get(rating, 0.050)
        
        maturity_adjustment = 1 + 0.1 * np.log(1 + maturity)
        
        return base_spread * maturity_adjustment
    
    async def get_yield_curve(self, currency: str = "USD") -> YieldCurve:
        return await self._get_yield_curve(currency)
    
    async def get_credit_spreads(self, rating: str) -> Dict[float, float]:
        maturities = [1, 2, 3, 5, 7, 10, 20, 30]
        spreads = {}
        
        for maturity in maturities:
            spreads[maturity] = await self._get_credit_spread(rating, maturity)
        
        return spreads


class GovernmentBondProvider(FixedIncomeDataProvider):
    def __init__(self, country: str = "US"):
        super().__init__()
        self.country = country
        
    async def get_treasury_auction_data(self) -> Dict:
        return {
            'next_auction_date': datetime.utcnow() + timedelta(days=7),
            'securities_offered': ['2Y', '5Y', '10Y'],
            'bid_to_cover_ratio': np.random.uniform(2.0, 3.5),
            'high_yield': np.random.uniform(0.04, 0.07),
            'allocation_percentage': np.random.uniform(0.3, 0.8)
        }
    
    async def get_tips_breakeven_inflation(self, maturity: float) -> float:
        nominal_yield = (await self._get_yield_curve('USD')).interpolate_yield(maturity)
        real_yield = nominal_yield - 0.02
        return nominal_yield - real_yield


class CorporateBondProvider(FixedIncomeDataProvider):
    def __init__(self):
        super().__init__()
        
    async def get_sector_spreads(self) -> Dict[str, Dict[str, float]]:
        sectors = ['Technology', 'Healthcare', 'Energy', 'Financials', 'Utilities']
        ratings = ['AAA', 'AA', 'A', 'BBB', 'BB']
        
        sector_spreads = {}
        for sector in sectors:
            sector_spreads[sector] = {}
            for rating in ratings:
                base_spread = await self._get_credit_spread(rating, 5.0)
                sector_adjustment = np.random.uniform(0.8, 1.3)
                sector_spreads[sector][rating] = base_spread * sector_adjustment
        
        return sector_spreads
    
    async def get_bond_liquidity_metrics(self, instrument: FixedIncomeInstrument) -> Dict[str, float]:
        return {
            'bid_ask_spread_bps': np.random.uniform(2, 50),
            'trade_frequency': np.random.uniform(0.1, 10.0),
            'average_trade_size': np.random.uniform(1000000, 50000000),
            'market_depth': np.random.uniform(0.5, 5.0)
        }


class YieldCurveAnalyzer:
    def __init__(self, provider: FixedIncomeDataProvider):
        self.provider = provider
    
    async def calculate_curve_metrics(self, currency: str = "USD") -> Dict[str, float]:
        curve = await self.provider.get_yield_curve(currency)
        
        yields = [point.yield_rate for point in curve.points]
        maturities = [point.maturity for point in curve.points]
        
        return {
            'curve_steepness': yields[-1] - yields[0],
            'curve_level': np.mean(yields),
            'curve_curvature': self._calculate_curvature(maturities, yields),
            'ten_two_spread': curve.interpolate_yield(10) - curve.interpolate_yield(2),
            'five_year_five_year_forward': curve.get_forward_rate(5, 10)
        }
    
    def _calculate_curvature(self, maturities: List[float], yields: List[float]) -> float:
        if len(maturities) < 3:
            return 0.0
        
        short_term = yields[0]
        medium_term = np.interp(5.0, maturities, yields)
        long_term = yields[-1]
        
        return 2 * medium_term - short_term - long_term
    
    async def detect_curve_inversions(self, currency: str = "USD") -> List[Tuple[float, float]]:
        curve = await self.provider.get_yield_curve(currency)
        inversions = []
        
        for i in range(len(curve.points) - 1):
            current = curve.points[i]
            next_point = curve.points[i + 1]
            
            if current.yield_rate > next_point.yield_rate:
                inversions.append((current.maturity, next_point.maturity))
        
        return inversions
    
    async def calculate_duration_risk(self, portfolio_bonds: List[FixedIncomeInstrument]) -> Dict[str, float]:
        total_duration = 0.0
        total_value = 0.0
        convexity = 0.0
        
        for bond in portfolio_bonds:
            yield_rate = await self.provider._get_yield_for_bond(bond)
            bond_price = FixedIncomePricer.calculate_bond_price(bond, yield_rate)
            bond_duration = FixedIncomePricer.calculate_duration(bond, yield_rate)
            bond_convexity = FixedIncomePricer.calculate_convexity(bond, yield_rate)
            
            bond_value = bond_price * 1000000
            
            total_duration += bond_duration * bond_value
            total_value += bond_value
            convexity += bond_convexity * bond_value
        
        if total_value == 0:
            return {'portfolio_duration': 0, 'portfolio_convexity': 0, 'dv01': 0}
        
        portfolio_duration = total_duration / total_value
        portfolio_convexity = convexity / total_value
        dv01 = portfolio_duration * total_value / 10000
        
        return {
            'portfolio_duration': portfolio_duration,
            'portfolio_convexity': portfolio_convexity,
            'dv01': dv01,
            'total_value': total_value
        }