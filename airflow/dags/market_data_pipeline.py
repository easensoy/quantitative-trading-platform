from datetime import datetime, timedelta
from typing import Dict, List, Any
import pandas as pd
import numpy as np

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.providers.mysql.operators.mysql import MySqlOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook
from airflow.models import Variable
from airflow.utils.dates import days_ago

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from src.data.extractors import MarketDataExtractor, FundamentalDataExtractor
from src.data.transformers import DataCleaner, DataValidator
from src.data.loaders import DatabaseLoader


default_args = {
    'owner': 'trading-team',
    'depends_on_past': False,
    'start_date': days_ago(1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2)
}

dag = DAG(
    'market_data_pipeline',
    default_args=default_args,
    description='Extract, transform, and load market data',
    schedule_interval='@hourly',
    catchup=False,
    max_active_runs=1,
    tags=['market-data', 'etl']
)


def extract_market_data(**context):
    """Extract market data from various sources"""
    extractor = MarketDataExtractor()
    execution_date = context['execution_date']
    
    symbols = Variable.get("market_data_symbols", default_var="AAPL,GOOGL,MSFT,TSLA").split(",")
    
    market_data = {}
    for symbol in symbols:
        try:
            data = extractor.extract_realtime_data(symbol)
            market_data[symbol] = data
        except Exception as e:
            print(f"Failed to extract data for {symbol}: {e}")
    
    return market_data


def extract_fundamental_data(**context):
    """Extract fundamental data"""
    extractor = FundamentalDataExtractor()
    execution_date = context['execution_date']
    
    symbols = Variable.get("fundamental_data_symbols", default_var="AAPL,GOOGL,MSFT,TSLA").split(",")
    
    fundamental_data = {}
    for symbol in symbols:
        try:
            data = extractor.extract_financial_statements(symbol)
            fundamental_data[symbol] = data
        except Exception as e:
            print(f"Failed to extract fundamental data for {symbol}: {e}")
    
    return fundamental_data


def validate_and_clean_data(**context):
    """Validate and clean extracted data"""
    task_instance = context['task_instance']
    
    market_data = task_instance.xcom_pull(task_ids='extract_market_data')
    fundamental_data = task_instance.xcom_pull(task_ids='extract_fundamental_data')
    
    cleaner = DataCleaner()
    validator = DataValidator()
    
    cleaned_market_data = {}
    cleaned_fundamental_data = {}
    
    for symbol, data in market_data.items():
        try:
            cleaned_data = cleaner.clean_market_data(data)
            if validator.validate_market_data(cleaned_data):
                cleaned_market_data[symbol] = cleaned_data
            else:
                print(f"Validation failed for market data: {symbol}")
        except Exception as e:
            print(f"Failed to clean market data for {symbol}: {e}")
    
    for symbol, data in fundamental_data.items():
        try:
            cleaned_data = cleaner.clean_fundamental_data(data)
            if validator.validate_fundamental_data(cleaned_data):
                cleaned_fundamental_data[symbol] = cleaned_data
            else:
                print(f"Validation failed for fundamental data: {symbol}")
        except Exception as e:
            print(f"Failed to clean fundamental data for {symbol}: {e}")
    
    return {
        'market_data': cleaned_market_data,
        'fundamental_data': cleaned_fundamental_data
    }


def transform_market_data(**context):
    """Transform market data for analytics"""
    task_instance = context['task_instance']
    cleaned_data = task_instance.xcom_pull(task_ids='validate_and_clean_data')
    
    market_data = cleaned_data['market_data']
    
    transformed_data = {}
    
    for symbol, data in market_data.items():
        try:
            df = pd.DataFrame(data)
            
            df['returns'] = df['close'].pct_change()
            df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
            df['volatility'] = df['returns'].rolling(window=20).std()
            df['sma_20'] = df['close'].rolling(window=20).mean()
            df['sma_50'] = df['close'].rolling(window=50).mean()
            df['rsi'] = calculate_rsi(df['close'])
            df['bollinger_upper'], df['bollinger_lower'] = calculate_bollinger_bands(df['close'])
            
            transformed_data[symbol] = df.to_dict('records')
            
        except Exception as e:
            print(f"Failed to transform market data for {symbol}: {e}")
    
    return transformed_data


def calculate_rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    """Calculate Relative Strength Index"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.rolling(window=window).mean()
    avg_loss = loss.rolling(window=window).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_bollinger_bands(prices: pd.Series, window: int = 20, num_std: float = 2) -> tuple:
    """Calculate Bollinger Bands"""
    sma = prices.rolling(window=window).mean()
    std = prices.rolling(window=window).std()
    
    upper_band = sma + (std * num_std)
    lower_band = sma - (std * num_std)
    
    return upper_band, lower_band


def load_to_mysql(**context):
    """Load data to MySQL database"""
    task_instance = context['task_instance']
    
    cleaned_data = task_instance.xcom_pull(task_ids='validate_and_clean_data')
    transformed_data = task_instance.xcom_pull(task_ids='transform_market_data')
    
    loader = DatabaseLoader('mysql')
    
    try:
        loader.load_market_data(cleaned_data['market_data'])
        loader.load_fundamental_data(cleaned_data['fundamental_data'])
        loader.load_analytics_data(transformed_data)
        
        print("Successfully loaded data to MySQL")
        
    except Exception as e:
        print(f"Failed to load data to MySQL: {e}")
        raise


def load_to_clickhouse(**context):
    """Load data to ClickHouse for analytics"""
    task_instance = context['task_instance']
    
    transformed_data = task_instance.xcom_pull(task_ids='transform_market_data')
    
    loader = DatabaseLoader('clickhouse')
    
    try:
        loader.load_analytics_data(transformed_data)
        print("Successfully loaded data to ClickHouse")
        
    except Exception as e:
        print(f"Failed to load data to ClickHouse: {e}")
        raise


def data_quality_check(**context):
    """Perform data quality checks"""
    mysql_hook = MySqlHook(mysql_conn_id='mysql_default')
    
    execution_date = context['execution_date']
    
    quality_checks = [
        {
            'name': 'market_data_count',
            'sql': f"""
                SELECT COUNT(*) as count 
                FROM market_data 
                WHERE DATE(timestamp) = DATE('{execution_date}')
            """,
            'min_threshold': 100
        },
        {
            'name': 'price_data_validity',
            'sql': f"""
                SELECT COUNT(*) as count 
                FROM market_data 
                WHERE DATE(timestamp) = DATE('{execution_date}')
                AND (close <= 0 OR high < low OR open <= 0)
            """,
            'max_threshold': 0
        },
        {
            'name': 'data_freshness',
            'sql': f"""
                SELECT TIMESTAMPDIFF(MINUTE, MAX(timestamp), NOW()) as minutes_since_last_update
                FROM market_data
            """,
            'max_threshold': 120
        }
    ]
    
    failed_checks = []
    
    for check in quality_checks:
        try:
            result = mysql_hook.get_first(check['sql'])
            value = result[0] if result else 0
            
            if 'min_threshold' in check and value < check['min_threshold']:
                failed_checks.append(f"{check['name']}: {value} < {check['min_threshold']}")
            elif 'max_threshold' in check and value > check['max_threshold']:
                failed_checks.append(f"{check['name']}: {value} > {check['max_threshold']}")
                
        except Exception as e:
            failed_checks.append(f"{check['name']}: Error executing check - {e}")
    
    if failed_checks:
        error_message = "Data quality checks failed:\n" + "\n".join(failed_checks)
        raise Exception(error_message)
    
    print("All data quality checks passed")


def send_completion_notification(**context):
    """Send notification upon successful completion"""
    execution_date = context['execution_date']
    
    print(f"Market data pipeline completed successfully for {execution_date}")


extract_market_data_task = PythonOperator(
    task_id='extract_market_data',
    python_callable=extract_market_data,
    dag=dag
)

extract_fundamental_data_task = PythonOperator(
    task_id='extract_fundamental_data',
    python_callable=extract_fundamental_data,
    dag=dag
)

validate_and_clean_task = PythonOperator(
    task_id='validate_and_clean_data',
    python_callable=validate_and_clean_data,
    dag=dag
)

transform_task = PythonOperator(
    task_id='transform_market_data',
    python_callable=transform_market_data,
    dag=dag
)

load_mysql_task = PythonOperator(
    task_id='load_to_mysql',
    python_callable=load_to_mysql,
    dag=dag
)

load_clickhouse_task = PythonOperator(
    task_id='load_to_clickhouse',
    python_callable=load_to_clickhouse,
    dag=dag
)

quality_check_task = PythonOperator(
    task_id='data_quality_check',
    python_callable=data_quality_check,
    dag=dag
)

notification_task = PythonOperator(
    task_id='send_completion_notification',
    python_callable=send_completion_notification,
    trigger_rule='all_success',
    dag=dag
)

[extract_market_data_task, extract_fundamental_data_task] >> validate_and_clean_task
validate_and_clean_task >> transform_task
transform_task >> [load_mysql_task, load_clickhouse_task]
[load_mysql_task, load_clickhouse_task] >> quality_check_task
quality_check_task >> notification_task