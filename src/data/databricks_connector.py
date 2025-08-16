from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
import pandas as pd
import numpy as np
import asyncio
import requests
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import os
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute, jobs
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, lag, stddev, avg, first, last, max as spark_max, min as spark_min
from pyspark.sql.window import Window
from delta import DeltaTable
from src.core.config import get_config
from src.core.exceptions import DatabaseError
from src.data.loaders import DataLoader
class DatabricksConnector(DataLoader):
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or get_config().databricks
        self.workspace_client = None
        self.sql_connection = None
        self.spark = None
    async def connect(self) -> None:
        try:
            self.workspace_client = WorkspaceClient(
                host=self.config.databricks_host,
                token=self.config.databricks_token
            )
            self.sql_connection = sql.connect(
                server_hostname=self.config.databricks_server_hostname,
                http_path=self.config.databricks_http_path,
                access_token=self.config.databricks_token
            )
            if self._is_databricks_environment():
                self.spark = SparkSession.builder \
                    .appName("QuantCore-MarketData") \
                    .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
                    .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
                    .getOrCreate()
        except Exception as e:
            raise DatabaseError(f"Failed to connect to Databricks: {e}")
    def _is_databricks_environment(self) -> bool:
        return 'DATABRICKS_RUNTIME_VERSION' in os.environ
    async def load(self, data: Any, table_name: str, **kwargs) -> bool:
        if not self.sql_connection:
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
            raise DatabaseError(f"Failed to load data to Databricks: {e}")
    async def _load_dataframe(self, df: pd.DataFrame, table_name: str, **kwargs) -> bool:
        if df.empty:
            return True
        try:
            mode = kwargs.get('mode', 'append')
            partition_cols = kwargs.get('partition_cols', [])
            if self.spark:
                spark_df = self.spark.createDataFrame(df)
                writer = spark_df.write.format("delta")
                if partition_cols:
                    writer = writer.partitionBy(*partition_cols)
                if mode == 'merge':
                    await self._merge_delta_table(spark_df, table_name, kwargs.get('merge_keys', []))
                else:
                    writer.mode(mode).saveAsTable(table_name)
            else:
                await self._sql_insert_dataframe(df, table_name, mode)
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to load DataFrame to Databricks: {e}")
    async def _merge_delta_table(self, spark_df: DataFrame, table_name: str, merge_keys: List[str]) -> None:
        if not merge_keys:
            raise DatabaseError("Merge keys must be specified for merge operation")
        try:
            delta_table = DeltaTable.forName(self.spark, table_name)
            merge_condition = " AND ".join([f"target.{key} = source.{key}" for key in merge_keys])
            delta_table.alias("target") \
                .merge(spark_df.alias("source"), merge_condition) \
                .whenMatchedUpdateAll() \
                .whenNotMatchedInsertAll() \
                .execute()
        except Exception:
            spark_df.write.format("delta").saveAsTable(table_name)
    async def _sql_insert_dataframe(self, df: pd.DataFrame, table_name: str, mode: str) -> None:
        cursor = self.sql_connection.cursor()
        try:
            columns = []
            for col_name, dtype in df.dtypes.items():
                if 'int' in str(dtype):
                    sql_type = 'BIGINT'
                elif 'float' in str(dtype):
                    sql_type = 'DOUBLE'
                elif 'datetime' in str(dtype):
                    sql_type = 'TIMESTAMP'
                else:
                    sql_type = 'STRING'
                columns.append(f"{col_name} {sql_type}")
            create_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns)}
                ) USING DELTA
            """
            cursor.execute(create_sql)
            if mode == 'overwrite':
                cursor.execute(f"DELETE FROM {table_name}")
            batch_size = 1000
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                values = []
                for _, row in batch.iterrows():
                    row_values = []
                    for val in row:
                        if pd.isna(val):
                            row_values.append('NULL')
                        elif isinstance(val, str):
                            row_values.append(f"'{val.replace(\"'\", \"''\")}'")
                        else:
                            row_values.append(str(val))
                    values.append(f"({', '.join(row_values)})")
                if values:
                    insert_sql = f"""
                        INSERT INTO {table_name} VALUES {', '.join(values)}
                    """
                    cursor.execute(insert_sql)
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
        if not self.sql_connection:
            await self.connect()
        cursor = self.sql_connection.cursor()
        try:
            columns_def = []
            for column_name, column_type in schema.items():
                columns_def.append(f"{column_name} {column_type}")
            create_query = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns_def)},
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
                ) USING DELTA
            """
            cursor.execute(create_query)
            return True
        except Exception as e:
            raise DatabaseError(f"Failed to create Databricks table {table_name}: {e}")
        finally:
            cursor.close()
    async def execute_query(self, query: str, **kwargs) -> pd.DataFrame:
        if not self.sql_connection:
            await self.connect()
        cursor = self.sql_connection.cursor()
        try:
            cursor.execute(query)
            results = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return pd.DataFrame(results, columns=columns)
        except Exception as e:
            raise DatabaseError(f"Failed to execute query: {e}")
        finally:
            cursor.close()
    async def close(self) -> None:
        if self.sql_connection:
            self.sql_connection.close()
        if self.spark:
            self.spark.stop()
class DatabricksMarketDataProcessor:
    def __init__(self, config: Optional[Dict] = None):
        self.connector = DatabricksConnector(config)
        self.config = config or get_config().databricks
    async def create_market_data_lakehouse(self) -> bool:
        bronze_tables = {
            'market_data_bronze': {
                'symbol': 'STRING',
                'timestamp': 'TIMESTAMP',
                'open': 'DOUBLE',
                'high': 'DOUBLE',
                'low': 'DOUBLE',
                'close': 'DOUBLE',
                'volume': 'BIGINT',
                'source': 'STRING',
                'ingestion_timestamp': 'TIMESTAMP'
            },
            'bloomberg_bronze': {
                'symbol': 'STRING',
                'field': 'STRING',
                'value': 'STRING',
                'timestamp': 'TIMESTAMP',
                'source': 'STRING DEFAULT "bloomberg"',
                'ingestion_timestamp': 'TIMESTAMP'
            },
            'refinitiv_bronze': {
                'symbol': 'STRING',
                'ric': 'STRING',
                'field': 'STRING',
                'value': 'STRING',
                'timestamp': 'TIMESTAMP',
                'source': 'STRING DEFAULT "refinitiv"',
                'ingestion_timestamp': 'TIMESTAMP'
            }
        }
        silver_tables = {
            'market_data_silver': {
                'symbol': 'STRING',
                'timestamp': 'TIMESTAMP',
                'open': 'DOUBLE',
                'high': 'DOUBLE',
                'low': 'DOUBLE',
                'close': 'DOUBLE',
                'volume': 'BIGINT',
                'adjusted_close': 'DOUBLE',
                'data_quality_score': 'DOUBLE',
                'source': 'STRING'
            }
        }
        gold_tables = {
            'market_analytics_gold': {
                'symbol': 'STRING',
                'date': 'DATE',
                'timestamp': 'TIMESTAMP',
                'open': 'DOUBLE',
                'high': 'DOUBLE',
                'low': 'DOUBLE',
                'close': 'DOUBLE',
                'volume': 'BIGINT',
                'returns': 'DOUBLE',
                'log_returns': 'DOUBLE',
                'volatility_20d': 'DOUBLE',
                'rsi_14': 'DOUBLE',
                'macd': 'DOUBLE',
                'macd_signal': 'DOUBLE',
                'bollinger_upper': 'DOUBLE',
                'bollinger_lower': 'DOUBLE',
                'volume_ratio': 'DOUBLE'
            }
        }
        success = True
        all_tables = {**bronze_tables, **silver_tables, **gold_tables}
        for table_name, schema in all_tables.items():
            try:
                await self.connector.create_table(table_name, schema)
            except Exception as e:
                print(f"Failed to create table {table_name}: {e}")
                success = False
        return success
    async def create_streaming_jobs(self) -> bool:
        if not self.connector.spark:
            print("Spark session not available for streaming jobs")
            return False
        try:
            bronze_stream = self.connector.spark \
                .readStream \
                .format("delta") \
                .table("market_data_bronze")
            silver_stream = bronze_stream \
                .filter(col("open") > 0) \
                .filter(col("high") >= col("low")) \
                .filter(col("volume") >= 0) \
                .withColumn("adjusted_close", col("close")) \
                .withColumn("data_quality_score", 
                           when((col("high") >= col("low")) & 
                                (col("open") > 0) & 
                                (col("close") > 0), 1.0).otherwise(0.5))
            silver_query = silver_stream \
                .writeStream \
                .format("delta") \
                .outputMode("append") \
                .option("checkpointLocation", "/tmp/silver_checkpoint") \
                .table("market_data_silver")
            silver_read_stream = self.connector.spark \
                .readStream \
                .format("delta") \
                .table("market_data_silver")
            symbol_window = Window.partitionBy("symbol").orderBy("timestamp")
            symbol_window_20 = symbol_window.rowsBetween(-19, 0)
            analytics_stream = silver_read_stream \
                .withColumn("returns", 
                           (col("close") - lag("close", 1).over(symbol_window)) / 
                           lag("close", 1).over(symbol_window)) \
                .withColumn("log_returns", 
                           log(col("close") / lag("close", 1).over(symbol_window))) \
                .withColumn("volatility_20d", 
                           stddev("returns").over(symbol_window_20)) \
                .withColumn("sma_20", 
                           avg("close").over(symbol_window_20)) \
                .withColumn("volume_ratio", 
                           col("volume") / avg("volume").over(symbol_window_20))
            gold_query = analytics_stream \
                .writeStream \
                .format("delta") \
                .outputMode("append") \
                .option("checkpointLocation", "/tmp/gold_checkpoint") \
                .table("market_analytics_gold")
            return True
        except Exception as e:
            print(f"Failed to create streaming jobs: {e}")
            return False
    async def create_ml_features(self) -> bool:
        if not self.connector.spark:
            return False
        try:
            market_data = self.connector.spark.table("market_analytics_gold")
            symbol_window = Window.partitionBy("symbol").orderBy("timestamp")
            symbol_window_5 = symbol_window.rowsBetween(-4, 0)
            symbol_window_20 = symbol_window.rowsBetween(-19, 0)
            symbol_window_50 = symbol_window.rowsBetween(-49, 0)
            ml_features = market_data \
                .withColumn("price_momentum_5", 
                           (col("close") - lag("close", 5).over(symbol_window)) / 
                           lag("close", 5).over(symbol_window)) \
                .withColumn("price_momentum_20", 
                           (col("close") - lag("close", 20).over(symbol_window)) / 
                           lag("close", 20).over(symbol_window)) \
                .withColumn("volume_momentum", 
                           col("volume") / avg("volume").over(symbol_window_20)) \
                .withColumn("volatility_regime", 
                           when(col("volatility_20d") > avg("volatility_20d").over(symbol_window_50), "high")
                           .otherwise("low")) \
                .withColumn("bollinger_position", 
                           (col("close") - col("bollinger_lower")) / 
                           (col("bollinger_upper") - col("bollinger_lower"))) \
                .withColumn("rsi_signal", 
                           when(col("rsi_14") > 70, "overbought")
                           .when(col("rsi_14") < 30, "oversold")
                           .otherwise("neutral"))
            ml_features.write \
                .format("delta") \
                .mode("overwrite") \
                .saveAsTable("ml_features_gold")
            return True
        except Exception as e:
            print(f"Failed to create ML features: {e}")
            return False
    async def run_batch_processing_job(self, symbols: List[str], start_date: str, end_date: str) -> bool:
        try:
            job_spec = {
                "name": "QuantCore Market Data Processing",
                "new_cluster": {
                    "spark_version": "11.3.x-scala2.12",
                    "node_type_id": "i3.xlarge",
                    "num_workers": 2,
                    "spark_conf": {
                        "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                        "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog"
                    }
                },
                "notebook_task": {
                    "notebook_path": "/Workspace/quantcore/market_data_processing",
                    "base_parameters": {
                        "symbols": ",".join(symbols),
                        "start_date": start_date,
                        "end_date": end_date
                    }
                },
                "timeout_seconds": 3600
            }
            job_response = self.connector.workspace_client.jobs.create(**job_spec)
            run_response = self.connector.workspace_client.jobs.run_now(job_id=job_response.job_id)
            print(f"Submitted job with run ID: {run_response.run_id}")
            return True
        except Exception as e:
            print(f"Failed to submit batch job: {e}")
            return False
    async def close(self) -> None:
        await self.connector.close()
def create_databricks_connector() -> DatabricksConnector:
    return DatabricksConnector()
def create_databricks_processor() -> DatabricksMarketDataProcessor:
    return DatabricksMarketDataProcessor()