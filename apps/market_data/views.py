from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q, Avg, Count, Max, Min
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import (
    Instrument, MarketData, TechnicalIndicator, FundamentalData,
    RiskMetrics, DataProvider, DataQualityCheck
)
from .serializers import (
    InstrumentSerializer, MarketDataSerializer, TechnicalIndicatorSerializer,
    FundamentalDataSerializer, RiskMetricsSerializer, DataProviderSerializer,
    DataQualityCheckSerializer, MarketDataSummarySerializer
)


class InstrumentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing instruments
    """
    queryset = Instrument.objects.filter(is_active=True)
    serializer_class = InstrumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by asset type
        asset_type = self.request.query_params.get('asset_type', None)
        if asset_type:
            queryset = queryset.filter(asset_type=asset_type)
        
        # Filter by exchange
        exchange = self.request.query_params.get('exchange', None)
        if exchange:
            queryset = queryset.filter(exchange=exchange)
        
        # Search by symbol or name
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(symbol__icontains=search) | Q(name__icontains=search)
            )
        
        return queryset.order_by('symbol')

    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get market summary for an instrument"""
        instrument = self.get_object()
        
        # Get latest market data
        latest_data = MarketData.objects.filter(
            instrument=instrument
        ).order_by('-timestamp').first()
        
        if not latest_data:
            return Response({'message': 'No market data available'}, status=status.HTTP_404_NOT_FOUND)
        
        # Get 52-week high/low
        year_ago = timezone.now() - timedelta(days=365)
        year_data = MarketData.objects.filter(
            instrument=instrument,
            timestamp__gte=year_ago
        ).aggregate(
            high_52w=Max('high_price'),
            low_52w=Min('low_price')
        )
        
        # Calculate daily change
        previous_data = MarketData.objects.filter(
            instrument=instrument,
            timestamp__lt=latest_data.timestamp
        ).order_by('-timestamp').first()
        
        daily_change = Decimal('0')
        daily_change_percent = Decimal('0')
        
        if previous_data:
            daily_change = latest_data.close_price - previous_data.close_price
            if previous_data.close_price > 0:
                daily_change_percent = (daily_change / previous_data.close_price) * 100
        
        # Get fundamental data
        latest_fundamental = FundamentalData.objects.filter(
            instrument=instrument
        ).order_by('-period_end_date').first()
        
        summary_data = {
            'symbol': instrument.symbol,
            'last_price': latest_data.close_price,
            'daily_change': daily_change,
            'daily_change_percent': daily_change_percent,
            'volume': latest_data.volume,
            'high_52w': year_data['high_52w'],
            'low_52w': year_data['low_52w'],
            'market_cap': instrument.market_cap,
            'pe_ratio': latest_fundamental.pe_ratio if latest_fundamental else None
        }
        
        serializer = MarketDataSummarySerializer(summary_data)
        return Response(serializer.data)


class MarketDataViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing market data
    """
    serializer_class = MarketDataSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = MarketData.objects.all()
        
        # Filter by instrument
        symbol = self.request.query_params.get('symbol', None)
        if symbol:
            queryset = queryset.filter(instrument__symbol=symbol)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        # Filter by provider
        provider = self.request.query_params.get('provider', None)
        if provider:
            queryset = queryset.filter(provider__name=provider)
        
        return queryset.order_by('-timestamp')

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get latest market data for all instruments"""
        latest_data = []
        
        # Get symbols to include
        symbols = request.query_params.get('symbols', None)
        if symbols:
            symbol_list = symbols.split(',')
            instruments = Instrument.objects.filter(symbol__in=symbol_list)
        else:
            instruments = Instrument.objects.filter(is_active=True)[:20]  # Limit to 20 for performance
        
        for instrument in instruments:
            latest = MarketData.objects.filter(
                instrument=instrument
            ).order_by('-timestamp').first()
            
            if latest:
                latest_data.append(latest)
        
        serializer = MarketDataSerializer(latest_data, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def ohlc(self, request):
        """Get OHLC data for charting"""
        symbol = request.query_params.get('symbol')
        if not symbol:
            return Response({'error': 'Symbol parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        days = int(request.query_params.get('days', 30))
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        data = MarketData.objects.filter(
            instrument__symbol=symbol,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp').values(
            'timestamp', 'open_price', 'high_price', 'low_price', 'close_price', 'volume'
        )
        
        return Response(list(data))


class RiskMetricsViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing risk metrics
    """
    serializer_class = RiskMetricsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = RiskMetrics.objects.all()
        
        # Filter by instrument
        symbol = self.request.query_params.get('symbol', None)
        if symbol:
            queryset = queryset.filter(instrument__symbol=symbol)
        
        # Filter by date
        date = self.request.query_params.get('date', None)
        if date:
            queryset = queryset.filter(calculation_date=date)
        else:
            # Get latest calculations by default
            latest_date = RiskMetrics.objects.aggregate(
                latest=Max('calculation_date')
            )['latest']
            if latest_date:
                queryset = queryset.filter(calculation_date=latest_date)
        
        return queryset.order_by('-risk_score')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get risk metrics summary"""
        queryset = self.get_queryset()
        
        summary = queryset.aggregate(
            avg_volatility=Avg('volatility_1y'),
            avg_sharpe_ratio=Avg('sharpe_ratio_1y'),
            avg_risk_score=Avg('risk_score'),
            high_risk_count=Count('id', filter=Q(volatility_category='high')),
            low_risk_count=Count('id', filter=Q(volatility_category='low'))
        )
        
        # Top risky instruments
        high_risk = queryset.filter(risk_score__gte=70).order_by('-risk_score')[:10]
        low_risk = queryset.filter(risk_score__lte=30).order_by('risk_score')[:10]
        
        return Response({
            'summary': summary,
            'high_risk_instruments': RiskMetricsSerializer(high_risk, many=True).data,
            'low_risk_instruments': RiskMetricsSerializer(low_risk, many=True).data
        })


class DataProviderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing data providers and their status
    """
    queryset = DataProvider.objects.order_by('name')
    serializer_class = DataProviderSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=['get'])
    def quality_status(self, request, pk=None):
        """Get quality status for a data provider"""
        provider = self.get_object()
        
        # Get recent quality checks
        recent_checks = DataQualityCheck.objects.filter(
            provider=provider,
            checked_at__gte=timezone.now() - timedelta(days=7)
        ).order_by('-checked_at')
        
        # Calculate success rate
        total_checks = recent_checks.count()
        passed_checks = recent_checks.filter(status='passed').count()
        success_rate = (passed_checks / total_checks * 100) if total_checks > 0 else 0
        
        # Get latest check by type
        latest_checks = {}
        for check_type in ['completeness', 'accuracy', 'consistency', 'timeliness']:
            latest_check = recent_checks.filter(check_type=check_type).first()
            if latest_check:
                latest_checks[check_type] = DataQualityCheckSerializer(latest_check).data
        
        return Response({
            'provider': provider.name,
            'is_active': provider.is_active,
            'success_rate': success_rate,
            'total_checks_last_7_days': total_checks,
            'passed_checks_last_7_days': passed_checks,
            'latest_checks_by_type': latest_checks,
            'recent_checks': DataQualityCheckSerializer(recent_checks[:20], many=True).data
        })

    @action(detail=False, methods=['get'])
    def status_overview(self, request):
        """Get overview of all provider statuses"""
        providers = self.get_queryset()
        overview = []
        
        for provider in providers:
            # Get latest quality check
            latest_check = DataQualityCheck.objects.filter(
                provider=provider
            ).order_by('-checked_at').first()
            
            # Get recent success rate
            recent_checks = DataQualityCheck.objects.filter(
                provider=provider,
                checked_at__gte=timezone.now() - timedelta(days=1)
            )
            
            total_recent = recent_checks.count()
            passed_recent = recent_checks.filter(status='passed').count()
            success_rate = (passed_recent / total_recent * 100) if total_recent > 0 else 0
            
            overview.append({
                'name': provider.name,
                'is_active': provider.is_active,
                'latest_check': latest_check.checked_at if latest_check else None,
                'latest_status': latest_check.status if latest_check else None,
                'success_rate_24h': success_rate,
                'total_checks_24h': total_recent
            })
        
        return Response(overview)