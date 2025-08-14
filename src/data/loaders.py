from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import numpy as np
import asyncio
import mysql.connector
from mysql.connector import Error
import clickhouse_driver
import redis
import json

from src.core.config import get_config
from src.core.exceptions import DatabaseError


class DataLoader(ABC):
    @abstractmethod
    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        pass

    @abstractmethod
    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        pass


class MySQLLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config().database
        self.connection = None
        self.connection_pool = None

    async def connect(self) -> None:
        try:
            self.connection = mysql.connector.connect(
                host=self.config.mysql_host,
                port=self.config.mysql_port,
                user=self.config.mysql_user,
                password=self.config.mysql_password,
                database=self.config.mysql_database,
                autocommit=True,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci'
            )
        except Error as e:
            raise DatabaseError(f"Failed to connect to MySQL: {e}")

    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        if not self.connection or not self.connection.is_connected():
            await self.connect()

        try:
            if isinstance(data, pd.DataFrame):
                return await self._load_dataframe(data, table_name, **kwargs)
            elif isinstance(data, list):
                return await self._load_list(data, table_name, **kwargs)
            elif isinstance(data, dict):
                return await self._load_dict(data, table_name, **kwargs)
            else:
                raise DatabaseError(f"Unsupported data type: {type(data)}")
        except Error as e:
            raise DatabaseError(f"Failed to load data to MySQL: {e}")

    async def _load_dataframe(self, df: pd.DataFrame, table_name: str, **kwargs) -> bool:
        if df.empty:
            return True

        mode = kwargs.get('mode', 'replace')
        batch_size = kwargs.get('batch_size', 1000)

        cursor = self.connection.cursor()

        try:
            if mode == 'replace':
                cursor.execute(f"TRUNCATE TABLE {table_name}")

            columns = list(df.columns)
            placeholders = ', '.join(['%s'] * len(columns))
            query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

            if mode == 'update':
                update_clause = ', '.join([f"{col} = VALUES({col})" for col in columns])
                query += f" ON DUPLICATE KEY UPDATE {update_clause}"

            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                values = [tuple(row) for row in batch.values]
                cursor.executemany(query, values)

            self.connection.commit()
            return True

        except Error as e:
            self.connection.rollback()
            raise DatabaseError(f"Failed to load DataFrame: {e}")
        finally:
            cursor.close()

    async def _load_list(self, data: List[Dict], table_name: str, **kwargs) -> bool:
        if not data:
            return True

        df = pd.DataFrame(data)
        return await self._load_dataframe(df, table_name, **kwargs)

    async def _load_dict(self, data: Dict, table_name: str, **kwargs) -> bool:
        df = pd.DataFrame([data])
        return await self._load_dataframe(df, table_name, **kwargs)

    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        if not self.connection or not self.connection.is_connected():
            await self.connect()

        cursor = self.connection.cursor()

        try:
            columns_def = []
            for column_name, column_type in schema.items():
                columns_def.append(f"{column_name} {column_type}")

            create_query = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns_def)},
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """

            cursor.execute(create_query)
            self.connection.commit()
            return True

        except Error as e:
            raise DatabaseError(f"Failed to create table {table_name}: {e}")
        finally:
            cursor.close()

    async def close(self) -> None:
        if self.connection and self.connection.is_connected():
            self.connection.close()


class ClickHouseLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config().database
        self.client = None

    async def connect(self) -> None:
        try:
            self.client = clickhouse_driver.Client(
                host=self.config.clickhouse_host,
                port=self.config.clickhouse_port,
                user=self.config.clickhouse_user,
                password=self.config.clickhouse_password,
                database=self.config.clickhouse_database
            )
        except Exception as e:
            raise DatabaseError(f"Failed to connect to ClickHouse: {e}")

    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        if not self.client:
            await self.connect()

        try:
            if isinstance(data, pd.DataFrame):
                return await self._load_dataframe(data, table_name, **kwargs)
            elif isinstance(data, list):
                return await self._load_list(data, table_name, **kwargs)
            elif isinstance(data, dict):
                return await self._load_dict(data, table_name, **kwargs)
            else:
                raise DatabaseError(f"Unsupported data type: {type(data)}")
        except Exception as e:
            raise DatabaseError(f"Failed to load data to ClickHouse: {e}")

    async def _load_dataframe(self, df: pd.DataFrame, table_name: str, **kwargs) -> bool:
        if df.empty:
            return True

        try:
            df_copy = df.copy()
            df_copy = df_copy.replace([np.inf, -np.inf], np.nan)
            df_copy = df_copy.fillna(0)

            data_tuples = [tuple(row) for row in df_copy.values]
            columns = list(df_copy.columns)

            query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES"

            self.client.execute(query, data_tuples)
            return True

        except Exception as e:
            raise DatabaseError(f"Failed to load DataFrame to ClickHouse: {e}")

    async def _load_list(self, data: List[Dict], table_name: str, **kwargs) -> bool:
        if not data:
            return True

        df = pd.DataFrame(data)
        return await self._load_dataframe(df, table_name, **kwargs)

    async def _load_dict(self, data: Dict, table_name: str, **kwargs) -> bool:
        df = pd.DataFrame([data])
        return await self._load_dataframe(df, table_name, **kwargs)

    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        if not self.client:
            await self.connect()

        try:
            columns_def = []
            for column_name, column_type in schema.items():
                columns_def.append(f"{column_name} {column_type}")

            create_query = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns_def)},
                    created_at DateTime DEFAULT now()
                ) ENGINE = MergeTree()
                ORDER BY created_at
            """

            self.client.execute(create_query)
            return True

        except Exception as e:
            raise DatabaseError(f"Failed to create ClickHouse table {table_name}: {e}")

    async def close(self) -> None:
        if self.client:
            self.client.disconnect()


class RedisLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config().database
        self.client = None

    async def connect(self) -> None:
        try:
            self.client = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                password=self.config.redis_password,
                decode_responses=True
            )
            self.client.ping()
        except Exception as e:
            raise DatabaseError(f"Failed to connect to Redis: {e}")

    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        if not self.client:
            await self.connect()

        try:
            ttl = kwargs.get('ttl', 3600)  # 1 hour default TTL

            if isinstance(data, pd.DataFrame):
                return await self._load_dataframe(data, table_name, ttl)
            elif isinstance(data, list):
                return await self._load_list(data, table_name, ttl)
            elif isinstance(data, dict):
                return await self._load_dict(data, table_name, ttl)
            else:
                raise DatabaseError(f"Unsupported data type: {type(data)}")
        except Exception as e:
            raise DatabaseError(f"Failed to load data to Redis: {e}")

    async def _load_dataframe(self, df: pd.DataFrame, key_prefix: str, ttl: int) -> bool:
        try:
            for index, row in df.iterrows():
                key = f"{key_prefix}:{index}"
                value = json.dumps(row.to_dict(), default=str)
                self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to load DataFrame to Redis: {e}")

    async def _load_list(self, data: List[Dict], key_prefix: str, ttl: int) -> bool:
        try:
            for i, item in enumerate(data):
                key = f"{key_prefix}:{i}"
                value = json.dumps(item, default=str)
                self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to load list to Redis: {e}")

    async def _load_dict(self, data: Dict, key: str, ttl: int) -> bool:
        try:
            value = json.dumps(data, default=str)
            self.client.setex(key, ttl, value)
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to load dict to Redis: {e}")

    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        # Redis doesn't have tables, so this is a no-op
        return True

    async def close(self) -> None:
        if self.client:
            self.client.close()


class DatabaseLoader:
    def __init__(self, database_type: str = 'mysql'):
        self.database_type = database_type
        self.mysql_loader = MySQLLoader()
        self.clickhouse_loader = ClickHouseLoader()
        self.redis_loader = RedisLoader()

    async def load_market_data(self, data: Dict[str, List[Dict]]) -> bool:
        success = True

        # Load to MySQL for operational data
        await self._ensure_market_data_tables()

        for symbol, symbol_data in data.items():
            if symbol_data:
                try:
                    df = pd.DataFrame(symbol_data)
                    df['symbol'] = symbol
                    success &= await self.mysql_loader.load(df, 'market_data', mode='update')
                except Exception as e:
                    print(f"Failed to load market data for {symbol}: {e}")
                    success = False

        # Load to Redis for real-time access
        for symbol, symbol_data in data.items():
            if symbol_data:
                try:
                    latest_data = symbol_data[-1]  # Most recent data point
                    key = f"latest_market_data:{symbol}"
                    success &= await self.redis_loader.load(latest_data, key, ttl=300)
                except Exception as e:
                    print(f"Failed to cache market data for {symbol}: {e}")

        return success

    async def load_fundamental_data(self, data: Dict[str, Dict]) -> bool:
        success = True

        await self._ensure_fundamental_data_tables()

        for symbol, symbol_data in data.items():
            if not symbol_data or symbol_data.get('source') == 'mock':
                continue

            try:
                for statement_type, statements in symbol_data.items():
                    if statement_type == 'source':
                        continue

                    if isinstance(statements, list):
                        for statement in statements:
                            statement['symbol'] = symbol
                            statement['statement_type'] = statement_type

                        df = pd.DataFrame(statements)
                        success &= await self.mysql_loader.load(df, 'fundamental_data', mode='update')

            except Exception as e:
                print(f"Failed to load fundamental data for {symbol}: {e}")
                success = False

        return success

    async def load_analytics_data(self, data: Dict[str, List[Dict]]) -> bool:
        success = True

        # Load to ClickHouse for analytics
        await self._ensure_analytics_tables()

        for symbol, symbol_data in data.items():
            if symbol_data:
                try:
                    df = pd.DataFrame(symbol_data)
                    df['symbol'] = symbol
                    success &= await self.clickhouse_loader.load(df, 'market_analytics')
                except Exception as e:
                    print(f"Failed to load analytics data for {symbol}: {e}")
                    success = False

        return success

    async def _ensure_market_data_tables(self) -> None:
        market_data_schema = {
            'id': 'BIGINT AUTO_INCREMENT PRIMARY KEY',
            'symbol': 'VARCHAR(20) NOT NULL',
            'timestamp': 'DATETIME NOT NULL',
            'open': 'DECIMAL(15,4)',
            'high': 'DECIMAL(15,4)',
            'low': 'DECIMAL(15,4)',
            'close': 'DECIMAL(15,4)',
            'volume': 'BIGINT',
            'source': 'VARCHAR(50)',
            'INDEX idx_symbol_timestamp': '(symbol, timestamp)',
            'UNIQUE KEY unique_symbol_timestamp': '(symbol, timestamp)'
        }

        await self.mysql_loader.create_table('market_data', market_data_schema)

    async def _ensure_fundamental_data_tables(self) -> None:
        fundamental_data_schema = {
            'id': 'BIGINT AUTO_INCREMENT PRIMARY KEY',
            'symbol': 'VARCHAR(20) NOT NULL',
            'statement_type': 'VARCHAR(50) NOT NULL',
            'fiscal_date_ending': 'DATE',
            'total_revenue': 'BIGINT',
            'gross_profit': 'BIGINT',
            'operating_income': 'BIGINT',
            'net_income': 'BIGINT',
            'total_assets': 'BIGINT',
            'total_liabilities': 'BIGINT',
            'total_shareholder_equity': 'BIGINT',
            'operating_cashflow': 'BIGINT',
            'capital_expenditures': 'BIGINT',
            'free_cash_flow': 'BIGINT',
            'INDEX idx_symbol_date': '(symbol, fiscal_date_ending)',
            'UNIQUE KEY unique_symbol_type_date': '(symbol, statement_type, fiscal_date_ending)'
        }

        await self.mysql_loader.create_table('fundamental_data', fundamental_data_schema)

    async def _ensure_analytics_tables(self) -> None:
        analytics_schema = {
            'symbol': 'String',
            'timestamp': 'DateTime',
            'close': 'Float64',
            'returns': 'Float64',
            'log_returns': 'Float64',
            'volatility': 'Float64',
            'sma_20': 'Float64',
            'sma_50': 'Float64',
            'ema_20': 'Float64',
            'rsi': 'Float64',
            'bb_upper': 'Float64',
            'bb_lower': 'Float64',
            'bb_position': 'Float64',
            'macd': 'Float64',
            'macd_signal': 'Float64',
            'macd_histogram': 'Float64',
            'atr': 'Float64',
            'volume': 'UInt64',
            'volume_ratio': 'Float64'
        }

        await self.clickhouse_loader.create_table('market_analytics', analytics_schema)

    async def close_all_connections(self) -> None:
        await asyncio.gather(
            self.mysql_loader.close(),
            self.clickhouse_loader.close(),
            self.redis_loader.close(),
            return_exceptions=True
        )


class StreamingDataLoader:
    def __init__(self):
        self.mysql_loader = MySQLLoader()
        self.redis_loader = RedisLoader()
        self.buffer = {}
        self.buffer_size = 1000
        self.flush_interval = 30  # seconds

    async def stream_market_data(self, symbol: str, data: Dict) -> None:
        # Add to buffer
        if symbol not in self.buffer:
            self.buffer[symbol] = []
        
        self.buffer[symbol].append(data)

        # Cache latest data in Redis immediately
        await self.redis_loader.load(data, f"realtime:{symbol}", ttl=60)

        # Flush buffer if it's full
        if len(self.buffer[symbol]) >= self.buffer_size:
            await self._flush_buffer(symbol)

    async def _flush_buffer(self, symbol: str) -> None:
        if symbol in self.buffer and self.buffer[symbol]:
            try:
                df = pd.DataFrame(self.buffer[symbol])
                df['symbol'] = symbol
                await self.mysql_loader.load(df, 'realtime_market_data', mode='append')
                self.buffer[symbol] = []
            except Exception as e:
                print(f"Failed to flush buffer for {symbol}: {e}")

    async def start_periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval)
            for symbol in list(self.buffer.keys()):
                await self._flush_buffer(symbol)


class DataWarehouseLoader:
    def __init__(self):
        self.mysql_loader = MySQLLoader()
        self.clickhouse_loader = ClickHouseLoader()

    async def load_historical_data(
        self,
        data: pd.DataFrame,
        partition_column: str = 'date',
        partition_size: str = 'monthly'
    ) -> bool:
        if data.empty:
            return True

        data[partition_column] = pd.to_datetime(data[partition_column])

        if partition_size == 'monthly':
            partition_groups = data.groupby([data[partition_column].dt.year, data[partition_column].dt.month])
        elif partition_size == 'daily':
            partition_groups = data.groupby(data[partition_column].dt.date)
        else:
            partition_groups = [(None, data)]

        success = True

        for partition_key, partition_data in partition_groups:
            try:
                if partition_size == 'monthly':
                    table_suffix = f"{partition_key[0]}_{partition_key[1]:02d}"
                elif partition_size == 'daily':
                    table_suffix = partition_key.strftime('%Y_%m_%d')
                else:
                    table_suffix = ""

                table_name = f"historical_market_data_{table_suffix}" if table_suffix else "historical_market_data"

                success &= await self.clickhouse_loader.load(partition_data, table_name)

            except Exception as e:
                print(f"Failed to load partition {partition_key}: {e}")
                success = False

        return success

    async def create_aggregated_views(self) -> bool:
        aggregation_queries = [
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS daily_ohlcv AS
            SELECT
                symbol,
                toDate(timestamp) as date,
                argMin(close, timestamp) as open,
                max(close) as high,
                min(close) as low,
                argMax(close, timestamp) as close,
                sum(volume) as volume
            FROM market_analytics
            GROUP BY symbol, date
            """,
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_returns AS
            SELECT
                symbol,
                toStartOfHour(timestamp) as hour,
                avg(returns) as avg_return,
                stddevPop(returns) as volatility,
                count() as count
            FROM market_analytics
            GROUP BY symbol, hour
            """
        ]

        success = True
        for query in aggregation_queries:
            try:
                await self.clickhouse_loader.client.execute(query)
            except Exception as e:
                print(f"Failed to create aggregated view: {e}")
                success = False

        return success


def create_data_loader(loader_type: str = "mysql") -> DataLoader:
    if loader_type == "mysql":
        return MySQLDataLoader()
    elif loader_type == "clickhouse":
        return ClickHouseDataLoader()
    elif loader_type == "redis":
        return RedisDataLoader()
    elif loader_type == "parquet":
        return ParquetDataLoader()
    return MySQLDataLoader()