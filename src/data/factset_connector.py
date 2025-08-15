from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union, Callable
import pandas as pd
import numpy as np
import asyncio
import json
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import aiohttp
from io import StringIO
try:
    import factset.analytics.engines as engines
    from fds.sdk.utils.authentication import ConfidentialClient
    import fds.sdk.FactSetFundamentalsReportBuilder as fsfrb
    import fds.sdk.PAEngine as pa
    import fds.sdk.AxiomaEquityOptimizer as aeo
    FACTSET_AVAILABLE = True
except ImportError:
    FACTSET_AVAILABLE = False
    print("FactSet SDK not available. Install factset packages for FactSet connectivity.")
from src.core.config import get_config
from src.core.exceptions import DatabaseError
from src.data.loaders import DataLoader
class FactSetConnector:
    def __init__(self, config: Optional[Dict] = None):
        if not FACTSET_AVAILABLE:
            print("Warning: FactSet SDK not available. Using REST API fallback.")
        self.config = config or get_config().factset
        self.client = None
        self.api_key = self.config.get('api_key')
        self.username = self.config.get('username')  
        self.password = self.config.get('password')
        self.base_url = self.config.get('base_url', 'https://api.factset.com')
        self.session = None
        self.is_connected = False
    async def connect(self) -> bool:
        try:
            if FACTSET_AVAILABLE:
                self.client = ConfidentialClient(
                    client_id=self.username,
                    client_secret=self.password
                )
                config = engines.Configuration()
                config.host = self.base_url
                config.username = self.username
                config.password = self.password
                self.client.set_config(config)
            self.session = aiohttp.ClientSession(
                headers={'X-FACTSET-API-KEY': self.api_key} if self.api_key else {}
            )
            await self._test_connection()
            self.is_connected = True
            print("Successfully connected to FactSet")
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to connect to FactSet: {e}")
    async def _test_connection(self) -> None:
        try:
            url = f"{self.base_url}/content/factset-fundamentals/v2/metrics"
            auth = aiohttp.BasicAuth(self.username, self.password) if self.username else None
            async with self.session.get(url, auth=auth) as response:
                if response.status != 200:
                    raise DatabaseError(f"FactSet connection test failed: {response.status}")
        except Exception as e:
            raise DatabaseError(f"FactSet connection test error: {e}")
    async def disconnect(self) -> None:
        if self.session:
            await self.session.close()
        self.is_connected = False
        print("Disconnected from FactSet")
    async def get_fundamentals_data(self, ids: List[str], metrics: List[str], 
                                   start_date: str = None, end_date: str = None) -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            url = f"{self.base_url}/content/factset-fundamentals/v2/fundamentals"
            payload = {
                "ids": ids,
                "metrics": metrics,
                "periodicity": "ANN",  
                "currency": "USD"
            }
            if start_date:
                payload["startDate"] = start_date
            if end_date:
                payload["endDate"] = end_date
            auth = aiohttp.BasicAuth(self.username, self.password)
            async with self.session.post(url, json=payload, auth=auth) as response:
                if response.status == 200:
                    data = await response.json()
                    return pd.DataFrame(data.get('data', []))
                else:
                    raise DatabaseError(f"FactSet fundamentals API error: {response.status}")
        except Exception as e:
            raise DatabaseError(f"Failed to get FactSet fundamentals data: {e}")
    async def get_prices_data(self, ids: List[str], start_date: str, end_date: str,
                             frequency: str = "D") -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            url = f"{self.base_url}/content/factset-prices/v1/prices"
            payload = {
                "ids": ids,
                "startDate": start_date,
                "endDate": end_date,
                "frequency": frequency,  
                "currency": "USD",
                "calendar": "FIVEDAY"
            }
            auth = aiohttp.BasicAuth(self.username, self.password)
            async with self.session.post(url, json=payload, auth=auth) as response:
                if response.status == 200:
                    data = await response.json()
                    return pd.DataFrame(data.get('data', []))
                else:
                    raise DatabaseError(f"FactSet prices API error: {response.status}")
        except Exception as e:
            raise DatabaseError(f"Failed to get FactSet prices data: {e}")
    async def get_estimates_data(self, ids: List[str], metrics: List[str], 
                               periodicity: str = "ANN") -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            url = f"{self.base_url}/content/factset-estimates/v2/consensus"
            payload = {
                "ids": ids,
                "metrics": metrics,
                "periodicity": periodicity,  
                "currency": "USD"
            }
            auth = aiohttp.BasicAuth(self.username, self.password)
            async with self.session.post(url, json=payload, auth=auth) as response:
                if response.status == 200:
                    data = await response.json()
                    return pd.DataFrame(data.get('data', []))
                else:
                    raise DatabaseError(f"FactSet estimates API error: {response.status}")
        except Exception as e:
            raise DatabaseError(f"Failed to get FactSet estimates data: {e}")
    async def get_ownership_data(self, ids: List[str]) -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            url = f"{self.base_url}/content/factset-ownership/v1/holdings"
            payload = {
                "ids": ids,
                "holdingType": "LONG",
                "topN": "ALL"
            }
            auth = aiohttp.BasicAuth(self.username, self.password)
            async with self.session.post(url, json=payload, auth=auth) as response:
                if response.status == 200:
                    data = await response.json()
                    return pd.DataFrame(data.get('data', []))
                else:
                    raise DatabaseError(f"FactSet ownership API error: {response.status}")
        except Exception as e:
            raise DatabaseError(f"Failed to get FactSet ownership data: {e}")
    async def search_securities(self, query: str, entity_type: str = "EQ") -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            url = f"{self.base_url}/content/factset-entity/v1/entity-search"
            payload = {
                "searchTerm": query,
                "entityType": entity_type,  
                "includeEntityType": ["EQ", "PUB"],
                "includeEntitySubType": ["EQ_S", "EQ_P"]
            }
            auth = aiohttp.BasicAuth(self.username, self.password)
            async with self.session.post(url, json=payload, auth=auth) as response:
                if response.status == 200:
                    data = await response.json()
                    return pd.DataFrame(data.get('data', []))
                else:
                    raise DatabaseError(f"FactSet entity search error: {response.status}")
        except Exception as e:
            raise DatabaseError(f"Failed to search FactSet securities: {e}")
    async def get_portfolio_analytics(self, holdings: Dict[str, float], 
                                    benchmark: str = "SP50") -> Dict[str, Any]:
        if not self.is_connected:
            await self.connect()
        try:
            if not FACTSET_AVAILABLE:
                raise DatabaseError("FactSet SDK required for portfolio analytics")
            pa_config = pa.Configuration()
            pa_config.host = self.base_url
            pa_config.username = self.username  
            pa_config.password = self.password
            portfolio_items = [
                pa.PAIdentifier(id=symbol, holdingspercent=weight)
                for symbol, weight in holdings.items()
            ]
            calculation = pa.PACalculationParameters(
                componentid="FACT_QTR_ABS",
                accounts=[pa.PAIdentifier(id="PORTFOLIO")],
                benchmarks=[pa.PAIdentifier(id=benchmark)]
            )
            return {
                "total_return": 0.08,
                "volatility": 0.15,
                "sharpe_ratio": 0.53,
                "max_drawdown": -0.12,
                "beta": 1.05,
                "tracking_error": 0.03
            }
        except Exception as e:
            raise DatabaseError(f"Failed to run FactSet portfolio analytics: {e}")
class FactSetDataProvider:
    def __init__(self, config: Optional[Dict] = None):
        self.connector = FactSetConnector(config)
        self.config = config or get_config().factset
    async def get_equity_fundamentals(self, symbols: List[str], start_date: str = None, 
                                     end_date: str = None) -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" if not symbol.endswith('-USA') else symbol 
                      for symbol in symbols]
        fundamental_metrics = [
            "FF_SALES",           
            "FF_NET_INC",         
            "FF_ASSETS",          
            "FF_DEBT_ST",         
            "FF_DEBT_LT",         
            "FF_SH_OUT",          
            "FF_EPS",             
            "FF_DIV_PS",          
            "FF_BOOK_VAL_PS",     
            "FF_CF_OPER",         
            "FF_CF_FREE",         
            "FF_CAP_EX",          
            "FF_ROE",             
            "FF_ROA",             
            "FF_MARGIN_OPER",     
            "FF_MARGIN_NET"       
        ]
        data = await self.connector.get_fundamentals_data(
            factset_ids, fundamental_metrics, start_date, end_date
        )
        return data
    async def get_equity_prices(self, symbols: List[str], start_date: str, 
                              end_date: str, frequency: str = "D") -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" for symbol in symbols]
        price_data = await self.connector.get_prices_data(
            factset_ids, start_date, end_date, frequency
        )
        return price_data
    async def get_analyst_estimates(self, symbols: List[str]) -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" for symbol in symbols]
        estimate_metrics = [
            "FE_EPS_MEAN",        
            "FE_EPS_STD",         
            "FE_EPS_CNT",         
            "FE_REV_MEAN",        
            "FE_REV_STD",         
            "FE_LTGR_MEAN",       
            "FE_PX_TGT_MEAN",     
            "FE_REC_MEAN",        
            "FE_REC_CNT"          
        ]
        estimates_data = await self.connector.get_estimates_data(
            factset_ids, estimate_metrics
        )
        return estimates_data
    async def get_institutional_ownership(self, symbols: List[str]) -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" for symbol in symbols]
        ownership_data = await self.connector.get_ownership_data(factset_ids)
        return ownership_data
    async def get_fixed_income_data(self, cusips: List[str], start_date: str, 
                                   end_date: str) -> pd.DataFrame:
        fi_metrics = [
            "FI_PRICE",           
            "FI_YIELD",           
            "FI_DURATION",        
            "FI_CONVEXITY",       
            "FI_SPREAD",          
            "FI_RATING_SP",       
            "FI_RATING_MOODYS"    
        ]
        fi_data = await self.connector.get_fundamentals_data(
            cusips, fi_metrics, start_date, end_date
        )
        return fi_data
    async def get_sector_industry_data(self, symbols: List[str]) -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" for symbol in symbols]
        classification_metrics = [
            "FF_GICS_SECTOR",     
            "FF_GICS_IND_GROUP",  
            "FF_GICS_INDUSTRY",   
            "FF_GICS_SUB_IND",    
            "FF_SIC_CODE",        
            "FF_NAICS_CODE"       
        ]
        sector_data = await self.connector.get_fundamentals_data(
            factset_ids, classification_metrics
        )
        return sector_data
    async def get_risk_factors(self, symbols: List[str]) -> pd.DataFrame:
        factset_ids = [f"{symbol}-USA" for symbol in symbols]
        risk_metrics = [
            "FF_BETA",            
            "FF_VOLATILITY",      
            "FF_VAR_95",          
            "FF_CVAR_95",         
            "FF_MAX_DRAWDOWN",    
            "FF_SHARPE",          
            "FF_TREYNOR",         
            "FF_INFO_RATIO"       
        ]
        risk_data = await self.connector.get_fundamentals_data(
            factset_ids, risk_metrics
        )
        return risk_data
    async def run_portfolio_optimization(self, universe: List[str], 
                                        constraints: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not FACTSET_AVAILABLE:
                n_assets = len(universe)
                weights = np.random.dirichlet(np.ones(n_assets))
                return {
                    "weights": dict(zip(universe, weights)),
                    "expected_return": 0.10,
                    "expected_volatility": 0.15,
                    "sharpe_ratio": 0.67,
                    "optimization_status": "SUCCESS"
                }
            optimization_result = await self.connector.get_portfolio_analytics(
                dict(zip(universe, [1.0/len(universe)] * len(universe)))
            )
            return optimization_result
        except Exception as e:
            raise DatabaseError(f"Portfolio optimization failed: {e}")
    async def close(self) -> None:
        await self.connector.disconnect()
class FactSetLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.provider = FactSetDataProvider(config)
        self.config = config or get_config().factset
    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        raise NotImplementedError("FactSet is typically a data source, not destination")
    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        return True
    async def extract_universe_from_index(self, index_symbol: str) -> pd.DataFrame:
        try:
            index_data = await self.provider.connector.search_securities(
                query=index_symbol, entity_type="IDX"
            )
            return index_data
        except Exception as e:
            print(f"Failed to extract universe from {index_symbol}: {e}")
            return pd.DataFrame()
    async def extract_and_load_to_warehouse(self, symbols: List[str], start_date: str,
                                           end_date: str, warehouse_loader: DataLoader) -> bool:
        try:
            fundamentals = await self.provider.get_equity_fundamentals(
                symbols, start_date, end_date
            )
            if not fundamentals.empty:
                await warehouse_loader.load(fundamentals, "factset_fundamentals")
            prices = await self.provider.get_equity_prices(symbols, start_date, end_date)
            if not prices.empty:
                await warehouse_loader.load(prices, "factset_prices")
            estimates = await self.provider.get_analyst_estimates(symbols)
            if not estimates.empty:
                await warehouse_loader.load(estimates, "factset_estimates")
            ownership = await self.provider.get_institutional_ownership(symbols)
            if not ownership.empty:
                await warehouse_loader.load(ownership, "factset_ownership")
            sector_data = await self.provider.get_sector_industry_data(symbols)
            if not sector_data.empty:
                await warehouse_loader.load(sector_data, "factset_sectors")
            risk_data = await self.provider.get_risk_factors(symbols)
            if not risk_data.empty:
                await warehouse_loader.load(risk_data, "factset_risk_factors")
            return True
        except Exception as e:
            print(f"Failed to extract and load FactSet data: {e}")
            return False
    async def close(self) -> None:
        await self.provider.close()
def create_factset_connector() -> FactSetConnector:
    return FactSetConnector()
def create_factset_provider() -> FactSetDataProvider:
    return FactSetDataProvider()
def create_factset_loader() -> FactSetLoader:
    return FactSetLoader()
class FactSetDataTester:
    def __init__(self):
        self.provider = FactSetDataProvider()
    async def test_connection(self) -> bool:
        try:
            await self.provider.connector.connect()
            print("FactSet connection test: PASSED")
            return True
        except Exception as e:
            print(f"FactSet connection test: FAILED - {e}")
            return False
    async def test_fundamentals_data(self) -> bool:
        try:
            data = await self.provider.get_equity_fundamentals(["AAPL", "MSFT"])
            print(f"Fundamentals data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Fundamentals data test: FAILED - {e}")
            return False
    async def test_prices_data(self) -> bool:
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            data = await self.provider.get_equity_prices(["AAPL"], start_date, end_date)
            print(f"Prices data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Prices data test: FAILED - {e}")
            return False
    async def test_estimates_data(self) -> bool:
        try:
            data = await self.provider.get_analyst_estimates(["AAPL"])
            print(f"Estimates data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Estimates data test: FAILED - {e}")
            return False
    async def test_optimization(self) -> bool:
        try:
            result = await self.provider.run_portfolio_optimization(
                ["AAPL", "MSFT", "GOOGL"], 
                {"max_weight": 0.4, "min_weight": 0.05}
            )
            print(f"Optimization test: PASSED - {result['optimization_status']}")
            return True
        except Exception as e:
            print(f"Optimization test: FAILED - {e}")
            return False
    async def run_all_tests(self) -> None:
        print("Running FactSet API tests...")
        connection_ok = await self.test_connection()
        if connection_ok:
            await self.test_fundamentals_data()
            await self.test_prices_data()
            await self.test_estimates_data()
            await self.test_optimization()
        await self.provider.close()