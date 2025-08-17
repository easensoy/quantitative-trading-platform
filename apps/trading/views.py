from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import (
    TradingAccount, Strategy, Order, Trade, Position, 
    PortfolioSnapshot, BacktestResult
)
from .serializers import (
    TradingAccountSerializer, StrategySerializer, OrderSerializer,
    TradeSerializer, PositionSerializer, PortfolioSnapshotSerializer,
    BacktestResultSerializer, OrderCreateSerializer, PortfolioSummarySerializer
)
from apps.market_data.models import Instrument, MarketData


class TradingAccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing trading accounts
    """
    serializer_class = TradingAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TradingAccount.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get portfolio summary for a trading account"""
        account = self.get_object()
        
        # Get latest snapshot
        latest_snapshot = PortfolioSnapshot.objects.filter(
            account=account
        ).order_by('-timestamp').first()
        
        if not latest_snapshot:
            return Response({
                'account_id': account.id,
                'account_name': account.name,
                'total_value': account.current_capital,
                'cash_balance': account.available_capital,
                'positions_value': Decimal('0'),
                'daily_pnl': Decimal('0'),
                'daily_pnl_percentage': Decimal('0'),
                'total_pnl': account.current_capital - account.initial_capital,
                'total_pnl_percentage': ((account.current_capital - account.initial_capital) / account.initial_capital * 100),
                'leverage': Decimal('1'),
                'exposure': Decimal('0'),
                'position_count': 0,
                'largest_position_symbol': None,
                'largest_position_value': None
            })
        
        # Get position details
        positions = Position.objects.filter(account=account, quantity__gt=0)
        position_count = positions.count()
        
        largest_position = positions.order_by('-market_value').first()
        
        summary_data = {
            'account_id': account.id,
            'account_name': account.name,
            'total_value': latest_snapshot.total_value,
            'cash_balance': latest_snapshot.cash_balance,
            'positions_value': latest_snapshot.positions_value,
            'daily_pnl': latest_snapshot.daily_pnl,
            'daily_pnl_percentage': (latest_snapshot.daily_pnl / latest_snapshot.total_value * 100) if latest_snapshot.total_value > 0 else Decimal('0'),
            'total_pnl': latest_snapshot.total_pnl,
            'total_pnl_percentage': (latest_snapshot.total_pnl / account.initial_capital * 100) if account.initial_capital > 0 else Decimal('0'),
            'leverage': latest_snapshot.leverage,
            'exposure': latest_snapshot.exposure,
            'position_count': position_count,
            'largest_position_symbol': largest_position.instrument.symbol if largest_position else None,
            'largest_position_value': largest_position.market_value if largest_position else None
        }
        
        serializer = PortfolioSummarySerializer(summary_data)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        """Get performance metrics for a trading account"""
        account = self.get_object()
        days = int(request.query_params.get('days', 30))
        
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        snapshots = PortfolioSnapshot.objects.filter(
            account=account,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp')
        
        if not snapshots.exists():
            return Response({'message': 'No performance data available'}, status=status.HTTP_404_NOT_FOUND)
        
        snapshot_data = list(snapshots.values(
            'timestamp', 'total_value', 'daily_pnl', 'total_pnl'
        ))
        
        # Calculate metrics
        total_return = ((snapshots.last().total_value - snapshots.first().total_value) / 
                       snapshots.first().total_value * 100) if snapshots.first().total_value > 0 else 0
        
        daily_returns = [float(s.daily_pnl / s.total_value) for s in snapshots if s.total_value > 0]
        
        if daily_returns:
            avg_daily_return = sum(daily_returns) / len(daily_returns)
            volatility = (sum([(r - avg_daily_return) ** 2 for r in daily_returns]) / len(daily_returns)) ** 0.5
            sharpe_ratio = (avg_daily_return * 252) / (volatility * (252 ** 0.5)) if volatility > 0 else 0
        else:
            avg_daily_return = 0
            volatility = 0
            sharpe_ratio = 0
        
        return Response({
            'period_days': days,
            'total_return_percentage': total_return,
            'average_daily_return': avg_daily_return * 100,
            'volatility': volatility * 100,
            'sharpe_ratio': sharpe_ratio,
            'snapshots': snapshot_data
        })


class StrategyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing trading strategies
    """
    serializer_class = StrategySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Strategy.objects.filter(account__user=self.request.user)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start a strategy"""
        strategy = self.get_object()
        strategy.status = 'active'
        strategy.save()
        return Response({'status': 'Strategy started'})

    @action(detail=True, methods=['post'])
    def stop(self, request, pk=None):
        """Stop a strategy"""
        strategy = self.get_object()
        strategy.status = 'stopped'
        strategy.save()
        return Response({'status': 'Strategy stopped'})

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        """Pause a strategy"""
        strategy = self.get_object()
        strategy.status = 'paused'
        strategy.save()
        return Response({'status': 'Strategy paused'})

    @action(detail=True, methods=['get'])
    def performance(self, request, pk=None):
        """Get performance metrics for a strategy"""
        strategy = self.get_object()
        
        # Get all orders for this strategy
        orders = Order.objects.filter(strategy=strategy, status='filled')
        
        if not orders.exists():
            return Response({'message': 'No completed orders for this strategy'})
        
        total_trades = orders.count()
        
        # Calculate PnL (simplified - would need more complex logic for real implementation)
        total_volume = orders.aggregate(total=Sum('quantity'))['total'] or 0
        avg_fill_price = orders.aggregate(avg=Avg('avg_fill_price'))['avg'] or 0
        
        # Get backtest results if available
        backtest_results = BacktestResult.objects.filter(strategy=strategy).order_by('-created_at').first()
        
        performance_data = {
            'total_trades': total_trades,
            'total_volume': total_volume,
            'average_fill_price': avg_fill_price,
            'backtest_results': BacktestResultSerializer(backtest_results).data if backtest_results else None
        }
        
        return Response(performance_data)


class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing orders
    """
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Order.objects.filter(account__user=self.request.user)
        
        # Filter by status
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by instrument
        symbol = self.request.query_params.get('symbol', None)
        if symbol:
            queryset = queryset.filter(instrument__symbol=symbol)
        
        # Filter by strategy
        strategy_id = self.request.query_params.get('strategy', None)
        if strategy_id:
            queryset = queryset.filter(strategy_id=strategy_id)
        
        return queryset.order_by('-created_at')

    @action(detail=False, methods=['post'])
    def create_order(self, request):
        """Create a new order with simplified interface"""
        serializer = OrderCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Get the default trading account for the user
            account = TradingAccount.objects.filter(user=request.user, is_active=True).first()
            if not account:
                return Response(
                    {'error': 'No active trading account found'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get instrument
            try:
                instrument = Instrument.objects.get(symbol=serializer.validated_data['symbol'])
            except Instrument.DoesNotExist:
                return Response(
                    {'error': f"Instrument {serializer.validated_data['symbol']} not found"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get strategy if provided
            strategy = None
            if serializer.validated_data.get('strategy_id'):
                try:
                    strategy = Strategy.objects.get(
                        id=serializer.validated_data['strategy_id'],
                        account__user=request.user
                    )
                except Strategy.DoesNotExist:
                    return Response(
                        {'error': 'Strategy not found'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Create order
            order = Order.objects.create(
                account=account,
                strategy=strategy,
                instrument=instrument,
                side=serializer.validated_data['side'],
                order_type=serializer.validated_data['order_type'],
                quantity=serializer.validated_data['quantity'],
                price=serializer.validated_data.get('price'),
                stop_price=serializer.validated_data.get('stop_price'),
                status='pending'
            )
            
            return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an order"""
        order = self.get_object()
        
        if order.status not in ['pending', 'submitted']:
            return Response(
                {'error': 'Can only cancel pending or submitted orders'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        order.status = 'cancelled'
        order.save()
        
        return Response({'status': 'Order cancelled'})


class PositionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing positions (read-only)
    """
    serializer_class = PositionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Position.objects.filter(account__user=self.request.user)
        
        # Filter by non-zero positions only by default
        if self.request.query_params.get('include_zero', 'false').lower() != 'true':
            queryset = queryset.exclude(quantity=0)
        
        # Filter by account
        account_id = self.request.query_params.get('account', None)
        if account_id:
            queryset = queryset.filter(account_id=account_id)
        
        return queryset.order_by('-market_value')

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get positions summary"""
        positions = self.get_queryset()
        
        total_value = positions.aggregate(total=Sum('market_value'))['total'] or 0
        total_pnl = positions.aggregate(total=Sum('unrealized_pnl'))['total'] or 0
        position_count = positions.count()
        
        # Top positions
        top_positions = positions.order_by('-market_value')[:5]
        
        return Response({
            'total_value': total_value,
            'total_unrealized_pnl': total_pnl,
            'position_count': position_count,
            'top_positions': PositionSerializer(top_positions, many=True).data
        })


class TradeViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing trade history (read-only)
    """
    serializer_class = TradeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Trade.objects.filter(order__account__user=self.request.user)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(execution_timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(execution_timestamp__lte=end_date)
        
        # Filter by instrument
        symbol = self.request.query_params.get('symbol', None)
        if symbol:
            queryset = queryset.filter(order__instrument__symbol=symbol)
        
        return queryset.order_by('-execution_timestamp')


class BacktestResultViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for viewing backtest results (read-only)
    """
    serializer_class = BacktestResultSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return BacktestResult.objects.filter(
            strategy__account__user=self.request.user
        ).order_by('-created_at')