from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import asyncio
import aiohttp
import pandas as pd
import numpy as np
import requests
from dataclasses import dataclass

from src.core.models import Instrument, MarketData, AssetType
from src.core.exceptions import MarketDataError


@dataclass
class DataSource:
    name: str
    url: str
    api_key: str
    rate_limit: int
    timeout: int = 30


class DataExtractor(ABC):
    @abstractmethod
    async def extract(self, symbols: List[str], **kwargs) -> Dict[str, Any]:
        pass


class MarketDataExtractor(DataExtractor):
    def __init__(self):
        self.sources = {
            'alpha_vantage': DataSource(
                name='alpha_vantage',
                url='https://www.alphavantage.co/query',
                api_key='demo',
                rate_limit=5
            ),
            'yahoo_finance': DataSource(
                name='yahoo_finance',
                url='https://query1.finance.yahoo.com/v8/finance/chart',
                api_key='',
                rate_limit=100
            ),
            'polygon': DataSource(
                name='polygon',
                url='https://api.polygon.io/v2',
                api_key='demo',
                rate_limit=1000
            )
        }
        self.session = None

    async def extract(self, symbols: List[str], **kwargs) -> Dict[str, Any]:
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        tasks = []
        for symbol in symbols:
            task = asyncio.create_task(self.extract_realtime_data(symbol))
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"Failed to extract data for {symbols[i]}: {result}")
            else:
                data[symbols[i]] = result
        
        return data

    async def extract_realtime_data(self, symbol: str) -> List[Dict]:
        try:
            return await self._extract_from_yahoo_finance(symbol)
        except Exception as e:
            print(f"Yahoo Finance failed for {symbol}: {e}")
            try:
                return await self._extract_from_alpha_vantage(symbol)
            except Exception as e2:
                print(f"Alpha Vantage failed for {symbol}: {e2}")
                return self._generate_mock_data(symbol)

    async def _extract_from_yahoo_finance(self, symbol: str) -> List[Dict]:
        source = self.sources['yahoo_finance']
        url = f"{source.url}/{symbol}"
        
        params = {
            'interval': '1d',
            'range': '5d',
            'includePrePost': 'false'
        }
        
        async with self.session.get(url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Yahoo Finance API error: {response.status}")
            
            data = await response.json()
            
            if 'chart' not in data or 'error' in data['chart']:
                raise MarketDataError("Invalid response from Yahoo Finance")
            
            chart_data = data['chart']['result'][0]
            timestamps = chart_data['timestamp']
            quotes = chart_data['indicators']['quote'][0]
            
            market_data = []
            for i, timestamp in enumerate(timestamps):
                if all(quotes[field][i] is not None for field in ['open', 'high', 'low', 'close']):
                    market_data.append({
                        'timestamp': datetime.fromtimestamp(timestamp),
                        'symbol': symbol,
                        'open': quotes['open'][i],
                        'high': quotes['high'][i],
                        'low': quotes['low'][i],
                        'close': quotes['close'][i],
                        'volume': quotes['volume'][i] or 0,
                        'source': 'yahoo_finance'
                    })
            
            return market_data

    async def _extract_from_alpha_vantage(self, symbol: str) -> List[Dict]:
        source = self.sources['alpha_vantage']
        
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': symbol,
            'apikey': source.api_key,
            'outputsize': 'compact'
        }
        
        async with self.session.get(source.url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Alpha Vantage API error: {response.status}")
            
            data = await response.json()
            
            if 'Error Message' in data:
                raise MarketDataError(f"Alpha Vantage error: {data['Error Message']}")
            
            if 'Time Series (Daily)' not in data:
                raise MarketDataError("Invalid response from Alpha Vantage")
            
            time_series = data['Time Series (Daily)']
            
            market_data = []
            for date_str, values in time_series.items():
                market_data.append({
                    'timestamp': datetime.strptime(date_str, '%Y-%m-%d'),
                    'symbol': symbol,
                    'open': float(values['1. open']),
                    'high': float(values['2. high']),
                    'low': float(values['3. low']),
                    'close': float(values['4. close']),
                    'volume': int(values['5. volume']),
                    'source': 'alpha_vantage'
                })
            
            return sorted(market_data, key=lambda x: x['timestamp'])

    def _generate_mock_data(self, symbol: str) -> List[Dict]:
        """Generate mock data for testing purposes"""
        base_price = 100 + hash(symbol) % 100
        
        data = []
        for i in range(5):
            date = datetime.now() - timedelta(days=4-i)
            
            open_price = base_price + np.random.normal(0, 2)
            close_price = open_price + np.random.normal(0, 1)
            high_price = max(open_price, close_price) + abs(np.random.normal(0, 0.5))
            low_price = min(open_price, close_price) - abs(np.random.normal(0, 0.5))
            volume = int(np.random.lognormal(10, 1))
            
            data.append({
                'timestamp': date,
                'symbol': symbol,
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume,
                'source': 'mock'
            })
            
            base_price = close_price
        
        return data

    async def extract_intraday_data(self, symbol: str, interval: str = '5min') -> List[Dict]:
        try:
            return await self._extract_intraday_yahoo(symbol, interval)
        except Exception as e:
            print(f"Intraday extraction failed for {symbol}: {e}")
            return self._generate_mock_intraday_data(symbol, interval)

    async def _extract_intraday_yahoo(self, symbol: str, interval: str) -> List[Dict]:
        source = self.sources['yahoo_finance']
        url = f"{source.url}/{symbol}"
        
        params = {
            'interval': interval,
            'range': '1d',
            'includePrePost': 'false'
        }
        
        async with self.session.get(url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Yahoo Finance API error: {response.status}")
            
            data = await response.json()
            chart_data = data['chart']['result'][0]
            timestamps = chart_data['timestamp']
            quotes = chart_data['indicators']['quote'][0]
            
            market_data = []
            for i, timestamp in enumerate(timestamps):
                if all(quotes[field][i] is not None for field in ['open', 'high', 'low', 'close']):
                    market_data.append({
                        'timestamp': datetime.fromtimestamp(timestamp),
                        'symbol': symbol,
                        'open': quotes['open'][i],
                        'high': quotes['high'][i],
                        'low': quotes['low'][i],
                        'close': quotes['close'][i],
                        'volume': quotes['volume'][i] or 0,
                        'source': 'yahoo_finance'
                    })
            
            return market_data

    def _generate_mock_intraday_data(self, symbol: str, interval: str) -> List[Dict]:
        interval_minutes = {'1min': 1, '5min': 5, '15min': 15, '30min': 30, '1h': 60}
        minutes = interval_minutes.get(interval, 5)
        
        base_price = 100 + hash(symbol) % 100
        current_time = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
        
        data = []
        for i in range(78):  # 6.5 hours of trading * 60 / interval
            timestamp = current_time + timedelta(minutes=i * minutes)
            
            open_price = base_price + np.random.normal(0, 0.5)
            close_price = open_price + np.random.normal(0, 0.3)
            high_price = max(open_price, close_price) + abs(np.random.normal(0, 0.2))
            low_price = min(open_price, close_price) - abs(np.random.normal(0, 0.2))
            volume = int(np.random.lognormal(8, 1))
            
            data.append({
                'timestamp': timestamp,
                'symbol': symbol,
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume,
                'source': 'mock'
            })
            
            base_price = close_price
        
        return data

    async def close(self):
        if self.session:
            await self.session.close()


class FundamentalDataExtractor(DataExtractor):
    def __init__(self):
        self.sources = {
            'alpha_vantage': DataSource(
                name='alpha_vantage',
                url='https://www.alphavantage.co/query',
                api_key='demo',
                rate_limit=5
            ),
            'financial_modeling_prep': DataSource(
                name='financial_modeling_prep',
                url='https://financialmodelingprep.com/api/v3',
                api_key='demo',
                rate_limit=250
            )
        }
        self.session = None

    async def extract(self, symbols: List[str], **kwargs) -> Dict[str, Any]:
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        data = {}
        for symbol in symbols:
            try:
                data[symbol] = await self.extract_financial_statements(symbol)
            except Exception as e:
                print(f"Failed to extract fundamental data for {symbol}: {e}")
                data[symbol] = self._generate_mock_fundamental_data(symbol)
        
        return data

    async def extract_financial_statements(self, symbol: str) -> Dict[str, Any]:
        try:
            return await self._extract_from_alpha_vantage(symbol)
        except Exception as e:
            print(f"Alpha Vantage fundamental data failed for {symbol}: {e}")
            return self._generate_mock_fundamental_data(symbol)

    async def _extract_from_alpha_vantage(self, symbol: str) -> Dict[str, Any]:
        source = self.sources['alpha_vantage']
        
        income_statement = await self._get_income_statement(symbol, source)
        balance_sheet = await self._get_balance_sheet(symbol, source)
        cash_flow = await self._get_cash_flow(symbol, source)
        
        return {
            'income_statement': income_statement,
            'balance_sheet': balance_sheet,
            'cash_flow': cash_flow,
            'source': 'alpha_vantage'
        }

    async def _get_income_statement(self, symbol: str, source: DataSource) -> Dict:
        params = {
            'function': 'INCOME_STATEMENT',
            'symbol': symbol,
            'apikey': source.api_key
        }
        
        async with self.session.get(source.url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Alpha Vantage API error: {response.status}")
            
            data = await response.json()
            
            if 'Error Message' in data:
                raise MarketDataError(f"Alpha Vantage error: {data['Error Message']}")
            
            return data.get('annualReports', [])

    async def _get_balance_sheet(self, symbol: str, source: DataSource) -> Dict:
        params = {
            'function': 'BALANCE_SHEET',
            'symbol': symbol,
            'apikey': source.api_key
        }
        
        async with self.session.get(source.url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Alpha Vantage API error: {response.status}")
            
            data = await response.json()
            return data.get('annualReports', [])

    async def _get_cash_flow(self, symbol: str, source: DataSource) -> Dict:
        params = {
            'function': 'CASH_FLOW',
            'symbol': symbol,
            'apikey': source.api_key
        }
        
        async with self.session.get(source.url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Alpha Vantage API error: {response.status}")
            
            data = await response.json()
            return data.get('annualReports', [])

    def _generate_mock_fundamental_data(self, symbol: str) -> Dict[str, Any]:
        base_revenue = 1000000000 + (hash(symbol) % 10000000000)
        
        return {
            'income_statement': [{
                'fiscalDateEnding': '2023-12-31',
                'totalRevenue': str(base_revenue),
                'grossProfit': str(int(base_revenue * 0.3)),
                'operatingIncome': str(int(base_revenue * 0.15)),
                'netIncome': str(int(base_revenue * 0.1)),
                'ebitda': str(int(base_revenue * 0.2))
            }],
            'balance_sheet': [{
                'fiscalDateEnding': '2023-12-31',
                'totalAssets': str(int(base_revenue * 2)),
                'totalLiabilities': str(int(base_revenue * 0.8)),
                'totalShareholderEquity': str(int(base_revenue * 1.2)),
                'cash': str(int(base_revenue * 0.3))
            }],
            'cash_flow': [{
                'fiscalDateEnding': '2023-12-31',
                'operatingCashflow': str(int(base_revenue * 0.12)),
                'capitalExpenditures': str(int(base_revenue * 0.05)),
                'freeCashFlow': str(int(base_revenue * 0.07))
            }],
            'source': 'mock'
        }

    async def close(self):
        if self.session:
            await self.session.close()


class NewsDataExtractor(DataExtractor):
    def __init__(self):
        self.sources = {
            'alpha_vantage': DataSource(
                name='alpha_vantage',
                url='https://www.alphavantage.co/query',
                api_key='demo',
                rate_limit=5
            ),
            'newsapi': DataSource(
                name='newsapi',
                url='https://newsapi.org/v2',
                api_key='demo',
                rate_limit=1000
            )
        }
        self.session = None

    async def extract(self, symbols: List[str], **kwargs) -> Dict[str, Any]:
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        data = {}
        for symbol in symbols:
            try:
                data[symbol] = await self.extract_news(symbol)
            except Exception as e:
                print(f"Failed to extract news for {symbol}: {e}")
                data[symbol] = []
        
        return data

    async def extract_news(self, symbol: str, limit: int = 50) -> List[Dict]:
        try:
            return await self._extract_from_alpha_vantage_news(symbol, limit)
        except Exception as e:
            print(f"News extraction failed for {symbol}: {e}")
            return self._generate_mock_news(symbol, limit)

    async def _extract_from_alpha_vantage_news(self, symbol: str, limit: int) -> List[Dict]:
        source = self.sources['alpha_vantage']
        
        params = {
            'function': 'NEWS_SENTIMENT',
            'tickers': symbol,
            'apikey': source.api_key,
            'limit': limit
        }
        
        async with self.session.get(source.url, params=params, timeout=source.timeout) as response:
            if response.status != 200:
                raise MarketDataError(f"Alpha Vantage API error: {response.status}")
            
            data = await response.json()
            
            if 'Error Message' in data:
                raise MarketDataError(f"Alpha Vantage error: {data['Error Message']}")
            
            return data.get('feed', [])

    def _generate_mock_news(self, symbol: str, limit: int) -> List[Dict]:
        news_items = []
        
        for i in range(min(limit, 10)):
            timestamp = datetime.now() - timedelta(hours=i*2)
            
            news_items.append({
                'title': f'Market Update: {symbol} Shows Strong Performance',
                'url': f'https://example.com/news/{symbol}/{i}',
                'time_published': timestamp.strftime('%Y%m%dT%H%M%S'),
                'authors': ['Market Analyst'],
                'summary': f'Analysis of {symbol} recent market movements and outlook.',
                'source': 'mock',
                'sentiment_score': np.random.uniform(-1, 1),
                'sentiment_label': np.random.choice(['Bearish', 'Neutral', 'Bullish'])
            })
        
        return news_items

    async def close(self):
        if self.session:
            await self.session.close()


class AlternativeDataExtractor(DataExtractor):
    def __init__(self):
        self.sources = {
            'satellite': DataSource(
                name='satellite',
                url='https://api.satellite-data.com',
                api_key='demo',
                rate_limit=100
            ),
            'social_sentiment': DataSource(
                name='social_sentiment',
                url='https://api.social-sentiment.com',
                api_key='demo',
                rate_limit=1000
            )
        }

    async def extract(self, symbols: List[str], **kwargs) -> Dict[str, Any]:
        data = {}
        
        for symbol in symbols:
            data[symbol] = {
                'satellite_data': self._generate_mock_satellite_data(symbol),
                'social_sentiment': self._generate_mock_social_sentiment(symbol),
                'web_scraping': self._generate_mock_web_data(symbol)
            }
        
        return data

    def _generate_mock_satellite_data(self, symbol: str) -> Dict:
        return {
            'parking_lot_occupancy': np.random.uniform(0.4, 0.9),
            'shipping_activity': np.random.randint(50, 200),
            'construction_activity': np.random.uniform(0, 1),
            'timestamp': datetime.now().isoformat()
        }

    def _generate_mock_social_sentiment(self, symbol: str) -> Dict:
        return {
            'twitter_sentiment': np.random.uniform(-1, 1),
            'reddit_mentions': np.random.randint(10, 1000),
            'news_sentiment': np.random.uniform(-1, 1),
            'overall_sentiment': np.random.uniform(-1, 1),
            'timestamp': datetime.now().isoformat()
        }

    def _generate_mock_web_data(self, symbol: str) -> Dict:
        return {
            'website_traffic': np.random.randint(1000, 100000),
            'product_reviews': np.random.uniform(1, 5),
            'job_postings': np.random.randint(0, 500),
            'timestamp': datetime.now().isoformat()
        }


def create_data_extractor(extractor_type: str = "market_data") -> DataExtractor:
    if extractor_type == "market_data":
        return MarketDataExtractor()
    elif extractor_type == "fundamental":
        return FundamentalDataExtractor()
    elif extractor_type == "news":
        return NewsDataExtractor()
    elif extractor_type == "alternative":
        return AlternativeDataExtractor()
    return MarketDataExtractor()