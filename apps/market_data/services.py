from typing import List, Dict, Optional, Any
from decimal import Decimal
from datetime import datetime, timedelta
from django.db import transaction, models
from django.utils import timezone
from django.conf import settings
import pandas as pd
import yfinance as yf
import asyncio
from asgiref.sync import sync_to_async

from .models import (
    DataProvider, Instrument, MarketData, TechnicalIndicator, 
    FundamentalData, RiskMetrics, DataQualityCheck
)


class MarketDataService:
    def __init__(self):
        self.providers = self._initialize_providers()

    @classmethod
    async def create(cls) -> 'MarketDataService':
        """Construct from async code. __init__ queries the database, which Django forbids
        inside a running event loop (SynchronousOnlyOperation)."""
        return await sync_to_async(cls)()

    def _initialize_providers(self) -> Dict[str, DataProvider]:
        providers = {}
        for provider_name in settings.TRADING_CONFIG.get('MARKET_DATA_PROVIDERS', ['yfinance']):
            provider, created = DataProvider.objects.get_or_create(
                name=provider_name,
                defaults={'is_active': True}
            )
            providers[provider_name] = provider
        return providers

    async def get_or_create_instrument(self, symbol: str, asset_type: str = 'equity', 
                                     exchange: str = 'NASDAQ') -> Instrument:
        instrument, created = await sync_to_async(Instrument.objects.get_or_create)(
            symbol=symbol,
            defaults={
                'name': symbol,
                'asset_type': asset_type,
                'exchange': exchange
            }
        )
        return instrument

    async def fetch_market_data(self, symbols: List[str], start_date: datetime, 
                              end_date: datetime, provider: str = 'yfinance') -> List[MarketData]:
        if provider not in self.providers:
            raise ValueError(f"Provider {provider} not configured")

        provider_obj = self.providers[provider]
        market_data_objects = []

        if provider == 'yfinance':
            market_data_objects = await self._fetch_yfinance_data(
                symbols, start_date, end_date, provider_obj
            )

        return market_data_objects

    async def _fetch_yfinance_data(self, symbols: List[str], start_date: datetime, 
                                 end_date: datetime, provider: DataProvider) -> List[MarketData]:
        market_data_objects = []
        
        for symbol in symbols:
            try:
                instrument = await self.get_or_create_instrument(symbol)
                
                ticker = yf.Ticker(symbol)
                data = await sync_to_async(ticker.history)(
                    start=start_date.date(),
                    end=end_date.date(),
                    interval='1d'
                )
                
                if data.empty:
                    continue

                for date, row in data.iterrows():
                    market_data = MarketData(
                        instrument=instrument,
                        provider=provider,
                        timestamp=timezone.make_aware(datetime.combine(date.date(), datetime.min.time())),
                        open_price=Decimal(str(row['Open'])),
                        high_price=Decimal(str(row['High'])),
                        low_price=Decimal(str(row['Low'])),
                        close_price=Decimal(str(row['Close'])),
                        volume=int(row['Volume']),
                        data_quality_score=Decimal('1.0')
                    )
                    market_data_objects.append(market_data)

            except Exception as e:
                print(f"Error fetching data for {symbol}: {e}")
                continue

        return market_data_objects

    async def bulk_save_market_data(self, market_data_objects: List[MarketData]) -> int:
        return await sync_to_async(self._bulk_save_market_data)(market_data_objects)

    # transaction.atomic cannot wrap a coroutine (it only covered creating the coroutine
    # and raised SynchronousOnlyOperation inside the event loop), so the inserts run here.
    @transaction.atomic
    def _bulk_save_market_data(self, market_data_objects: List[MarketData]) -> int:
        saved_count = 0
        batch_size = 1000
        
        for i in range(0, len(market_data_objects), batch_size):
            batch = market_data_objects[i:i + batch_size]
            MarketData.objects.bulk_create(
                batch,
                ignore_conflicts=True,
                batch_size=batch_size
            )
            saved_count += len(batch)
        
        return saved_count

    async def calculate_technical_indicators(self, instrument: Instrument, 
                                           lookback_days: int = 100) -> None:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        market_data_qs = MarketData.objects.filter(
            instrument=instrument,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp')
        
        market_data_list = await sync_to_async(list)(market_data_qs)
        
        if len(market_data_list) < 20:
            return

        df = pd.DataFrame([
            {
                'timestamp': md.timestamp,
                'close': float(md.close_price),
                'volume': md.volume,
                'id': md.id
            }
            for md in market_data_list
        ])

        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['ema_20'] = df['close'].ewm(span=20).mean()
        
        df['bollinger_sma'] = df['close'].rolling(window=20).mean()
        df['bollinger_std'] = df['close'].rolling(window=20).std()
        df['bollinger_upper'] = df['bollinger_sma'] + (2 * df['bollinger_std'])
        df['bollinger_lower'] = df['bollinger_sma'] - (2 * df['bollinger_std'])
        
        df['rsi'] = self._calculate_rsi(df['close'])
        df['volume_ratio'] = df['volume'] / df['volume'].rolling(window=20).mean()
        df['momentum_20d'] = df['close'].pct_change(periods=20)

        technical_indicators = []
        for _, row in df.iterrows():
            if pd.notna(row['sma_20']):
                market_data_obj = next((md for md in market_data_list if md.id == row['id']), None)
                if market_data_obj:
                    technical_indicators.append(
                        TechnicalIndicator(
                            market_data=market_data_obj,
                            sma_20=Decimal(str(row['sma_20'])) if pd.notna(row['sma_20']) else None,
                            sma_50=Decimal(str(row['sma_50'])) if pd.notna(row['sma_50']) else None,
                            ema_20=Decimal(str(row['ema_20'])) if pd.notna(row['ema_20']) else None,
                            bollinger_upper=Decimal(str(row['bollinger_upper'])) if pd.notna(row['bollinger_upper']) else None,
                            bollinger_lower=Decimal(str(row['bollinger_lower'])) if pd.notna(row['bollinger_lower']) else None,
                            rsi=Decimal(str(row['rsi'])) if pd.notna(row['rsi']) else None,
                            volume_ratio=Decimal(str(row['volume_ratio'])) if pd.notna(row['volume_ratio']) else None,
                            momentum_20d=Decimal(str(row['momentum_20d'])) if pd.notna(row['momentum_20d']) else None,
                        )
                    )

        if technical_indicators:
            await sync_to_async(TechnicalIndicator.objects.bulk_create)(
                technical_indicators,
                ignore_conflicts=True
            )

    def _calculate_rsi(self, prices: pd.Series, window: int = 14) -> pd.Series:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(window=window).mean()
        avg_loss = loss.rolling(window=window).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    async def calculate_risk_metrics(self, instrument: Instrument) -> RiskMetrics:
        end_date = timezone.now()
        start_date = end_date - timedelta(days=730)  # 2 years of data for calculations
        
        market_data_qs = MarketData.objects.filter(
            instrument=instrument,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp')
        
        market_data_list = await sync_to_async(list)(market_data_qs)
        
        if len(market_data_list) < 252:  # Need at least 1 year of data
            return None

        df = pd.DataFrame([
            {
                'timestamp': md.timestamp,
                'close': float(md.close_price),
                'daily_return': float(md.daily_return) if md.daily_return else None
            }
            for md in market_data_list
        ])

        if df['daily_return'].isna().all():
            df['daily_return'] = df['close'].pct_change()

        df = df.dropna(subset=['daily_return'])

        volatility_30d = df['daily_return'].tail(30).std() * (252 ** 0.5)
        volatility_90d = df['daily_return'].tail(90).std() * (252 ** 0.5)
        volatility_1y = df['daily_return'].tail(252).std() * (252 ** 0.5)
        
        avg_return_30d = df['daily_return'].tail(30).mean() * 252
        avg_return_1y = df['daily_return'].tail(252).mean() * 252
        
        risk_free_rate = settings.TRADING_CONFIG.get('RISK_FREE_RATE', 0.02)
        sharpe_ratio_1y = (avg_return_1y - risk_free_rate) / volatility_1y if volatility_1y > 0 else None
        
        df['cumulative'] = (1 + df['daily_return']).cumprod()
        df['running_max'] = df['cumulative'].expanding().max()
        df['drawdown'] = (df['cumulative'] - df['running_max']) / df['running_max']
        
        current_drawdown = df['drawdown'].iloc[-1]
        max_drawdown_1y = df['drawdown'].tail(252).min()
        
        var_95_1y = df['daily_return'].tail(252).quantile(0.05)
        var_99_1y = df['daily_return'].tail(252).quantile(0.01)
        
        tail_returns = df['daily_return'].tail(252)
        expected_shortfall_95 = tail_returns[tail_returns <= var_95_1y].mean()

        volatility_category = 'unknown'
        if volatility_1y <= 0.15:
            volatility_category = 'low'
        elif volatility_1y <= 0.25:
            volatility_category = 'medium'
        elif volatility_1y <= 0.40:
            volatility_category = 'high'
        else:
            volatility_category = 'very_high'

        risk_score = min(100, max(0,
            volatility_1y * 100 * 0.3 +
            abs(max_drawdown_1y) * 100 * 0.3 +
            abs(var_95_1y) * 100 * 0.2 +
            (max(0, volatility_1y - 0.25) * 50) * 0.2
        ))

        # (instrument, calculation_date) is unique: recalculating on the same day
        # (--force-recalculate) must update today's row instead of inserting a second one.
        risk_metrics, _ = await sync_to_async(RiskMetrics.objects.update_or_create)(
            instrument=instrument,
            calculation_date=timezone.now().date(),
            defaults=dict(
                volatility_30d=Decimal(str(volatility_30d)),
                volatility_90d=Decimal(str(volatility_90d)),
                volatility_1y=Decimal(str(volatility_1y)),
                avg_return_30d_annualized=Decimal(str(avg_return_30d)),
                avg_return_1y_annualized=Decimal(str(avg_return_1y)),
                sharpe_ratio_1y=Decimal(str(sharpe_ratio_1y)) if sharpe_ratio_1y else None,
                current_drawdown=Decimal(str(current_drawdown)),
                max_drawdown_1y=Decimal(str(max_drawdown_1y)),
                var_95_1y=Decimal(str(var_95_1y)),
                var_99_1y=Decimal(str(var_99_1y)),
                expected_shortfall_95=Decimal(str(expected_shortfall_95)),
                volatility_category=volatility_category,
                risk_score=Decimal(str(risk_score)),
            ),
        )
        return risk_metrics

    async def run_data_quality_checks(self, provider: DataProvider) -> List[DataQualityCheck]:
        checks = []
        
        completeness_check = await self._check_data_completeness(provider)
        if completeness_check:
            checks.append(completeness_check)
        
        consistency_check = await self._check_data_consistency(provider)
        if consistency_check:
            checks.append(consistency_check)
        
        timeliness_check = await self._check_data_timeliness(provider)
        if timeliness_check:
            checks.append(timeliness_check)

        if checks:
            await sync_to_async(DataQualityCheck.objects.bulk_create)(checks)
        
        return checks

    async def _check_data_completeness(self, provider: DataProvider) -> Optional[DataQualityCheck]:
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        
        total_expected = await sync_to_async(Instrument.objects.filter(is_active=True).count)()
        actual_count = await sync_to_async(MarketData.objects.filter(
            provider=provider,
            timestamp__date=yesterday
        ).values('instrument').distinct().count)()
        
        score = actual_count / total_expected if total_expected > 0 else 0
        threshold = 0.8
        status = 'passed' if score >= threshold else 'failed'
        
        return DataQualityCheck(
            provider=provider,
            check_type='completeness',
            check_name='Daily Data Completeness',
            status=status,
            score=Decimal(str(score)),
            threshold=Decimal(str(threshold)),
            message=f"Expected {total_expected} instruments, got {actual_count}",
            metadata={'expected': total_expected, 'actual': actual_count}
        )

    async def _check_data_consistency(self, provider: DataProvider) -> Optional[DataQualityCheck]:
        yesterday = timezone.now().date() - timedelta(days=1)
        
        total_records = await sync_to_async(MarketData.objects.filter(
            provider=provider,
            timestamp__date=yesterday
        ).count)()
        
        if total_records == 0:
            return None
        
        # The Q expression must come before the keyword filters; the previous order was a
        # SyntaxError that stopped this module (and every task and command) from importing.
        invalid_records = await sync_to_async(MarketData.objects.filter(
            models.Q(high_price__lt=models.F('low_price')) |
            models.Q(high_price__lt=models.F('close_price')) |
            models.Q(low_price__gt=models.F('close_price')),
            provider=provider,
            timestamp__date=yesterday,
        ).count)()
        
        score = (total_records - invalid_records) / total_records
        threshold = 0.95
        status = 'passed' if score >= threshold else 'failed'
        
        return DataQualityCheck(
            provider=provider,
            check_type='consistency',
            check_name='Price Data Consistency',
            status=status,
            score=Decimal(str(score)),
            threshold=Decimal(str(threshold)),
            message=f"Found {invalid_records} inconsistent records out of {total_records}",
            metadata={'total': total_records, 'invalid': invalid_records}
        )

    async def _check_data_timeliness(self, provider: DataProvider) -> Optional[DataQualityCheck]:
        latest_data = await sync_to_async(MarketData.objects.filter(
            provider=provider
        ).order_by('-timestamp').first)()
        
        if not latest_data:
            return DataQualityCheck(
                provider=provider,
                check_type='timeliness',
                check_name='Data Timeliness',
                status='failed',
                score=Decimal('0'),
                threshold=Decimal('0.8'),
                message="No data found for provider"
            )
        
        now = timezone.now()
        hours_behind = (now - latest_data.timestamp).total_seconds() / 3600
        
        threshold_hours = 24
        score = max(0, 1 - (hours_behind / threshold_hours))
        status = 'passed' if score >= 0.8 else 'failed'
        
        return DataQualityCheck(
            provider=provider,
            check_type='timeliness',
            check_name='Data Timeliness',
            status=status,
            score=Decimal(str(score)),
            threshold=Decimal('0.8'),
            message=f"Latest data is {hours_behind:.1f} hours old",
            metadata={'hours_behind': hours_behind}
        )