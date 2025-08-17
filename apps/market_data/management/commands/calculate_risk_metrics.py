from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, timedelta
import asyncio
from asgiref.sync import sync_to_async

from apps.market_data.services import MarketDataService
from apps.market_data.models import Instrument, RiskMetrics


class Command(BaseCommand):
    help = 'Calculate risk metrics for instruments (replaces DBT risk metrics transformation)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            type=str,
            help='Comma-separated list of symbols (default: all active instruments)',
        )
        parser.add_argument(
            '--force-recalculate',
            action='store_true',
            help='Recalculate even if metrics exist for today',
        )
        parser.add_argument(
            '--min-data-points',
            type=int,
            default=252,
            help='Minimum number of data points required for calculation (default: 252)',
        )

    def handle(self, *args, **options):
        asyncio.run(self._handle_async(*args, **options))

    async def _handle_async(self, *args, **options):
        service = MarketDataService()
        
        # Get symbols to process
        if options['symbols']:
            symbols = [s.strip() for s in options['symbols'].split(',')]
            instruments = []
            for symbol in symbols:
                try:
                    instrument = await sync_to_async(Instrument.objects.get)(
                        symbol=symbol, is_active=True
                    )
                    instruments.append(instrument)
                except Instrument.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(f"Instrument {symbol} not found or inactive")
                    )
        else:
            instruments = await sync_to_async(list)(
                Instrument.objects.filter(is_active=True)
            )

        if not instruments:
            self.stdout.write(self.style.WARNING('No instruments to process'))
            return

        self.stdout.write(f"Processing {len(instruments)} instruments")
        
        today = timezone.now().date()
        processed_count = 0
        skipped_count = 0
        error_count = 0

        for instrument in instruments:
            try:
                # Check if metrics already exist for today
                if not options['force_recalculate']:
                    existing_metrics = await sync_to_async(RiskMetrics.objects.filter(
                        instrument=instrument,
                        calculation_date=today
                    ).exists)()
                    
                    if existing_metrics:
                        self.stdout.write(f"Skipping {instrument.symbol} - metrics already exist for today")
                        skipped_count += 1
                        continue

                # Check if we have enough data points
                from apps.market_data.models import MarketData
                data_count = await sync_to_async(MarketData.objects.filter(
                    instrument=instrument,
                    timestamp__gte=timezone.now() - timedelta(days=options['min_data_points'] * 2)
                ).count)()
                
                if data_count < options['min_data_points']:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping {instrument.symbol} - insufficient data "
                            f"({data_count} < {options['min_data_points']})"
                        )
                    )
                    skipped_count += 1
                    continue

                # Calculate risk metrics
                self.stdout.write(f"Calculating risk metrics for {instrument.symbol}...")
                
                risk_metrics = await service.calculate_risk_metrics(instrument)
                
                if risk_metrics:
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ {instrument.symbol} - Risk Score: {risk_metrics.risk_score}")
                    )
                    processed_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f"✗ {instrument.symbol} - Unable to calculate metrics")
                    )
                    error_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ {instrument.symbol} - Error: {e}")
                )
                error_count += 1

        # Summary
        self.stdout.write("\n" + "="*50)
        self.stdout.write(f"Risk Metrics Calculation Summary:")
        self.stdout.write(f"  Processed: {processed_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        self.stdout.write(f"  Errors: {error_count}")
        self.stdout.write("="*50)

        if error_count > 0:
            self.stdout.write(
                self.style.WARNING(f"Completed with {error_count} errors")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Risk metrics calculation completed successfully")
            )