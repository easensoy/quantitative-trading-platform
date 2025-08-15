from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union, Callable
import pandas as pd
import numpy as np
import asyncio
import json
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import websocket
import threading

# Refinitiv Eikon/Workspace imports
try:
    import eikon as ek
    import refinitiv.dataplatform.eikon as rdp
    REFINITIV_AVAILABLE = True
except ImportError:
    REFINITIV_AVAILABLE = False
    print("Refinitiv Eikon API not available. Install eikon package for Refinitiv connectivity.")

from src.core.config import get_config
from src.core.exceptions import DatabaseError
from src.data.loaders import DataLoader


class RefinitivConnector:
    """Refinitiv Eikon/Workspace API connector for market data"""
    
    def __init__(self, config: Optional[Dict] = None):
        if not REFINITIV_AVAILABLE:
            raise DatabaseError("Refinitiv Eikon API not available")
            
        self.config = config or get_config().refinitiv
        self.is_connected = False
        self.callbacks: Dict[str, List[Callable]] = {}
        self.streaming_session = None

    async def connect(self) -> bool:
        """Connect to Refinitiv Eikon/Workspace"""
        try:
            # Set app key for Eikon
            app_key = self.config.get('app_key', 'DEFAULT_CODE_BOOK_APP_KEY')
            ek.set_app_key(app_key)
            
            # Test connection
            test_data = ek.get_data(['AAPL.O'], ['TR.CommonName'])
            if test_data[0] is not None and not test_data[0].empty:
                self.is_connected = True
                print("Successfully connected to Refinitiv Eikon")
                return True
            else:
                raise DatabaseError("Refinitiv connection test failed")
                
        except Exception as e:
            raise DatabaseError(f"Failed to connect to Refinitiv: {e}")

    async def disconnect(self) -> None:
        """Disconnect from Refinitiv"""
        self.is_connected = False
        if self.streaming_session:
            self.streaming_session.close()
        print("Disconnected from Refinitiv")

    async def get_historical_data(self, instruments: List[str], fields: List[str],
                                 start_date: str, end_date: str, 
                                 frequency: str = 'D') -> pd.DataFrame:
        """Get historical time series data"""
        if not self.is_connected:
            await self.connect()

        try:
            # Convert date format if needed
            if len(start_date) == 8:  # YYYYMMDD format
                start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            if len(end_date) == 8:
                end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

            # Get historical data using Eikon
            data, err = ek.get_data(
                instruments=instruments,
                fields=fields,
                parameters={
                    'SDate': start_date,
                    'EDate': end_date,
                    'Frq': frequency
                }
            )

            if err:
                raise DatabaseError(f"Refinitiv API error: {err}")

            return data

        except Exception as e:
            raise DatabaseError(f"Failed to get Refinitiv historical data: {e}")

    async def get_reference_data(self, instruments: List[str], fields: List[str]) -> pd.DataFrame:
        """Get reference/fundamental data"""
        if not self.is_connected:
            await self.connect()

        try:
            data, err = ek.get_data(
                instruments=instruments,
                fields=fields
            )

            if err:
                raise DatabaseError(f"Refinitiv API error: {err}")

            return data

        except Exception as e:
            raise DatabaseError(f"Failed to get Refinitiv reference data: {e}")

    async def get_timeseries_data(self, ric: str, start_date: str, end_date: str,
                                 interval: str = 'daily') -> pd.DataFrame:
        """Get time series data for a single RIC"""
        if not self.is_connected:
            await self.connect()

        try:
            # Convert interval to Eikon format
            interval_map = {
                'minute': '1min',
                'hourly': '1h', 
                'daily': 'daily',
                'weekly': 'weekly',
                'monthly': 'monthly'
            }
            
            eikon_interval = interval_map.get(interval, 'daily')

            data = ek.get_timeseries(
                rics=ric,
                start_date=start_date,
                end_date=end_date,
                interval=eikon_interval,
                fields=['OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME']
            )

            return data

        except Exception as e:
            raise DatabaseError(f"Failed to get Refinitiv time series: {e}")

    async def get_news_data(self, query: str, count: int = 100) -> pd.DataFrame:
        """Get news headlines and data"""
        if not self.is_connected:
            await self.connect()

        try:
            news_data = ek.get_news_headlines(
                query=query,
                count=count,
                date_from=datetime.now() - timedelta(days=7),
                date_to=datetime.now()
            )

            return news_data

        except Exception as e:
            raise DatabaseError(f"Failed to get Refinitiv news data: {e}")

    async def search_instruments(self, search_term: str, asset_class: str = 'equity') -> pd.DataFrame:
        """Search for financial instruments"""
        if not self.is_connected:
            await self.connect()

        try:
            # Use symbol search
            search_results = ek.get_symbology(
                symbol=search_term,
                from_symbol_type='symbol',
                to_symbol_type=['RIC', 'ISIN', 'CUSIP'],
                raw_output=False
            )

            return search_results

        except Exception as e:
            raise DatabaseError(f"Failed to search Refinitiv instruments: {e}")

    async def get_company_data(self, rics: List[str]) -> pd.DataFrame:
        """Get comprehensive company fundamental data"""
        if not self.is_connected:
            await self.connect()

        try:
            # Define comprehensive field set
            fields = [
                'TR.CommonName',
                'TR.BusinessSummary',
                'TR.HeadquartersCountry',
                'TR.GICSIndustryGroupName',
                'TR.GICSSectorName',
                'TR.Revenue',
                'TR.NetIncome',
                'TR.TotalAssets',
                'TR.TotalDebt',
                'TR.MarketCap',
                'TR.BookValuePerShare',
                'TR.DividendYield',
                'TR.PERatio',
                'TR.PriceToBookValue',
                'TR.ROE',
                'TR.ROA',
                'TR.DebtToEquity',
                'TR.Beta'
            ]

            data, err = ek.get_data(
                instruments=rics,
                fields=fields
            )

            if err:
                raise DatabaseError(f"Refinitiv API error: {err}")

            return data

        except Exception as e:
            raise DatabaseError(f"Failed to get Refinitiv company data: {e}")


class RefinitivDataProvider:
    """High-level Refinitiv data provider for QuantCore"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.connector = RefinitivConnector(config)
        self.config = config or get_config().refinitiv

    async def get_equity_data(self, symbols: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Get equity market data"""
        # Convert symbols to RICs if needed
        rics = [f"{symbol}.O" if not symbol.endswith(('.O', '.N', '.K', '.L')) else symbol 
                for symbol in symbols]
        
        fields = [
            'TR.OPENPRICE', 'TR.HIGHPRICE', 'TR.LOWPRICE', 'TR.CLOSEPRICE',
            'TR.VOLUME', 'TR.PctChg', 'TR.Volatility30D'
        ]
        
        data = await self.connector.get_historical_data(rics, fields, start_date, end_date)
        
        # Standardize column names
        column_mapping = {
            'TR.OPENPRICE': 'open',
            'TR.HIGHPRICE': 'high',
            'TR.LOWPRICE': 'low', 
            'TR.CLOSEPRICE': 'close',
            'TR.VOLUME': 'volume',
            'TR.PctChg': 'daily_return',
            'TR.Volatility30D': 'volatility_30d'
        }
        
        data = data.rename(columns=column_mapping)
        return data

    async def get_fx_data(self, currency_pairs: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Get FX market data"""
        # Convert currency pairs to Refinitiv FX RICs
        fx_rics = [f"{pair}=" for pair in currency_pairs]
        
        data_frames = []
        for ric in fx_rics:
            try:
                ts_data = await self.connector.get_timeseries_data(ric, start_date, end_date)
                ts_data['instrument'] = ric
                data_frames.append(ts_data)
            except Exception as e:
                print(f"Failed to get FX data for {ric}: {e}")
        
        return pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()

    async def get_fixed_income_data(self, cusips: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Get fixed income data"""
        fields = [
            'TR.MIDPRICE',
            'TR.YIELD',
            'TR.MODDURATION',
            'TR.CONVEXITY',
            'TR.BIDPRICE',
            'TR.ASKPRICE',
            'TR.CREDITRATING'
        ]
        
        return await self.connector.get_historical_data(cusips, fields, start_date, end_date)

    async def get_commodities_data(self, commodity_symbols: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        """Get commodity market data"""
        # Convert to Refinitiv commodity RICs
        commodity_rics = []
        for symbol in commodity_symbols:
            if symbol.upper() == 'CRUDE':
                commodity_rics.append('CLc1')  # WTI Crude Oil
            elif symbol.upper() == 'GOLD':
                commodity_rics.append('XAU=')  # Gold
            elif symbol.upper() == 'SILVER':
                commodity_rics.append('XAG=')  # Silver
            else:
                commodity_rics.append(symbol)
        
        data_frames = []
        for ric in commodity_rics:
            try:
                ts_data = await self.connector.get_timeseries_data(ric, start_date, end_date)
                ts_data['instrument'] = ric
                data_frames.append(ts_data)
            except Exception as e:
                print(f"Failed to get commodity data for {ric}: {e}")
        
        return pd.concat(data_frames, ignore_index=True) if data_frames else pd.DataFrame()

    async def get_esg_data(self, rics: List[str]) -> pd.DataFrame:
        """Get ESG (Environmental, Social, Governance) data"""
        esg_fields = [
            'TR.TRESGScore',
            'TR.EnvironmentPillarScore', 
            'TR.SocialPillarScore',
            'TR.GovernancePillarScore',
            'TR.TRESGCombinedScore',
            'TR.TRESGControversiesScore',
            'TR.TRESGResourceUseScore',
            'TR.TRESGEmissionsScore'
        ]
        
        return await self.connector.get_reference_data(rics, esg_fields)

    async def get_options_data(self, underlying_rics: List[str]) -> pd.DataFrame:
        """Get options data"""
        options_fields = [
            'TR.OPENPRICE',
            'TR.CLOSEPRICE', 
            'TR.BIDPRICE',
            'TR.ASKPRICE',
            'TR.VOLUME',
            'TR.IMPLIEDVOL',
            'TR.OPTIONOPENINTEREST',
            'TR.OPTIONDELTA',
            'TR.OPTIONGAMMA',
            'TR.OPTIONTHETA',
            'TR.OPTIONVEGA'
        ]
        
        # This would need more complex logic to get actual options chains
        # This is a simplified example
        return await self.connector.get_reference_data(underlying_rics, options_fields)

    async def get_earnings_data(self, rics: List[str], periods: int = 8) -> pd.DataFrame:
        """Get earnings estimates and actuals"""
        earnings_fields = [
            'TR.EPSMeanEst',
            'TR.EPSActual',
            'TR.EPSSurprisePct',
            'TR.RevenueEst', 
            'TR.RevenueActual',
            'TR.RevenueSurprisePct'
        ]
        
        # Get data for multiple periods
        parameters = {'Period': f'FQ{periods}'}
        
        data, err = ek.get_data(
            instruments=rics,
            fields=earnings_fields,
            parameters=parameters
        )
        
        if err:
            raise DatabaseError(f"Refinitiv earnings data error: {err}")
            
        return data

    async def get_analyst_recommendations(self, rics: List[str]) -> pd.DataFrame:
        """Get analyst recommendations and price targets"""
        analyst_fields = [
            'TR.TPMeanEst',
            'TR.TPHighEst',
            'TR.TPLowEst',
            'TR.RecommendationMean',
            'TR.NumOfRecommendations',
            'TR.BrokerRecCode',
            'TR.AnalystDate'
        ]
        
        return await self.connector.get_reference_data(rics, analyst_fields)

    async def close(self) -> None:
        """Close Refinitiv connection"""
        await self.connector.disconnect()


class RefinitivLoader(DataLoader):
    """Refinitiv data loader for QuantCore data pipeline"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.provider = RefinitivDataProvider(config)
        self.config = config or get_config().refinitiv

    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        """Load method - Refinitiv is typically a data source"""
        raise NotImplementedError("Refinitiv is typically a data source, not destination")

    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        """Create table method - not applicable for Refinitiv"""
        return True

    async def extract_equity_universe(self, index: str = 'SP500') -> pd.DataFrame:
        """Extract equity universe from an index"""
        try:
            # Get S&P 500 constituents
            if index == 'SP500':
                universe_ric = '.SPX'
                constituents = ek.get_data(
                    universe_ric, 
                    ['TR.IndexConstituentRIC', 'TR.IndexConstituentName', 'TR.IndexConstituentWeightPercent']
                )[0]
            else:
                # Generic index constituent extraction
                constituents = ek.get_data(
                    index, 
                    ['TR.IndexConstituentRIC', 'TR.IndexConstituentName']
                )[0]
            
            return constituents
            
        except Exception as e:
            print(f"Failed to extract equity universe: {e}")
            return pd.DataFrame()

    async def extract_and_load_to_warehouse(self, rics: List[str], start_date: str, 
                                           end_date: str, warehouse_loader: DataLoader) -> bool:
        """Extract from Refinitiv and load to data warehouse"""
        try:
            # Get equity data
            equity_data = await self.provider.get_equity_data(rics, start_date, end_date)
            if not equity_data.empty:
                await warehouse_loader.load(equity_data, "refinitiv_equity_data")
            
            # Get company fundamental data
            company_data = await self.provider.connector.get_company_data(rics)
            if not company_data.empty:
                await warehouse_loader.load(company_data, "refinitiv_company_data")
            
            # Get ESG data
            esg_data = await self.provider.get_esg_data(rics)
            if not esg_data.empty:
                await warehouse_loader.load(esg_data, "refinitiv_esg_data")
            
            return True
            
        except Exception as e:
            print(f"Failed to extract and load Refinitiv data: {e}")
            return False

    async def close(self) -> None:
        await self.provider.close()


# Factory functions
def create_refinitiv_connector() -> RefinitivConnector:
    """Create Refinitiv connector"""
    return RefinitivConnector()


def create_refinitiv_provider() -> RefinitivDataProvider:
    """Create Refinitiv data provider"""  
    return RefinitivDataProvider()


def create_refinitiv_loader() -> RefinitivLoader:
    """Create Refinitiv data loader"""
    return RefinitivLoader()


# Example usage and testing
class RefinitivDataTester:
    """Test Refinitiv connectivity and data retrieval"""
    
    def __init__(self):
        self.provider = RefinitivDataProvider()

    async def test_connection(self) -> bool:
        """Test Refinitiv connection"""
        try:
            await self.provider.connector.connect()
            print("Refinitiv connection test: PASSED")
            return True
        except Exception as e:
            print(f"Refinitiv connection test: FAILED - {e}")
            return False

    async def test_reference_data(self) -> bool:
        """Test reference data retrieval"""
        try:
            data = await self.provider.connector.get_company_data(["AAPL.O", "MSFT.O"])
            print(f"Reference data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Reference data test: FAILED - {e}")
            return False

    async def test_historical_data(self) -> bool:
        """Test historical data retrieval"""
        try:
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            
            data = await self.provider.get_equity_data(["AAPL"], start_date, end_date)
            print(f"Historical data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Historical data test: FAILED - {e}")
            return False

    async def test_esg_data(self) -> bool:
        """Test ESG data retrieval"""
        try:
            data = await self.provider.get_esg_data(["AAPL.O"])
            print(f"ESG data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"ESG data test: FAILED - {e}")
            return False

    async def run_all_tests(self) -> None:
        """Run all Refinitiv tests"""
        print("Running Refinitiv API tests...")
        
        connection_ok = await self.test_connection()
        if connection_ok:
            await self.test_reference_data()
            await self.test_historical_data()
            await self.test_esg_data()
        
        await self.provider.close()