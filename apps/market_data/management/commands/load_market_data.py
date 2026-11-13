from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, timedelta
import asyncio
from typing import List

from apps.market_data.services import MarketDataService
from apps.market_data.models import Instrument


class Command(BaseCommand):
    help = 'Load market data from external providers (replaces DBT market data staging)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            type=str,
            help='Comma-separated list of symbols (default: all active instruments)',
        )
        parser.add_argument(
            '--provider',
            type=str,
            default='yfinance',
            help='Data provider to use (default: yfinance)',
        )
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date (YYYY-MM-DD format)',
        )
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date (YYYY-MM-DD format)',
        )
        parser.add_argument(
            '--days-back',
            type=int,
            default=30,
            help='Number of days back to fetch (default: 30)',
        )
        parser.add_argument(
            '--calculate-indicators',
            action='store_true',
            help='Calculate technical indicators after loading data',
        )

    def handle(self, *args, **options):
        asyncio.run(self._handle_async(*args, **options))

    async def _handle_async(self, *args, **options):
        service = await MarketDataService.create()
        
        # Parse dates
        if options['start_date'] and options['end_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
            except ValueError:
                raise CommandError('Date format must be YYYY-MM-DD')
        else:
            end_date = timezone.now()
            start_date = end_date - timedelta(days=options['days_back'])

        # Get symbols
        if options['symbols']:
            symbols = [s.strip() for s in options['symbols'].split(',')]
            self.stdout.write(f"Loading data for symbols: {', '.join(symbols)}")
        else:
            from asgiref.sync import sync_to_async
            instruments = await sync_to_async(list)(
                Instrument.objects.filter(is_active=True).values_list('symbol', flat=True)
            )
            symbols = list(instruments)
            self.stdout.write(f"Loading data for {len(symbols)} active instruments")

        if not symbols:
            self.stdout.write(self.style.WARNING('No symbols to process'))
            return

        # Fetch and save market data
        self.stdout.write(f"Fetching data from {start_date.date()} to {end_date.date()}")
        
        try:
            market_data_objects = await service.fetch_market_data(
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                provider=options['provider']
            )
            
            if market_data_objects:
                saved_count = await service.bulk_save_market_data(market_data_objects)
                self.stdout.write(
                    self.style.SUCCESS(f"Successfully saved {saved_count} market data records")
                )
                
                # Calculate technical indicators if requested
                if options['calculate_indicators']:
                    self.stdout.write("Calculating technical indicators...")
                    from asgiref.sync import sync_to_async
                    
                    for symbol in symbols:
                        try:
                            instrument = await sync_to_async(Instrument.objects.get)(symbol=symbol)
                            await service.calculate_technical_indicators(instrument)
                            self.stdout.write(f"Calculated indicators for {symbol}")
                        except Instrument.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(f"Instrument {symbol} not found in database")
                            )
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(f"Error calculating indicators for {symbol}: {e}")
                            )
                    
                    self.stdout.write(self.style.SUCCESS("Technical indicators calculation completed"))
            else:
                self.stdout.write(self.style.WARNING('No market data was fetched'))
                
        except Exception as e:
            raise CommandError(f'Error loading market data: {e}')