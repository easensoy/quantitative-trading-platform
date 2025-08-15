from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import aiohttp
import numpy as np
import pandas as pd
from enum import Enum
import json
import hashlib
from src.core.models import Instrument
from src.core.event_bus import EventBus
class DataSourceType(Enum):
    NEWS_SENTIMENT = "news_sentiment"
    SOCIAL_SENTIMENT = "social_sentiment"
    ECONOMIC_INDICATOR = "economic_indicator"
    SATELLITE_IMAGERY = "satellite_imagery"
    SUPPLY_CHAIN = "supply_chain"
    ESG_SCORES = "esg_scores"
    INSIDER_TRADING = "insider_trading"
    PATENT_FILINGS = "patent_filings"
@dataclass
class AlternativeDataPoint:
    source_type: DataSourceType
    timestamp: datetime
    symbol: Optional[str]
    value: float
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    @property
    def is_reliable(self) -> bool:
        return self.confidence > 0.7
    @property
    def age_hours(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds() / 3600
@dataclass
class SentimentData:
    symbol: str
    timestamp: datetime
    sentiment_score: float  
    volume: int  
    source_diversity: float  
    keywords: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    @property
    def sentiment_strength(self) -> float:
        return abs(self.sentiment_score) * min(np.log(self.volume + 1) / 5, 1.0)
class AlternativeDataProvider(ABC):
    @abstractmethod
    async def fetch_data(self, symbols: List[str], lookback_hours: int = 24) -> List[AlternativeDataPoint]:
        pass
    @abstractmethod
    async def get_real_time_data(self, symbols: List[str]) -> List[AlternativeDataPoint]:
        pass
class NewsAnalyticsProvider(AlternativeDataProvider):
    def __init__(self, api_key: str = "demo_key"):
        self.api_key = api_key
        self.base_url = "https://api.newsanalytics.com/v1"
        self.session: Optional[aiohttp.ClientSession] = None
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            self.session = aiohttp.ClientSession()
        return self.session
    async def fetch_data(self, symbols: List[str], lookback_hours: int = 24) -> List[AlternativeDataPoint]:
        data_points = []
        for symbol in symbols:
            sentiment_data = await self._fetch_news_sentiment(symbol, lookback_hours)
            for item in sentiment_data:
                data_point = AlternativeDataPoint(
                    source_type=DataSourceType.NEWS_SENTIMENT,
                    timestamp=item['timestamp'],
                    symbol=symbol,
                    value=item['sentiment'],
                    confidence=item['confidence'],
                    metadata={
                        'article_count': item['article_count'],
                        'sources': item['sources'],
                        'keywords': item['keywords']
                    }
                )
                data_points.append(data_point)
        return data_points
    async def get_real_time_data(self, symbols: List[str]) -> List[AlternativeDataPoint]:
        return await self.fetch_data(symbols, lookback_hours=1)
    async def _fetch_news_sentiment(self, symbol: str, lookback_hours: int) -> List[Dict]:
        num_points = max(1, lookback_hours // 4)
        sentiment_data = []
        for i in range(num_points):
            timestamp = datetime.utcnow() - timedelta(hours=i*4)
            base_sentiment = np.random.normal(0, 0.3)
            sentiment = np.tanh(base_sentiment)  
            sentiment_data.append({
                'timestamp': timestamp,
                'sentiment': sentiment,
                'confidence': np.random.uniform(0.6, 0.95),
                'article_count': np.random.poisson(10) + 1,
                'sources': ['Reuters', 'Bloomberg', 'WSJ', 'FT'][:np.random.randint(1, 5)],
                'keywords': [f'keyword_{j}' for j in range(np.random.randint(3, 8))]
            })
        return sentiment_data
class SocialSentimentProvider(AlternativeDataProvider):
    def __init__(self):
        self.platforms = ['twitter', 'reddit', 'stocktwits', 'seeking_alpha']
    async def fetch_data(self, symbols: List[str], lookback_hours: int = 24) -> List[AlternativeDataPoint]:
        data_points = []
        for symbol in symbols:
            social_data = await self._fetch_social_sentiment(symbol, lookback_hours)
            for item in social_data:
                data_point = AlternativeDataPoint(
                    source_type=DataSourceType.SOCIAL_SENTIMENT,
                    timestamp=item['timestamp'],
                    symbol=symbol,
                    value=item['sentiment'],
                    confidence=item['confidence'],
                    metadata={
                        'mention_count': item['mentions'],
                        'platforms': item['platforms'],
                        'viral_score': item.get('viral_score', 0)
                    }
                )
                data_points.append(data_point)
        return data_points
    async def get_real_time_data(self, symbols: List[str]) -> List[AlternativeDataPoint]:
        return await self.fetch_data(symbols, lookback_hours=2)
    async def _fetch_social_sentiment(self, symbol: str, lookback_hours: int) -> List[Dict]:
        num_points = max(1, lookback_hours // 2)
        social_data = []
        for i in range(num_points):
            timestamp = datetime.utcnow() - timedelta(hours=i*2)
            sentiment = np.tanh(np.random.normal(0, 0.5))
            mentions = np.random.poisson(50) + 5
            social_data.append({
                'timestamp': timestamp,
                'sentiment': sentiment,
                'confidence': max(0.3, min(0.8, mentions / 100)),
                'mentions': mentions,
                'platforms': np.random.choice(self.platforms, size=np.random.randint(1, 4), replace=False).tolist(),
                'viral_score': np.random.exponential(0.1)
            })
        return social_data
class EconomicIndicatorProvider(AlternativeDataProvider):
    def __init__(self):
        self.indicators = {
            'gdp_nowcast': 'GDP Growth Nowcast',
            'inflation_expectations': 'Inflation Expectations',
            'employment_trends': 'Employment Trends',
            'consumer_confidence': 'Consumer Confidence',
            'manufacturing_pmi': 'Manufacturing PMI'
        }
    async def fetch_data(self, symbols: List[str], lookback_hours: int = 24) -> List[AlternativeDataPoint]:
        data_points = []
        for indicator, name in self.indicators.items():
            value = await self._get_indicator_value(indicator)
            data_point = AlternativeDataPoint(
                source_type=DataSourceType.ECONOMIC_INDICATOR,
                timestamp=datetime.utcnow(),
                symbol=None,  
                value=value,
                confidence=0.85,
                metadata={
                    'indicator_name': name,
                    'indicator_code': indicator,
                    'frequency': 'daily'
                }
            )
            data_points.append(data_point)
        return data_points
    async def get_real_time_data(self, symbols: List[str]) -> List[AlternativeDataPoint]:
        return await self.fetch_data(symbols, lookback_hours=24)
    async def _get_indicator_value(self, indicator: str) -> float:
        base_values = {
            'gdp_nowcast': 2.5,
            'inflation_expectations': 2.0,
            'employment_trends': 0.3,
            'consumer_confidence': 0.1,
            'manufacturing_pmi': 52.0
        }
        base = base_values.get(indicator, 50.0)
        noise = np.random.normal(0, base * 0.05)
        return base + noise
class SatelliteImageryProvider(AlternativeDataProvider):
    def __init__(self):
        self.commodity_indicators = {
            'oil_storage': 'Crude Oil Storage Levels',
            'crop_health': 'Agricultural Crop Health Index',
            'mining_activity': 'Mining Activity Index',
            'shipping_traffic': 'Port Shipping Traffic'
        }
    async def fetch_data(self, symbols: List[str], lookback_hours: int = 24) -> List[AlternativeDataPoint]:
        data_points = []
        commodity_symbols = [s for s in symbols if self._is_commodity(s)]
        for symbol in commodity_symbols:
            indicators = await self._get_satellite_indicators(symbol)
            for indicator in indicators:
                data_point = AlternativeDataPoint(
                    source_type=DataSourceType.SATELLITE_IMAGERY,
                    timestamp=datetime.utcnow() - timedelta(hours=np.random.randint(1, 12)),
                    symbol=symbol,
                    value=indicator['value'],
                    confidence=indicator['confidence'],
                    metadata={
                        'indicator_type': indicator['type'],
                        'resolution': '10m',
                        'satellite_provider': 'Sentinel-2',
                        'weather_adjusted': True
                    }
                )
                data_points.append(data_point)
        return data_points
    async def get_real_time_data(self, symbols: List[str]) -> List[AlternativeDataPoint]:
        return await self.fetch_data(symbols, lookback_hours=24)
    def _is_commodity(self, symbol: str) -> bool:
        commodity_symbols = ['CL', 'NG', 'GC', 'SI', 'C', 'W', 'S', 'HG']
        return symbol.upper() in commodity_symbols
    async def _get_satellite_indicators(self, symbol: str) -> List[Dict]:
        indicators = []
        if symbol.upper() in ['CL', 'NG']:  
            indicators.append({
                'type': 'oil_storage',
                'value': np.random.normal(0.5, 0.2),
                'confidence': 0.8
            })
        elif symbol.upper() in ['C', 'W', 'S']:  
            indicators.append({
                'type': 'crop_health',
                'value': np.random.normal(0.3, 0.15),
                'confidence': 0.75
            })
        elif symbol.upper() in ['GC', 'SI', 'HG']:  
            indicators.append({
                'type': 'mining_activity',
                'value': np.random.normal(0.1, 0.1),
                'confidence': 0.7
            })
        return indicators
class AlternativeDataAggregator:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.providers: Dict[DataSourceType, AlternativeDataProvider] = {}
        self.data_cache: Dict[str, List[AlternativeDataPoint]] = {}
        self.last_update: Dict[DataSourceType, datetime] = {}
    def add_provider(self, provider: AlternativeDataProvider, source_types: List[DataSourceType]):
        for source_type in source_types:
            self.providers[source_type] = provider
    async def initialize(self):
        news_provider = NewsAnalyticsProvider()
        social_provider = SocialSentimentProvider()
        economic_provider = EconomicIndicatorProvider()
        satellite_provider = SatelliteImageryProvider()
        self.add_provider(news_provider, [DataSourceType.NEWS_SENTIMENT])
        self.add_provider(social_provider, [DataSourceType.SOCIAL_SENTIMENT])
        self.add_provider(economic_provider, [DataSourceType.ECONOMIC_INDICATOR])
        self.add_provider(satellite_provider, [DataSourceType.SATELLITE_IMAGERY])
        await self.event_bus.subscribe("market_data", self._handle_market_data_update)
    async def _handle_market_data_update(self, data: Dict):
        symbol = data["symbol"]
        await self._update_alternative_data([symbol])
    async def fetch_all_data(self, symbols: List[str], lookback_hours: int = 24) -> Dict[DataSourceType, List[AlternativeDataPoint]]:
        all_data = {}
        tasks = []
        for source_type, provider in self.providers.items():
            task = asyncio.create_task(provider.fetch_data(symbols, lookback_hours))
            tasks.append((source_type, task))
        for source_type, task in tasks:
            try:
                data = await task
                all_data[source_type] = data
                self.last_update[source_type] = datetime.utcnow()
            except Exception as e:
                print(f"Failed to fetch {source_type} data: {e}")
                all_data[source_type] = []
        return all_data
    async def get_combined_sentiment(self, symbol: str) -> Optional[SentimentData]:
        news_data = []
        social_data = []
        if DataSourceType.NEWS_SENTIMENT in self.providers:
            news_points = await self.providers[DataSourceType.NEWS_SENTIMENT].get_real_time_data([symbol])
            news_data = [dp for dp in news_points if dp.symbol == symbol]
        if DataSourceType.SOCIAL_SENTIMENT in self.providers:
            social_points = await self.providers[DataSourceType.SOCIAL_SENTIMENT].get_real_time_data([symbol])
            social_data = [dp for dp in social_points if dp.symbol == symbol]
        if not news_data and not social_data:
            return None
        all_sentiments = []
        all_volumes = []
        all_confidences = []
        for dp in news_data + social_data:
            all_sentiments.append(dp.value)
            all_volumes.append(dp.metadata.get('article_count', dp.metadata.get('mention_count', 1)))
            all_confidences.append(dp.confidence)
        weights = []
        for i, dp in enumerate(news_data + social_data):
            age_weight = max(0.1, 1.0 - dp.age_hours / 24.0)  
            conf_weight = all_confidences[i]
            weights.append(age_weight * conf_weight)
        if sum(weights) == 0:
            return None
        weighted_sentiment = np.average(all_sentiments, weights=weights)
        total_volume = sum(all_volumes)
        avg_confidence = np.mean(all_confidences)
        return SentimentData(
            symbol=symbol,
            timestamp=datetime.utcnow(),
            sentiment_score=weighted_sentiment,
            volume=total_volume,
            source_diversity=len(set([dp.source_type for dp in news_data + social_data])),
            keywords=[],  
            entities=[]   
        )
    async def _update_alternative_data(self, symbols: List[str]):
        now = datetime.utcnow()
        for source_type, provider in self.providers.items():
            last_update = self.last_update.get(source_type)
            if last_update is None or (now - last_update).total_seconds() > 900:  
                try:
                    data = await provider.get_real_time_data(symbols)
                    for dp in data:
                        await self.event_bus.publish("alternative_data", {
                            "source_type": dp.source_type.value,
                            "data_point": dp
                        })
                    self.last_update[source_type] = now
                except Exception as e:
                    print(f"Failed to update {source_type} data: {e}")
    def get_data_freshness(self) -> Dict[str, float]:
        freshness = {}
        now = datetime.utcnow()
        for source_type, last_update in self.last_update.items():
            if last_update:
                age_hours = (now - last_update).total_seconds() / 3600
                freshness[source_type.value] = age_hours
            else:
                freshness[source_type.value] = float('inf')
        return freshness
    def get_provider_status(self) -> Dict[str, Dict[str, Any]]:
        status = {}
        for source_type, provider in self.providers.items():
            status[source_type.value] = {
                'provider_type': type(provider).__name__,
                'last_update': self.last_update.get(source_type),
                'is_active': source_type in self.last_update
            }
        return status