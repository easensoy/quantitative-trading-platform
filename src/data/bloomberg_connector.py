from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union, Callable
import pandas as pd
import numpy as np
import asyncio
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import time
try:
    import blpapi
    BLOOMBERG_AVAILABLE = True
except ImportError:
    BLOOMBERG_AVAILABLE = False
    print("Bloomberg API not available. Install blpapi package for Bloomberg connectivity.")
from src.core.config import get_config
from src.core.exceptions import DatabaseError
from src.data.loaders import DataLoader
class BloombergConnector:
    def __init__(self, config: Optional[Dict] = None):
        if not BLOOMBERG_AVAILABLE:
            raise DatabaseError("Bloomberg API (blpapi) not available")
        self.config = config or get_config().bloomberg
        self.session = None
        self.ref_data_service = None
        self.mkt_data_service = None
        self.is_connected = False
        self.subscription_list = blpapi.SubscriptionList()
        self.callbacks: Dict[str, List[Callable]] = {}
        self.executor = ThreadPoolExecutor(max_workers=4)
    async def connect(self) -> bool:
        try:
            session_options = blpapi.SessionOptions()
            session_options.setServerHost(self.config.get('host', 'localhost'))
            session_options.setServerPort(self.config.get('port', 8194))
            self.session = blpapi.Session(session_options)
            if not self.session.start():
                raise DatabaseError("Failed to start Bloomberg session")
            if not self.session.openService("//blp/refdata"):
                raise DatabaseError("Failed to open Bloomberg reference data service")
            if not self.session.openService("//blp/mktdata"):
                raise DatabaseError("Failed to open Bloomberg market data service")
            self.ref_data_service = self.session.getService("//blp/refdata")
            self.mkt_data_service = self.session.getService("//blp/mktdata")
            self.is_connected = True
            print("Successfully connected to Bloomberg")
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to connect to Bloomberg: {e}")
    async def disconnect(self) -> None:
        if self.session:
            self.session.stop()
            self.is_connected = False
            print("Disconnected from Bloomberg")
    async def get_reference_data(self, securities: List[str], fields: List[str], overrides: Optional[Dict] = None) -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            request = self.ref_data_service.createRequest("ReferenceDataRequest")
            for security in securities:
                request.getElement("securities").appendValue(security)
            for field in fields:
                request.getElement("fields").appendValue(field)
            if overrides:
                overrides_element = request.getElement("overrides")
                for field_id, value in overrides.items():
                    override = overrides_element.appendElement()
                    override.setElement("fieldId", field_id)
                    override.setElement("value", str(value))
            request_id = self.session.sendRequest(request)
            data = []
            while True:
                event = self.session.nextEvent(1000)  
                if event.eventType() == blpapi.Event.RESPONSE:
                    for msg in event:
                        if msg.hasElement("securityData"):
                            security_data_array = msg.getElement("securityData")
                            for i in range(security_data_array.numValues()):
                                security_data = security_data_array.getValue(i)
                                security = security_data.getElement("security").getValue()
                                row_data = {"security": security}
                                if security_data.hasElement("fieldData"):
                                    field_data = security_data.getElement("fieldData")
                                    for field in fields:
                                        if field_data.hasElement(field):
                                            value = field_data.getElement(field).getValue()
                                            row_data[field] = value
                                        else:
                                            row_data[field] = None
                                if security_data.hasElement("fieldExceptions"):
                                    exceptions = security_data.getElement("fieldExceptions")
                                    for j in range(exceptions.numValues()):
                                        exc = exceptions.getValue(j)
                                        field_id = exc.getElement("fieldId").getValue()
                                        error_info = exc.getElement("errorInfo")
                                        row_data[field_id] = f"ERROR: {error_info.getElement('message').getValue()}"
                                data.append(row_data)
                    break
                elif event.eventType() == blpapi.Event.TIMEOUT:
                    break
            return pd.DataFrame(data)
        except Exception as e:
            raise DatabaseError(f"Failed to get Bloomberg reference data: {e}")
    async def get_historical_data(self, securities: List[str], fields: List[str], 
                                 start_date: str, end_date: str, 
                                 periodicity: str = "DAILY") -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            request = self.ref_data_service.createRequest("HistoricalDataRequest")
            for security in securities:
                request.getElement("securities").appendValue(security)
            for field in fields:
                request.getElement("fields").appendValue(field)
            request.set("startDate", start_date)
            request.set("endDate", end_date)
            request.set("periodicitySelection", periodicity)
            request_id = self.session.sendRequest(request)
            data = []
            while True:
                event = self.session.nextEvent(1000)
                if event.eventType() == blpapi.Event.RESPONSE:
                    for msg in event:
                        if msg.hasElement("securityData"):
                            security_data = msg.getElement("securityData")
                            security = security_data.getElement("security").getValue()
                            if security_data.hasElement("fieldData"):
                                field_data_array = security_data.getElement("fieldData")
                                for i in range(field_data_array.numValues()):
                                    field_data = field_data_array.getValue(i)
                                    row_data = {"security": security}
                                    if field_data.hasElement("date"):
                                        date_value = field_data.getElement("date").getValue()
                                        row_data["date"] = date_value
                                    for field in fields:
                                        if field_data.hasElement(field):
                                            value = field_data.getElement(field).getValue()
                                            row_data[field] = value
                                        else:
                                            row_data[field] = None
                                    data.append(row_data)
                    break
                elif event.eventType() == blpapi.Event.TIMEOUT:
                    break
            return pd.DataFrame(data)
        except Exception as e:
            raise DatabaseError(f"Failed to get Bloomberg historical data: {e}")
    async def subscribe_realtime_data(self, securities: List[str], fields: List[str], 
                                    callback: Callable = None) -> None:
        if not self.is_connected:
            await self.connect()
        try:
            for security in securities:
                subscription_string = security
                if fields:
                    subscription_string += "?fields=" + ",".join(fields)
                self.subscription_list.add(subscription_string)
                if callback:
                    if security not in self.callbacks:
                        self.callbacks[security] = []
                    self.callbacks[security].append(callback)
            self.session.subscribe(self.subscription_list)
            asyncio.create_task(self._process_market_data_events())
            print(f"Subscribed to real-time data for {len(securities)} securities")
        except Exception as e:
            raise DatabaseError(f"Failed to subscribe to Bloomberg real-time data: {e}")
    async def _process_market_data_events(self) -> None:
        while self.is_connected:
            try:
                event = self.session.nextEvent(100)  
                if event.eventType() == blpapi.Event.SUBSCRIPTION_DATA:
                    for msg in event:
                        security = msg.correlationId().value()
                        data = {}
                        for element in msg.asElement().elements():
                            field_name = element.name()
                            field_value = element.getValue()
                            data[field_name] = field_value
                        data['timestamp'] = datetime.now()
                        data['security'] = security
                        if security in self.callbacks:
                            for callback in self.callbacks[security]:
                                try:
                                    await callback(data)
                                except Exception as e:
                                    print(f"Callback error for {security}: {e}")
                elif event.eventType() == blpapi.Event.SUBSCRIPTION_STATUS:
                    for msg in event:
                        if msg.messageType() == "SubscriptionTerminated":
                            print(f"Subscription terminated: {msg}")
            except Exception as e:
                print(f"Error processing market data events: {e}")
                await asyncio.sleep(1)
    async def get_intraday_bars(self, security: str, start_datetime: str, end_datetime: str,
                              interval: int = 60) -> pd.DataFrame:
        if not self.is_connected:
            await self.connect()
        try:
            request = self.ref_data_service.createRequest("IntradayBarRequest")
            request.set("security", security)
            request.set("startDateTime", start_datetime)
            request.set("endDateTime", end_datetime)
            request.set("interval", interval)  
            request_id = self.session.sendRequest(request)
            data = []
            while True:
                event = self.session.nextEvent(1000)
                if event.eventType() == blpapi.Event.RESPONSE:
                    for msg in event:
                        if msg.hasElement("barData"):
                            bar_data = msg.getElement("barData")
                            bar_tick_data = bar_data.getElement("barTickData")
                            for i in range(bar_tick_data.numValues()):
                                bar = bar_tick_data.getValue(i)
                                row_data = {
                                    "security": security,
                                    "datetime": bar.getElement("time").getValue(),
                                    "open": bar.getElement("open").getValue(),
                                    "high": bar.getElement("high").getValue(),
                                    "low": bar.getElement("low").getValue(),
                                    "close": bar.getElement("close").getValue(),
                                    "volume": bar.getElement("volume").getValue(),
                                    "numEvents": bar.getElement("numEvents").getValue()
                                }
                                data.append(row_data)
                    break
                elif event.eventType() == blpapi.Event.TIMEOUT:
                    break
            return pd.DataFrame(data)
        except Exception as e:
            raise DatabaseError(f"Failed to get Bloomberg intraday data: {e}")
class BloombergDataProvider:
    def __init__(self, config: Optional[Dict] = None):
        self.connector = BloombergConnector(config)
        self.config = config or get_config().bloomberg
    async def get_equity_data(self, symbols: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        fields = [
            "PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST",
            "PX_VOLUME", "CHG_PCT_1D", "VOLATILITY_30D"
        ]
        bb_securities = [f"{symbol} Equity" for symbol in symbols]
        data = await self.connector.get_historical_data(
            bb_securities, fields, start_date, end_date
        )
        data = data.rename(columns={
            "PX_OPEN": "open",
            "PX_HIGH": "high", 
            "PX_LOW": "low",
            "PX_LAST": "close",
            "PX_VOLUME": "volume",
            "CHG_PCT_1D": "daily_return",
            "VOLATILITY_30D": "volatility_30d"
        })
        return data
    async def get_fx_data(self, currency_pairs: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        fields = ["PX_OPEN", "PX_HIGH", "PX_LOW", "PX_LAST", "VOLUME"]
        bb_securities = [f"{pair} Curncy" for pair in currency_pairs]
        return await self.connector.get_historical_data(
            bb_securities, fields, start_date, end_date
        )
    async def get_bond_data(self, cusips: List[str], start_date: str, end_date: str) -> pd.DataFrame:
        fields = [
            "PX_LAST", "YLD_YTM_MID", "DUR_ADJ_MID", 
            "CONVEXITY_MID", "PX_BID", "PX_ASK"
        ]
        bb_securities = [f"{cusip} Corp" for cusip in cusips]
        return await self.connector.get_historical_data(
            bb_securities, fields, start_date, end_date
        )
    async def get_fundamental_data(self, symbols: List[str]) -> pd.DataFrame:
        fields = [
            "SALES_REV_TURN", "NET_INCOME", "TOT_DEBT_TO_TOT_EQY",
            "RETURN_ON_ASSET", "RETURN_ON_EQUITY", "PE_RATIO",
            "PX_TO_BOOK_RATIO", "FREE_CASH_FLOW", "EBITDA",
            "MARKET_CAP", "BETA_ADJ_OVERRIDABLE"
        ]
        bb_securities = [f"{symbol} Equity" for symbol in symbols]
        return await self.connector.get_reference_data(bb_securities, fields)
    async def get_options_data(self, underlying_symbols: List[str], expiration: str) -> pd.DataFrame:
        fields = [
            "PX_LAST", "PX_BID", "PX_ASK", "IMPLIEDVOLATILITY_MID",
            "DELTA_MID", "GAMMA_MID", "THETA_MID", "VEGA_MID",
            "OPEN_INT", "PX_VOLUME"
        ]
        options_data = []
        for symbol in underlying_symbols:
            chain_request = f"OMON {symbol} Equity {expiration} C"
            try:
                data = await self.connector.get_reference_data([chain_request], fields)
                options_data.append(data)
            except Exception as e:
                print(f"Failed to get options data for {symbol}: {e}")
        return pd.concat(options_data, ignore_index=True) if options_data else pd.DataFrame()
    async def stream_market_data(self, symbols: List[str], callback: Callable) -> None:
        fields = ["LAST_PRICE", "BID", "ASK", "VOLUME", "TIME"]
        bb_securities = [f"{symbol} Equity" for symbol in symbols]
        await self.connector.subscribe_realtime_data(bb_securities, fields, callback)
    async def close(self) -> None:
        await self.connector.disconnect()
class BloombergLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.provider = BloombergDataProvider(config)
        self.config = config or get_config().bloomberg
    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        raise NotImplementedError("Bloomberg is typically a data source, not destination")
    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        return True
    async def extract_and_load_to_warehouse(self, symbols: List[str], start_date: str, 
                                           end_date: str, warehouse_loader: DataLoader) -> bool:
        try:
            equity_data = await self.provider.get_equity_data(symbols, start_date, end_date)
            if not equity_data.empty:
                await warehouse_loader.load(equity_data, "bloomberg_equity_data")
            fundamental_data = await self.provider.get_fundamental_data(symbols)
            if not fundamental_data.empty:
                await warehouse_loader.load(fundamental_data, "bloomberg_fundamental_data")
            return True
        except Exception as e:
            print(f"Failed to extract and load Bloomberg data: {e}")
            return False
    async def close(self) -> None:
        await self.provider.close()
def create_bloomberg_connector() -> BloombergConnector:
    return BloombergConnector()
def create_bloomberg_provider() -> BloombergDataProvider:
    return BloombergDataProvider()
def create_bloomberg_loader() -> BloombergLoader:
    return BloombergLoader()
class BloombergDataTester:
    def __init__(self):
        self.provider = BloombergDataProvider()
    async def test_connection(self) -> bool:
        try:
            await self.provider.connector.connect()
            print("Bloomberg connection test: PASSED")
            return True
        except Exception as e:
            print(f"Bloomberg connection test: FAILED - {e}")
            return False
    async def test_reference_data(self) -> bool:
        try:
            data = await self.provider.get_fundamental_data(["AAPL", "MSFT"])
            print(f"Reference data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Reference data test: FAILED - {e}")
            return False
    async def test_historical_data(self) -> bool:
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
            data = await self.provider.get_equity_data(["AAPL"], start_date, end_date)
            print(f"Historical data test: PASSED - Retrieved {len(data)} rows")
            return True
        except Exception as e:
            print(f"Historical data test: FAILED - {e}")
            return False
    async def run_all_tests(self) -> None:
        print("Running Bloomberg API tests...")
        connection_ok = await self.test_connection()
        if connection_ok:
            await self.test_reference_data()
            await self.test_historical_data()
        await self.provider.close()