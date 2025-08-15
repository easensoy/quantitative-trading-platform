from datetime import datetime, timedelta
from typing import Dict, List, Any
import pandas as pd
import numpy as np
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.operators.bash import BashOperator
from airflow.providers.mysql.operators.mysql import MySqlOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook
from airflow.models import Variable
from airflow.utils.dates import days_ago
from airflow.utils.trigger_rule import TriggerRule
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from src.data.bloomberg_connector import create_bloomberg_loader
from src.data.refinitiv_connector import create_refinitiv_loader
from src.data.factset_connector import create_factset_loader
from src.data.snowflake_connector import create_snowflake_warehouse
from src.data.databricks_connector import create_databricks_processor
from src.data.loaders import DatabaseLoader
default_args = {
    'owner': 'quantcore-team',
    'depends_on_past': False,
    'start_date': days_ago(1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=10),
    'execution_timeout': timedelta(hours=4)
}
dag = DAG(
    'multi_vendor_financial_data_pipeline',
    default_args=default_args,
    description='Orchestrate data ingestion from Bloomberg, Refinitiv, and FactSet',
    schedule_interval='0 6 * * 1-5',  
    catchup=False,
    max_active_runs=1,
    tags=['financial-data', 'etl', 'multi-vendor']
)
def check_vendor_availability(**context):
    execution_date = context['execution_date']
    vendor_status = {
        'bloomberg': False,
        'refinitiv': False, 
        'factset': False
    }
    try:
        bloomberg_loader = create_bloomberg_loader()
        vendor_status['bloomberg'] = True
        print("Bloomberg: AVAILABLE")
    except Exception as e:
        print(f"Bloomberg: UNAVAILABLE - {e}")
    try:
        refinitiv_loader = create_refinitiv_loader()
        vendor_status['refinitiv'] = True
        print("Refinitiv: AVAILABLE")
    except Exception as e:
        print(f"Refinitiv: UNAVAILABLE - {e}")
    try:
        factset_loader = create_factset_loader()
        vendor_status['factset'] = True
        print("FactSet: AVAILABLE")
    except Exception as e:
        print(f"FactSet: UNAVAILABLE - {e}")
    context['task_instance'].xcom_push(key='vendor_status', value=vendor_status)
    available_vendors = [vendor for vendor, available in vendor_status.items() if available]
    if not available_vendors:
        return 'skip_pipeline'
    else:
        return 'extract_symbols_universe'
def extract_symbols_universe(**context):
    symbols_config = {
        'sp500': Variable.get("sp500_symbols", default_var="AAPL,MSFT,GOOGL,AMZN,TSLA").split(","),
        'russell1000': Variable.get("russell1000_symbols", default_var="").split(",") if Variable.get("russell1000_symbols", "") else [],
        'custom_universe': Variable.get("custom_symbols", default_var="").split(",") if Variable.get("custom_symbols", "") else []
    }
    all_symbols = set()
    for symbol_list in symbols_config.values():
        all_symbols.update(symbol_list)
    final_symbols = list(all_symbols)
    context['task_instance'].xcom_push(key='symbols_universe', value=final_symbols)
    print(f"Trading universe: {len(final_symbols)} symbols")
    return final_symbols
def extract_bloomberg_data(**context):
    vendor_status = context['task_instance'].xcom_pull(key='vendor_status')
    symbols = context['task_instance'].xcom_pull(key='symbols_universe')
    if not vendor_status.get('bloomberg', False):
        print("Bloomberg not available, skipping...")
        return {}
    try:
        bloomberg_loader = create_bloomberg_loader()
        end_date = context['execution_date'].strftime('%Y%m%d')
        start_date = (context['execution_date'] - timedelta(days=30)).strftime('%Y%m%d')
        equity_data = await bloomberg_loader.provider.get_equity_data(symbols, start_date, end_date)
        fundamental_data = await bloomberg_loader.provider.get_fundamental_data(symbols)
        bloomberg_data = {
            'equity': equity_data.to_dict('records') if not equity_data.empty else [],
            'fundamentals': fundamental_data.to_dict('records') if not fundamental_data.empty else []
        }
        await bloomberg_loader.close()
        context['task_instance'].xcom_push(key='bloomberg_data', value=bloomberg_data)
        print(f"Bloomberg data extracted: {len(bloomberg_data['equity'])} equity records, {len(bloomberg_data['fundamentals'])} fundamental records")
        return bloomberg_data
    except Exception as e:
        print(f"Bloomberg extraction failed: {e}")
        return {}
def extract_refinitiv_data(**context):
    vendor_status = context['task_instance'].xcom_pull(key='vendor_status')
    symbols = context['task_instance'].xcom_pull(key='symbols_universe')
    if not vendor_status.get('refinitiv', False):
        print("Refinitiv not available, skipping...")
        return {}
    try:
        refinitiv_loader = create_refinitiv_loader()
        end_date = context['execution_date'].strftime('%Y-%m-%d')
        start_date = (context['execution_date'] - timedelta(days=30)).strftime('%Y-%m-%d')
        equity_data = await refinitiv_loader.provider.get_equity_data(symbols, start_date, end_date)
        company_data = await refinitiv_loader.provider.connector.get_company_data([f"{s}.O" for s in symbols])
        esg_data = await refinitiv_loader.provider.get_esg_data([f"{s}.O" for s in symbols])
        refinitiv_data = {
            'equity': equity_data.to_dict('records') if not equity_data.empty else [],
            'company': company_data.to_dict('records') if not company_data.empty else [],
            'esg': esg_data.to_dict('records') if not esg_data.empty else []
        }
        await refinitiv_loader.close()
        context['task_instance'].xcom_push(key='refinitiv_data', value=refinitiv_data)
        print(f"Refinitiv data extracted: {len(refinitiv_data['equity'])} equity records")
        return refinitiv_data
    except Exception as e:
        print(f"Refinitiv extraction failed: {e}")
        return {}
def extract_factset_data(**context):
    vendor_status = context['task_instance'].xcom_pull(key='vendor_status')
    symbols = context['task_instance'].xcom_pull(key='symbols_universe')
    if not vendor_status.get('factset', False):
        print("FactSet not available, skipping...")
        return {}
    try:
        factset_loader = create_factset_loader()
        end_date = context['execution_date'].strftime('%Y-%m-%d')
        start_date = (context['execution_date'] - timedelta(days=30)).strftime('%Y-%m-%d')
        fundamentals = await factset_loader.provider.get_equity_fundamentals(symbols, start_date, end_date)
        prices = await factset_loader.provider.get_equity_prices(symbols, start_date, end_date)
        estimates = await factset_loader.provider.get_analyst_estimates(symbols)
        ownership = await factset_loader.provider.get_institutional_ownership(symbols)
        factset_data = {
            'fundamentals': fundamentals.to_dict('records') if not fundamentals.empty else [],
            'prices': prices.to_dict('records') if not prices.empty else [],
            'estimates': estimates.to_dict('records') if not estimates.empty else [],
            'ownership': ownership.to_dict('records') if not ownership.empty else []
        }
        await factset_loader.close()
        context['task_instance'].xcom_push(key='factset_data', value=factset_data)
        print(f"FactSet data extracted: {len(factset_data['fundamentals'])} fundamental records")
        return factset_data
    except Exception as e:
        print(f"FactSet extraction failed: {e}")
        return {}
def merge_and_validate_data(**context):
    task_instance = context['task_instance']
    bloomberg_data = task_instance.xcom_pull(key='bloomberg_data') or {}
    refinitiv_data = task_instance.xcom_pull(key='refinitiv_data') or {}
    factset_data = task_instance.xcom_pull(key='factset_data') or {}
    all_equity_data = []
    for record in bloomberg_data.get('equity', []):
        record['source'] = 'bloomberg'
        all_equity_data.append(record)
    for record in refinitiv_data.get('equity', []):
        record['source'] = 'refinitiv'
        all_equity_data.append(record)
    for record in factset_data.get('prices', []):
        record['source'] = 'factset'
        all_equity_data.append(record)
    all_fundamental_data = []
    for record in bloomberg_data.get('fundamentals', []):
        record['source'] = 'bloomberg'
        all_fundamental_data.append(record)
    for record in factset_data.get('fundamentals', []):
        record['source'] = 'factset'
        all_fundamental_data.append(record)
    consolidated_data = {
        'equity_prices': all_equity_data,
        'fundamentals': all_fundamental_data,
        'esg': refinitiv_data.get('esg', []),
        'estimates': factset_data.get('estimates', []),
        'ownership': factset_data.get('ownership', [])
    }
    validation_results = {
        'equity_records': len(consolidated_data['equity_prices']),
        'fundamental_records': len(consolidated_data['fundamentals']),
        'esg_records': len(consolidated_data['esg']),
        'estimates_records': len(consolidated_data['estimates']),
        'ownership_records': len(consolidated_data['ownership'])
    }
    quality_issues = []
    if validation_results['equity_records'] == 0:
        quality_issues.append("No equity price data available")
    if validation_results['fundamental_records'] == 0:
        quality_issues.append("No fundamental data available")
    task_instance.xcom_push(key='consolidated_data', value=consolidated_data)
    task_instance.xcom_push(key='validation_results', value=validation_results)
    task_instance.xcom_push(key='quality_issues', value=quality_issues)
    print(f"Data consolidation complete: {validation_results}")
    if quality_issues:
        print(f"Quality issues: {quality_issues}")
    return consolidated_data
def load_to_snowflake(**context):
    task_instance = context['task_instance']
    consolidated_data = task_instance.xcom_pull(key='consolidated_data')
    try:
        snowflake_warehouse = create_snowflake_warehouse()
        await snowflake_warehouse.create_financial_schema()
        if consolidated_data['equity_prices']:
            equity_df = pd.DataFrame(consolidated_data['equity_prices'])
            await snowflake_warehouse.load_market_data(equity_df)
            print(f"Loaded {len(equity_df)} equity records to Snowflake")
        if consolidated_data['fundamentals']:
            fund_df = pd.DataFrame(consolidated_data['fundamentals'])
            await snowflake_warehouse.loader.load(fund_df, 'fundamental_data_raw')
            print(f"Loaded {len(fund_df)} fundamental records to Snowflake")
        if consolidated_data['esg']:
            esg_df = pd.DataFrame(consolidated_data['esg'])
            await snowflake_warehouse.loader.load(esg_df, 'esg_data_raw')
            print(f"Loaded {len(esg_df)} ESG records to Snowflake")
        await snowflake_warehouse.close()
        return True
    except Exception as e:
        print(f"Snowflake loading failed: {e}")
        raise
def process_with_databricks(**context):
    task_instance = context['task_instance']
    symbols = task_instance.xcom_pull(key='symbols_universe')
    try:
        databricks_processor = create_databricks_processor()
        await databricks_processor.create_market_data_lakehouse()
        await databricks_processor.create_ml_features()
        end_date = context['execution_date'].strftime('%Y-%m-%d')
        start_date = (context['execution_date'] - timedelta(days=30)).strftime('%Y-%m-%d')
        job_success = await databricks_processor.run_batch_processing_job(
            symbols, start_date, end_date
        )
        await databricks_processor.close()
        if job_success:
            print("Databricks processing completed successfully")
        else:
            print("Databricks processing had issues")
        return job_success
    except Exception as e:
        print(f"Databricks processing failed: {e}")
        raise
def generate_data_quality_report(**context):
    task_instance = context['task_instance']
    validation_results = task_instance.xcom_pull(key='validation_results')
    quality_issues = task_instance.xcom_pull(key='quality_issues')
    vendor_status = task_instance.xcom_pull(key='vendor_status')
    report = {
        'execution_date': context['execution_date'].strftime('%Y-%m-%d'),
        'vendor_availability': vendor_status,
        'data_volume': validation_results,
        'quality_issues': quality_issues,
        'overall_status': 'SUCCESS' if not quality_issues else 'WARNING'
    }
    task_instance.xcom_push(key='quality_report', value=report)
    print("=== DATA QUALITY REPORT ===")
    print(f"Execution Date: {report['execution_date']}")
    print(f"Vendor Status: {report['vendor_availability']}")
    print(f"Data Volume: {report['data_volume']}")
    print(f"Quality Issues: {len(report['quality_issues'])}")
    print(f"Overall Status: {report['overall_status']}")
    return report
def send_completion_notification(**context):
    task_instance = context['task_instance']
    quality_report = task_instance.xcom_pull(key='quality_report')
    print("=== PIPELINE COMPLETION NOTIFICATION ===")
    print(f"Multi-vendor data pipeline completed")
    print(f"Status: {quality_report['overall_status']}")
    print(f"Total records processed: {sum(quality_report['data_volume'].values())}")
    if quality_report['quality_issues']:
        print(f"⚠️  Quality issues detected:")
        for issue in quality_report['quality_issues']:
            print(f"   - {issue}")
    else:
        print("✅ No quality issues detected")
check_vendors_task = PythonOperator(
    task_id='check_vendor_availability',
    python_callable=check_vendor_availability,
    dag=dag
)
skip_pipeline_task = BashOperator(
    task_id='skip_pipeline',
    bash_command='echo "No vendors available, skipping pipeline"',
    dag=dag
)
extract_universe_task = PythonOperator(
    task_id='extract_symbols_universe',
    python_callable=extract_symbols_universe,
    dag=dag
)
extract_bloomberg_task = PythonOperator(
    task_id='extract_bloomberg_data',
    python_callable=extract_bloomberg_data,
    dag=dag
)
extract_refinitiv_task = PythonOperator(
    task_id='extract_refinitiv_data', 
    python_callable=extract_refinitiv_data,
    dag=dag
)
extract_factset_task = PythonOperator(
    task_id='extract_factset_data',
    python_callable=extract_factset_data,
    dag=dag
)
merge_data_task = PythonOperator(
    task_id='merge_and_validate_data',
    python_callable=merge_and_validate_data,
    trigger_rule=TriggerRule.NONE_FAILED_MIN_ONE_SUCCESS,
    dag=dag
)
load_snowflake_task = PythonOperator(
    task_id='load_to_snowflake',
    python_callable=load_to_snowflake,
    dag=dag
)
process_databricks_task = PythonOperator(
    task_id='process_with_databricks',
    python_callable=process_with_databricks,
    dag=dag
)
quality_report_task = PythonOperator(
    task_id='generate_data_quality_report',
    python_callable=generate_data_quality_report,
    trigger_rule=TriggerRule.NONE_FAILED,
    dag=dag
)
notification_task = PythonOperator(
    task_id='send_completion_notification',
    python_callable=send_completion_notification,
    trigger_rule=TriggerRule.ALL_DONE,
    dag=dag
)
check_vendors_task >> [skip_pipeline_task, extract_universe_task]
extract_universe_task >> [extract_bloomberg_task, extract_refinitiv_task, extract_factset_task]
[extract_bloomberg_task, extract_refinitiv_task, extract_factset_task] >> merge_data_task
merge_data_task >> [load_snowflake_task, process_databricks_task]
[load_snowflake_task, process_databricks_task] >> quality_report_task
quality_report_task >> notification_task