from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import numpy as np
import asyncio
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from snowflake.sqlalchemy import URL
from sqlalchemy import create_engine
import json
from datetime import datetime

from src.core.config import get_config
from src.core.exceptions import DatabaseError
from src.data.loaders import DataLoader


class SnowflakeLoader(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config().database
        self.connection = None
        self.engine = None

    async def connect(self) -> None:
        try:
            self.connection = snowflake.connector.connect(
                user=self.config.snowflake_user,
                password=self.config.snowflake_password,
                account=self.config.snowflake_account,
                warehouse=self.config.snowflake_warehouse,
                database=self.config.snowflake_database,
                schema=self.config.snowflake_schema,
                role=self.config.snowflake_role
            )
            
            # Create SQLAlchemy engine for pandas integration
            engine_url = URL(
                user=self.config.snowflake_user,
                password=self.config.snowflake_password,
                account=self.config.snowflake_account,
                warehouse=self.config.snowflake_warehouse,
                database=self.config.snowflake_database,
                schema=self.config.snowflake_schema,
                role=self.config.snowflake_role
            )
            self.engine = create_engine(engine_url)
            
        except Exception as e:
            raise DatabaseError(f"Failed to connect to Snowflake: {e}")

    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        if not self.connection:
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
            raise DatabaseError(f"Failed to load data to Snowflake: {e}")

    async def _load_dataframe(self, df: pd.DataFrame, table_name: str, **kwargs) -> bool:
        if df.empty:
            return True

        try:
            mode = kwargs.get('mode', 'append')  # append, replace, fail
            chunk_size = kwargs.get('chunk_size', 10000)
            auto_create_table = kwargs.get('auto_create_table', True)
            
            # Clean data for Snowflake
            df_clean = df.copy()
            df_clean = df_clean.replace([np.inf, -np.inf], np.nan)
            
            # Convert datetime columns
            for col in df_clean.columns:
                if df_clean[col].dtype == 'datetime64[ns]':
                    df_clean[col] = pd.to_datetime(df_clean[col])

            success, nchunks, nrows, _ = write_pandas(
                conn=self.connection,
                df=df_clean,
                table_name=table_name,
                auto_create_table=auto_create_table,
                overwrite=(mode == 'replace'),
                chunk_size=chunk_size
            )

            return success

        except Exception as e:
            raise DatabaseError(f"Failed to load DataFrame to Snowflake: {e}")

    async def _load_list(self, data: List[Dict], table_name: str, **kwargs) -> bool:
        if not data:
            return True

        df = pd.DataFrame(data)
        return await self._load_dataframe(df, table_name, **kwargs)

    async def _load_dict(self, data: Dict, table_name: str, **kwargs) -> bool:
        df = pd.DataFrame([data])
        return await self._load_dataframe(df, table_name, **kwargs)

    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        if not self.connection:
            await self.connect()

        cursor = self.connection.cursor()

        try:
            columns_def = []
            for column_name, column_type in schema.items():
                columns_def.append(f"{column_name} {column_type}")

            create_query = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns_def)},
                    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """

            cursor.execute(create_query)
            return True

        except Exception as e:
            raise DatabaseError(f"Failed to create Snowflake table {table_name}: {e}")
        finally:
            cursor.close()

    async def execute_query(self, query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        """Execute a query and return results as DataFrame"""
        if not self.engine:
            await self.connect()

        try:
            return pd.read_sql(query, self.engine, params=params)
        except Exception as e:
            raise DatabaseError(f"Failed to execute query: {e}")

    async def close(self) -> None:
        if self.connection:
            self.connection.close()
        if self.engine:
            self.engine.dispose()


class SnowflakeWarehouse:
    """Data warehouse operations for financial market data"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.loader = SnowflakeLoader(config)

    async def create_financial_schema(self) -> bool:
        """Create optimized schema for financial data"""
        tables = {
            'market_data_raw': {
                'SYMBOL': 'VARCHAR(20)',
                'TIMESTAMP': 'TIMESTAMP_NTZ',
                'OPEN': 'NUMBER(15,4)',
                'HIGH': 'NUMBER(15,4)',
                'LOW': 'NUMBER(15,4)',
                'CLOSE': 'NUMBER(15,4)',
                'VOLUME': 'NUMBER(20,0)',
                'SOURCE': 'VARCHAR(50)'
            },
            'bloomberg_data': {
                'SYMBOL': 'VARCHAR(20)',
                'FIELD': 'VARCHAR(50)',
                'VALUE': 'VARIANT',
                'TIMESTAMP': 'TIMESTAMP_NTZ',
                'SOURCE': 'VARCHAR(20) DEFAULT \'BLOOMBERG\''
            },
            'refinitiv_data': {
                'SYMBOL': 'VARCHAR(20)',
                'RIC': 'VARCHAR(50)',
                'FIELD': 'VARCHAR(50)',
                'VALUE': 'VARIANT',
                'TIMESTAMP': 'TIMESTAMP_NTZ',
                'SOURCE': 'VARCHAR(20) DEFAULT \'REFINITIV\''
            },
            'factset_data': {
                'SYMBOL': 'VARCHAR(20)',
                'FSYM_ID': 'VARCHAR(50)',
                'METRIC': 'VARCHAR(100)',
                'VALUE': 'VARIANT',
                'DATE': 'DATE',
                'PERIOD_TYPE': 'VARCHAR(20)',
                'SOURCE': 'VARCHAR(20) DEFAULT \'FACTSET\''
            },
            'market_analytics': {
                'SYMBOL': 'VARCHAR(20)',
                'TIMESTAMP': 'TIMESTAMP_NTZ',
                'RETURNS': 'NUMBER(10,6)',
                'VOLATILITY': 'NUMBER(10,6)',
                'RSI': 'NUMBER(5,2)',
                'MACD': 'NUMBER(10,6)',
                'BOLLINGER_UPPER': 'NUMBER(15,4)',
                'BOLLINGER_LOWER': 'NUMBER(15,4)',
                'VOLUME_RATIO': 'NUMBER(8,4)'
            }
        }

        success = True
        for table_name, schema in tables.items():
            try:
                await self.loader.create_table(table_name, schema)
            except Exception as e:
                print(f"Failed to create table {table_name}: {e}")
                success = False

        return success

    async def create_time_series_streams(self) -> bool:
        """Create Snowflake streams for real-time data processing"""
        streams = [
            """
            CREATE OR REPLACE STREAM market_data_stream 
            ON TABLE market_data_raw 
            APPEND_ONLY = TRUE
            """,
            """
            CREATE OR REPLACE STREAM bloomberg_stream 
            ON TABLE bloomberg_data 
            APPEND_ONLY = TRUE
            """,
            """
            CREATE OR REPLACE STREAM refinitiv_stream 
            ON TABLE refinitiv_data 
            APPEND_ONLY = TRUE
            """
        ]

        cursor = self.loader.connection.cursor()
        success = True

        for stream_sql in streams:
            try:
                cursor.execute(stream_sql)
            except Exception as e:
                print(f"Failed to create stream: {e}")
                success = False

        cursor.close()
        return success

    async def create_data_pipelines(self) -> bool:
        """Create Snowflake tasks for automated data processing"""
        tasks = [
            """
            CREATE OR REPLACE TASK process_market_data_task
            WAREHOUSE = 'QUANTCORE_WH'
            SCHEDULE = '1 MINUTE'
            AS
            INSERT INTO market_analytics (
                symbol, timestamp, returns, volatility, rsi, 
                macd, bollinger_upper, bollinger_lower, volume_ratio
            )
            SELECT 
                symbol,
                timestamp,
                (close - LAG(close) OVER (PARTITION BY symbol ORDER BY timestamp)) / LAG(close) OVER (PARTITION BY symbol ORDER BY timestamp) as returns,
                STDDEV(close) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as volatility,
                -- RSI calculation would go here
                NULL as rsi,
                -- MACD calculation would go here  
                NULL as macd,
                close + (2 * STDDEV(close) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)) as bollinger_upper,
                close - (2 * STDDEV(close) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)) as bollinger_lower,
                volume / AVG(volume) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as volume_ratio
            FROM market_data_stream
            WHERE METADATA$ACTION = 'INSERT'
            """,
            """
            CREATE OR REPLACE TASK aggregate_daily_data_task
            WAREHOUSE = 'QUANTCORE_WH'
            SCHEDULE = '0 0 * * *'  -- Daily at midnight
            AS
            CREATE OR REPLACE TABLE daily_market_summary AS
            SELECT 
                symbol,
                DATE(timestamp) as date,
                FIRST_VALUE(close) OVER (PARTITION BY symbol, DATE(timestamp) ORDER BY timestamp) as open,
                MAX(close) as high,
                MIN(close) as low,
                LAST_VALUE(close) OVER (PARTITION BY symbol, DATE(timestamp) ORDER BY timestamp) as close,
                SUM(volume) as total_volume,
                COUNT(*) as tick_count
            FROM market_data_raw
            WHERE DATE(timestamp) = CURRENT_DATE - 1
            GROUP BY symbol, DATE(timestamp)
            """
        ]

        cursor = self.loader.connection.cursor()
        success = True

        for task_sql in tasks:
            try:
                cursor.execute(task_sql)
            except Exception as e:
                print(f"Failed to create task: {e}")
                success = False

        # Start the tasks
        try:
            cursor.execute("ALTER TASK process_market_data_task RESUME")
            cursor.execute("ALTER TASK aggregate_daily_data_task RESUME")
        except Exception as e:
            print(f"Failed to start tasks: {e}")
            success = False

        cursor.close()
        return success

    async def load_market_data(self, data: pd.DataFrame) -> bool:
        """Load market data optimized for Snowflake"""
        # Add partition column for efficient querying
        data['load_date'] = pd.to_datetime(data['timestamp']).dt.date
        
        return await self.loader.load(
            data, 
            'market_data_raw',
            mode='append',
            chunk_size=50000,
            auto_create_table=True
        )

    async def close(self) -> None:
        await self.loader.close()


# Integration with existing loaders
def create_snowflake_loader() -> SnowflakeLoader:
    """Factory function to create Snowflake loader"""
    return SnowflakeLoader()


def create_snowflake_warehouse() -> SnowflakeWarehouse:
    """Factory function to create Snowflake data warehouse"""
    return SnowflakeWarehouse()