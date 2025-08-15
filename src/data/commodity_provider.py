from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import numpy as np

from src.core.models import (
    Instrument, MarketData, MarketDataProvider, CommodityInstrument, 
    CommodityFuturesPrice
)


class CommodityDataProvider(MarketDataProvider):
    def __init__(self):
        self.subscribed_instruments: List[CommodityInstrument] = []
        self.current_prices: Dict[str, MarketData] = {}
        
    async def get_market_data(self, instrument: Instrument) -> MarketData:
        if not isinstance(instrument, CommodityInstrument):
            raise ValueError("Instrument must be CommodityInstrument type")
            
        return await self._fetch_commodity_data(instrument)
    
    async def subscribe_market_data(self, instruments: List[Instrument]) -> None:
        commodity_instruments = [inst for inst in instruments if isinstance(inst, CommodityInstrument)]
        self.subscribed_instruments.extend(commodity_instruments)
    
    async def _fetch_commodity_data(self, instrument: CommodityInstrument) -> MarketData:
        price_data = await self._get_commodity_price(instrument)
        
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
    
    async def _get_commodity_price(self, instrument: CommodityInstrument) -> Dict:
        base_price = self._get_base_price(instrument.symbol)
        volatility = self._get_volatility(instrument.symbol)
        
        spread = base_price * 0.002
        
        bid = base_price - spread / 2
        ask = base_price + spread / 2
        volume = np.random.randint(1000, 10000)
        
        return {
            'bid': round(bid, instrument.tick_size),
            'ask': round(ask, instrument.tick_size),
            'last': round(base_price, instrument.tick_size),
            'volume': volume,
            'bid_size': np.random.randint(10, 100),
            'ask_size': np.random.randint(10, 100)
        }
    
    def _get_base_price(self, symbol: str) -> float:
        commodity_prices = {
            'CL': 75.0,    # Crude Oil
            'NG': 3.5,     # Natural Gas
            'GC': 2000.0,  # Gold
            'SI': 25.0,    # Silver
            'HG': 4.0,     # Copper
            'C': 500.0,    # Corn
            'W': 600.0,    # Wheat
            'S': 1400.0,   # Soybeans
        }
        
        base = commodity_prices.get(symbol.upper(), 100.0)
        noise = np.random.normal(0, base * 0.01)
        return max(base + noise, base * 0.8)
    
    def _get_volatility(self, symbol: str) -> float:
        volatilities = {
            'CL': 0.30,    # Oil is volatile
            'NG': 0.45,    # Natural gas very volatile
            'GC': 0.20,    # Gold moderate volatility
            'SI': 0.25,    # Silver higher than gold
            'HG': 0.22,    # Copper industrial metal
            'C': 0.18,     # Agricultural commodities
            'W': 0.20,
            'S': 0.16,
        }
        return volatilities.get(symbol.upper(), 0.20)


class EnergyDataProvider(CommodityDataProvider):
    def __init__(self):
        super().__init__()
        self.energy_symbols = ['CL', 'NG', 'HO', 'RB', 'BZ']
    
    async def get_crack_spreads(self, crude_symbol: str = 'CL') -> Dict[str, float]:
        crude_price = self._get_base_price(crude_symbol)
        heating_oil_price = self._get_base_price('HO')
        gasoline_price = self._get_base_price('RB')
        
        return {
            'heating_oil_crack': heating_oil_price - crude_price,
            'gasoline_crack': gasoline_price - crude_price,
            '3_2_1_crack': (2 * gasoline_price + heating_oil_price) / 3 - crude_price
        }
    
    async def get_storage_levels(self, symbol: str) -> Dict[str, float]:
        return {
            'current_level': np.random.uniform(300, 500),
            'capacity': 500,
            'utilization_rate': np.random.uniform(0.6, 0.9),
            'seasonal_avg': np.random.uniform(350, 450)
        }


class MetalsDataProvider(CommodityDataProvider):
    def __init__(self):
        super().__init__()
        self.metals_symbols = ['GC', 'SI', 'HG', 'PL', 'PA']
    
    async def get_gold_silver_ratio(self) -> float:
        gold_price = self._get_base_price('GC')
        silver_price = self._get_base_price('SI')
        return gold_price / silver_price
    
    async def get_lme_inventory(self, symbol: str) -> Dict[str, float]:
        return {
            'warehouse_stocks': np.random.uniform(100000, 500000),
            'cancelled_warrants': np.random.uniform(5000, 25000),
            'daily_change': np.random.uniform(-5000, 5000)
        }


class AgricultureDataProvider(CommodityDataProvider):
    def __init__(self):
        super().__init__()
        self.ag_symbols = ['C', 'W', 'S', 'SM', 'BO', 'CC', 'KC', 'SB', 'CT']
    
    async def get_seasonal_factors(self, symbol: str) -> Dict[str, float]:
        month = datetime.now().month
        
        seasonal_patterns = {
            'C': [0.95, 0.97, 1.02, 1.05, 1.08, 1.10, 1.05, 0.98, 0.95, 0.92, 0.95, 0.98],
            'W': [1.00, 1.02, 1.05, 1.08, 1.10, 1.08, 1.05, 0.98, 0.95, 0.95, 0.98, 1.00],
            'S': [0.98, 1.00, 1.03, 1.06, 1.08, 1.10, 1.08, 1.05, 1.00, 0.95, 0.95, 0.98]
        }
        
        pattern = seasonal_patterns.get(symbol.upper(), [1.0] * 12)
        
        return {
            'current_factor': pattern[month - 1],
            'peak_month': pattern.index(max(pattern)) + 1,
            'trough_month': pattern.index(min(pattern)) + 1,
            'volatility': np.std(pattern)
        }
    
    async def get_weather_data(self, region: str) -> Dict[str, float]:
        return {
            'temperature_deviation': np.random.uniform(-5, 5),
            'precipitation_ratio': np.random.uniform(0.5, 1.5),
            'drought_index': np.random.uniform(0, 4),
            'growing_degree_days': np.random.uniform(1000, 2500)
        }


class CommodityCurveBuilder:
    def __init__(self, provider: CommodityDataProvider):
        self.provider = provider
    
    async def build_futures_curve(self, base_instrument: CommodityInstrument, 
                                 months_out: int = 12) -> List[CommodityFuturesPrice]:
        spot_price = self.provider._get_base_price(base_instrument.symbol)
        risk_free_rate = 0.05
        
        curve = []
        for i in range(1, months_out + 1):
            delivery_date = datetime.utcnow() + timedelta(days=30 * i)
            time_to_maturity = i / 12.0
            
            storage_cost = self._estimate_storage_cost(base_instrument, time_to_maturity)
            convenience_yield = self._estimate_convenience_yield(base_instrument, time_to_maturity)
            
            futures_price_obj = CommodityFuturesPrice(
                spot_price=spot_price,
                futures_price=spot_price * np.exp((risk_free_rate + storage_cost - convenience_yield) * time_to_maturity),
                time_to_maturity=time_to_maturity,
                risk_free_rate=risk_free_rate,
                storage_cost=storage_cost,
                convenience_yield=convenience_yield
            )
            
            curve.append(futures_price_obj)
        
        return curve
    
    def _estimate_storage_cost(self, instrument: CommodityInstrument, time_to_maturity: float) -> float:
        if instrument.is_energy:
            return 0.02 * time_to_maturity
        elif instrument.is_metals:
            return 0.01 * time_to_maturity
        else:
            return 0.03 * time_to_maturity
    
    def _estimate_convenience_yield(self, instrument: CommodityInstrument, time_to_maturity: float) -> float:
        base_convenience = {
            'CL': 0.03,
            'NG': 0.05,
            'GC': 0.005,
            'SI': 0.01,
            'C': 0.02,
            'W': 0.025
        }
        
        base = base_convenience.get(instrument.symbol.upper(), 0.02)
        return base * np.exp(-time_to_maturity)