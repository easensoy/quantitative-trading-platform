from celery import shared_task
from django.utils import timezone
from datetime import datetime, timedelta
from typing import List
import logging

from .services import MarketDataService
from .models import Instrument, DataProvider

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def fetch_market_data_task(self, symbols: List[str] = None, provider: str = 'yfinance', 
                          days_back: int = 1):
    """
    Celery task to fetch market data (replaces Airflow market data DAG)
    """
    try:
        import asyncio
        from asgiref.sync import sync_to_async
        
        async def _fetch_data():
            service = MarketDataService()
            
            # Get symbols to fetch
            if not symbols:
                instruments = await sync_to_async(list)(
                    Instrument.objects.filter(is_active=True).values_list('symbol', flat=True)
                )
                symbols_to_fetch = list(instruments)
            else:
                symbols_to_fetch = symbols
            
            if not symbols_to_fetch:
                logger.warning("No symbols to fetch")
                return {'status': 'warning', 'message': 'No symbols to fetch'}
            
            # Calculate date range
            end_date = timezone.now()
            start_date = end_date - timedelta(days=days_back)
            
            logger.info(f"Fetching data for {len(symbols_to_fetch)} symbols from {provider}")
            
            # Fetch market data
            market_data_objects = await service.fetch_market_data(
                symbols=symbols_to_fetch,
                start_date=start_date,
                end_date=end_date,
                provider=provider
            )
            
            if market_data_objects:
                saved_count = await service.bulk_save_market_data(market_data_objects)
                logger.info(f"Successfully saved {saved_count} market data records")
                
                return {
                    'status': 'success',
                    'symbols_processed': len(symbols_to_fetch),
                    'records_saved': saved_count,
                    'provider': provider
                }
            else:
                logger.warning("No market data was fetched")
                return {'status': 'warning', 'message': 'No market data was fetched'}
        
        # Run the async function
        result = asyncio.run(_fetch_data())
        return result
        
    except Exception as exc:
        logger.error(f"Error in fetch_market_data_task: {exc}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=2)
def calculate_technical_indicators_task(self, symbols: List[str] = None):
    """
    Celery task to calculate technical indicators
    """
    try:
        import asyncio
        from asgiref.sync import sync_to_async
        
        async def _calculate_indicators():
            service = MarketDataService()
            
            # Get instruments
            if symbols:
                instruments = []
                for symbol in symbols:
                    try:
                        instrument = await sync_to_async(Instrument.objects.get)(
                            symbol=symbol, is_active=True
                        )
                        instruments.append(instrument)
                    except Instrument.DoesNotExist:
                        logger.warning(f"Instrument {symbol} not found")
            else:
                instruments = await sync_to_async(list)(
                    Instrument.objects.filter(is_active=True)
                )
            
            processed_count = 0
            error_count = 0
            
            for instrument in instruments:
                try:
                    await service.calculate_technical_indicators(instrument)
                    processed_count += 1
                    logger.info(f"Calculated technical indicators for {instrument.symbol}")
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error calculating indicators for {instrument.symbol}: {e}")
            
            return {
                'status': 'success',
                'processed': processed_count,
                'errors': error_count,
                'total_instruments': len(instruments)
            }
        
        result = asyncio.run(_calculate_indicators())
        return result
        
    except Exception as exc:
        logger.error(f"Error in calculate_technical_indicators_task: {exc}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=2)
def calculate_risk_metrics_task(self, symbols: List[str] = None, force_recalculate: bool = False):
    """
    Celery task to calculate risk metrics
    """
    try:
        import asyncio
        from asgiref.sync import sync_to_async
        from .models import RiskMetrics
        
        async def _calculate_risk_metrics():
            service = MarketDataService()
            
            # Get instruments
            if symbols:
                instruments = []
                for symbol in symbols:
                    try:
                        instrument = await sync_to_async(Instrument.objects.get)(
                            symbol=symbol, is_active=True
                        )
                        instruments.append(instrument)
                    except Instrument.DoesNotExist:
                        logger.warning(f"Instrument {symbol} not found")
            else:
                instruments = await sync_to_async(list)(
                    Instrument.objects.filter(is_active=True)
                )
            
            processed_count = 0
            skipped_count = 0
            error_count = 0
            today = timezone.now().date()
            
            for instrument in instruments:
                try:
                    # Check if metrics already exist for today
                    if not force_recalculate:
                        existing_metrics = await sync_to_async(RiskMetrics.objects.filter(
                            instrument=instrument,
                            calculation_date=today
                        ).exists)()
                        
                        if existing_metrics:
                            skipped_count += 1
                            continue
                    
                    # Calculate risk metrics
                    risk_metrics = await service.calculate_risk_metrics(instrument)
                    
                    if risk_metrics:
                        processed_count += 1
                        logger.info(f"Calculated risk metrics for {instrument.symbol}")
                    else:
                        error_count += 1
                        logger.warning(f"Unable to calculate risk metrics for {instrument.symbol}")
                        
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error calculating risk metrics for {instrument.symbol}: {e}")
            
            return {
                'status': 'success',
                'processed': processed_count,
                'skipped': skipped_count,
                'errors': error_count,
                'total_instruments': len(instruments)
            }
        
        result = asyncio.run(_calculate_risk_metrics())
        return result
        
    except Exception as exc:
        logger.error(f"Error in calculate_risk_metrics_task: {exc}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=2)
def data_quality_check_task(self, provider_name: str = None):
    """
    Celery task to run data quality checks
    """
    try:
        import asyncio
        from asgiref.sync import sync_to_async
        
        async def _run_quality_checks():
            service = MarketDataService()
            
            # Get providers to check
            if provider_name:
                try:
                    providers = [await sync_to_async(DataProvider.objects.get)(
                        name=provider_name, is_active=True
                    )]
                except DataProvider.DoesNotExist:
                    logger.error(f"Provider {provider_name} not found")
                    return {'status': 'error', 'message': f'Provider {provider_name} not found'}
            else:
                providers = await sync_to_async(list)(
                    DataProvider.objects.filter(is_active=True)
                )
            
            total_checks = 0
            passed_checks = 0
            failed_checks = 0
            
            for provider in providers:
                try:
                    checks = await service.run_data_quality_checks(provider)
                    
                    for check in checks:
                        total_checks += 1
                        if check.status == 'passed':
                            passed_checks += 1
                        else:
                            failed_checks += 1
                            logger.warning(
                                f"Quality check failed: {provider.name} - {check.check_name}: {check.message}"
                            )
                    
                    logger.info(f"Completed quality checks for provider {provider.name}")
                    
                except Exception as e:
                    logger.error(f"Error running quality checks for {provider.name}: {e}")
                    failed_checks += 1
                    total_checks += 1
            
            success_rate = (passed_checks / total_checks * 100) if total_checks > 0 else 0
            
            return {
                'status': 'success',
                'total_checks': total_checks,
                'passed_checks': passed_checks,
                'failed_checks': failed_checks,
                'success_rate': success_rate,
                'providers_checked': len(providers)
            }
        
        result = asyncio.run(_run_quality_checks())
        return result
        
    except Exception as exc:
        logger.error(f"Error in data_quality_check_task: {exc}")
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@shared_task
def daily_market_data_pipeline():
    """
    Daily pipeline task that orchestrates market data processing
    (replaces Airflow DAG orchestration)
    """
    logger.info("Starting daily market data pipeline")
    
    # Step 1: Fetch market data
    fetch_result = fetch_market_data_task.delay(days_back=1)
    fetch_data = fetch_result.get()
    
    if fetch_data['status'] != 'success':
        logger.error(f"Market data fetch failed: {fetch_data}")
        return {'status': 'failed', 'step': 'fetch_market_data', 'error': fetch_data}
    
    # Step 2: Calculate technical indicators
    indicators_result = calculate_technical_indicators_task.delay()
    indicators_data = indicators_result.get()
    
    if indicators_data['status'] != 'success':
        logger.warning(f"Technical indicators calculation had issues: {indicators_data}")
    
    # Step 3: Calculate risk metrics
    risk_result = calculate_risk_metrics_task.delay()
    risk_data = risk_result.get()
    
    if risk_data['status'] != 'success':
        logger.warning(f"Risk metrics calculation had issues: {risk_data}")
    
    # Step 4: Run data quality checks
    quality_result = data_quality_check_task.delay()
    quality_data = quality_result.get()
    
    if quality_data['status'] != 'success':
        logger.warning(f"Data quality checks had issues: {quality_data}")
    
    # Pipeline summary
    pipeline_result = {
        'status': 'success',
        'pipeline': 'daily_market_data',
        'completed_at': timezone.now().isoformat(),
        'steps': {
            'fetch_market_data': fetch_data,
            'technical_indicators': indicators_data,
            'risk_metrics': risk_data,
            'quality_checks': quality_data
        }
    }
    
    logger.info(f"Daily market data pipeline completed: {pipeline_result}")
    return pipeline_result


@shared_task
def weekly_comprehensive_analysis():
    """
    Weekly comprehensive analysis task
    """
    logger.info("Starting weekly comprehensive analysis")
    
    # Recalculate everything with force flag
    risk_result = calculate_risk_metrics_task.delay(force_recalculate=True)
    risk_data = risk_result.get()
    
    indicators_result = calculate_technical_indicators_task.delay()
    indicators_data = indicators_result.get()
    
    # Run comprehensive quality checks
    quality_result = data_quality_check_task.delay()
    quality_data = quality_result.get()
    
    result = {
        'status': 'success',
        'pipeline': 'weekly_comprehensive_analysis',
        'completed_at': timezone.now().isoformat(),
        'steps': {
            'risk_metrics': risk_data,
            'technical_indicators': indicators_data,
            'quality_checks': quality_data
        }
    }
    
    logger.info(f"Weekly comprehensive analysis completed: {result}")
    return result