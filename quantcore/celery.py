import os
from celery import Celery
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quantcore.settings')

app = Celery('quantcore')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()

# Celery Beat Schedule (replaces Airflow DAG scheduling)
app.conf.beat_schedule = {
    # Daily market data pipeline (runs at 6 AM UTC, after market close)
    'daily-market-data-pipeline': {
        'task': 'apps.market_data.tasks.daily_market_data_pipeline',
        'schedule': '0 6 * * 1-5',  # Monday to Friday at 6 AM UTC
    },
    
    # Hourly data fetch during market hours
    'hourly-market-data-fetch': {
        'task': 'apps.market_data.tasks.fetch_market_data_task',
        'schedule': '0 14-21 * * 1-5',  # 2 PM to 9 PM UTC (market hours)
    },
    
    # Technical indicators calculation (every 4 hours during weekdays)
    'calculate-technical-indicators': {
        'task': 'apps.market_data.tasks.calculate_technical_indicators_task',
        'schedule': '0 */4 * * 1-5',
    },
    
    # Data quality checks (twice daily)
    'data-quality-checks': {
        'task': 'apps.market_data.tasks.data_quality_check_task',
        'schedule': '0 8,20 * * 1-5',  # 8 AM and 8 PM UTC
    },
    
    # Weekly comprehensive analysis (Sundays at 2 AM UTC)
    'weekly-comprehensive-analysis': {
        'task': 'apps.market_data.tasks.weekly_comprehensive_analysis',
        'schedule': '0 2 * * 0',  # Sunday at 2 AM UTC
    },
    
    # Risk metrics calculation (daily at 7 AM UTC)
    'daily-risk-metrics': {
        'task': 'apps.market_data.tasks.calculate_risk_metrics_task',
        'schedule': '0 7 * * 1-5',
    },
}

app.conf.timezone = 'UTC'

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')