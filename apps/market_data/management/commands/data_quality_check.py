from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
import asyncio
from asgiref.sync import sync_to_async

from apps.market_data.services import MarketDataService
from apps.market_data.models import DataProvider, DataQualityCheck


class Command(BaseCommand):
    help = 'Run data quality checks on market data (replaces DBT data quality tests)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--provider',
            type=str,
            help='Specific provider to check (default: all active providers)',
        )
        parser.add_argument(
            '--check-type',
            type=str,
            choices=['completeness', 'accuracy', 'consistency', 'timeliness'],
            help='Specific check type to run (default: all)',
        )
        parser.add_argument(
            '--fail-on-error',
            action='store_true',
            help='Exit with error code if any checks fail',
        )

    def handle(self, *args, **options):
        asyncio.run(self._handle_async(*args, **options))

    async def _handle_async(self, *args, **options):
        service = await MarketDataService.create()
        
        # Get providers to check
        if options['provider']:
            try:
                providers = [await sync_to_async(DataProvider.objects.get)(
                    name=options['provider'], is_active=True
                )]
            except DataProvider.DoesNotExist:
                raise CommandError(f"Provider '{options['provider']}' not found or inactive")
        else:
            providers = await sync_to_async(list)(
                DataProvider.objects.filter(is_active=True)
            )

        if not providers:
            self.stdout.write(self.style.WARNING('No active providers found'))
            return

        self.stdout.write(f"Running data quality checks for {len(providers)} provider(s)")
        self.stdout.write("="*60)

        total_checks = 0
        passed_checks = 0
        warning_checks = 0
        failed_checks = 0
        
        for provider in providers:
            self.stdout.write(f"\n📊 Checking provider: {provider.name}")
            self.stdout.write("-" * 40)
            
            try:
                # Run quality checks
                checks = await service.run_data_quality_checks(provider)
                
                if not checks:
                    self.stdout.write(self.style.WARNING("  No checks were performed"))
                    continue
                
                # Display results for this provider
                provider_passed = 0
                provider_warnings = 0
                provider_failed = 0
                
                for check in checks:
                    total_checks += 1
                    
                    # Status emoji
                    if check.status == 'passed':
                        status_icon = "✅"
                        provider_passed += 1
                        passed_checks += 1
                    elif check.status == 'warning':
                        status_icon = "⚠️"
                        provider_warnings += 1
                        warning_checks += 1
                    else:
                        status_icon = "❌"
                        provider_failed += 1
                        failed_checks += 1
                    
                    # Display check result
                    self.stdout.write(
                        f"  {status_icon} {check.check_name}: "
                        f"{check.score:.3f} (threshold: {check.threshold})"
                    )
                    
                    if check.message:
                        self.stdout.write(f"     📝 {check.message}")
                
                # Provider summary
                self.stdout.write(f"\n  Provider Summary:")
                self.stdout.write(f"    ✅ Passed: {provider_passed}")
                if provider_warnings > 0:
                    self.stdout.write(f"    ⚠️  Warnings: {provider_warnings}")
                if provider_failed > 0:
                    self.stdout.write(f"    ❌ Failed: {provider_failed}")
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"  Error running checks for {provider.name}: {e}")
                )
                failed_checks += 1
                total_checks += 1

        # Overall summary
        self.stdout.write("\n" + "="*60)
        self.stdout.write("📈 OVERALL SUMMARY")
        self.stdout.write("="*60)
        self.stdout.write(f"Total Checks: {total_checks}")
        self.stdout.write(f"✅ Passed: {passed_checks}")
        
        if warning_checks > 0:
            self.stdout.write(f"⚠️  Warnings: {warning_checks}")
        
        if failed_checks > 0:
            self.stdout.write(f"❌ Failed: {failed_checks}")
        
        # Calculate success rate
        if total_checks > 0:
            success_rate = (passed_checks / total_checks) * 100
            self.stdout.write(f"📊 Success Rate: {success_rate:.1f}%")
            
            # Status based on success rate
            if success_rate >= 95:
                overall_status = self.style.SUCCESS("EXCELLENT")
            elif success_rate >= 85:
                overall_status = self.style.WARNING("GOOD")
            elif success_rate >= 70:
                overall_status = self.style.WARNING("FAIR")
            else:
                overall_status = self.style.ERROR("POOR")
            
            self.stdout.write(f"🏆 Data Quality: {overall_status}")
        
        # Recent failed checks details
        if failed_checks > 0:
            self.stdout.write("\n🔍 RECENT FAILED CHECKS:")
            self.stdout.write("-" * 30)
            
            # select_related: reading failure.provider below would otherwise run a lazy
            # query inside the event loop, which Django rejects (SynchronousOnlyOperation).
            recent_failures = await sync_to_async(list)(
                DataQualityCheck.objects.filter(
                    status='failed',
                    checked_at__gte=timezone.now() - timezone.timedelta(hours=24)
                ).select_related('provider').order_by('-checked_at')[:10]
            )
            
            for failure in recent_failures:
                self.stdout.write(
                    f"❌ {failure.provider.name} - {failure.check_name}: {failure.message}"
                )
        
        # Exit with error if requested and checks failed
        if options['fail_on_error'] and failed_checks > 0:
            raise CommandError(f"Data quality checks failed: {failed_checks} failures detected")
        
        self.stdout.write("\n✨ Data quality check completed!")