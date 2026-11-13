from rest_framework import serializers
from decimal import Decimal
from .models import (
    TradingAccount, Strategy, Order, Trade, Position, 
    PortfolioSnapshot, BacktestResult
)
from apps.market_data.models import Instrument


# Named apart from apps.market_data.serializers.InstrumentSerializer: the OpenAPI schema
# derives component names from class names, and two "Instrument" components collide.
class StrategyInstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ['symbol', 'name', 'asset_type', 'exchange', 'currency', 'sector', 'industry']


class TradingAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = TradingAccount
        fields = [
            'id', 'name', 'account_type', 'initial_capital', 'current_capital',
            'available_capital', 'max_position_size', 'max_portfolio_risk',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


def _request_user(serializer):
    request = serializer.context.get('request')
    user = getattr(request, 'user', None)
    return user if user is not None and user.is_authenticated else None


class StrategySerializer(serializers.ModelSerializer):
    instruments = StrategyInstrumentSerializer(many=True, read_only=True)
    instrument_symbols = serializers.ListField(
        child=serializers.CharField(max_length=20),
        write_only=True,
        required=False
    )

    def get_fields(self):
        fields = super().get_fields()
        user = _request_user(self)
        if user is not None:
            # Only the requesting user's accounts are valid targets.
            fields['account'].queryset = TradingAccount.objects.filter(user=user)
        return fields

    class Meta:
        model = Strategy
        fields = [
            'id', 'name', 'description', 'strategy_type', 'parameters',
            'account', 'instruments', 'instrument_symbols', 'allocation_percentage',
            'status', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def create(self, validated_data):
        instrument_symbols = validated_data.pop('instrument_symbols', [])
        strategy = Strategy.objects.create(**validated_data)
        
        if instrument_symbols:
            instruments = Instrument.objects.filter(symbol__in=instrument_symbols)
            strategy.instruments.set(instruments)
        
        return strategy

    def update(self, instance, validated_data):
        instrument_symbols = validated_data.pop('instrument_symbols', None)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if instrument_symbols is not None:
            instruments = Instrument.objects.filter(symbol__in=instrument_symbols)
            instance.instruments.set(instruments)
        
        return instance


class OrderSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)
    strategy_name = serializers.CharField(source='strategy.name', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'account', 'strategy', 'instrument', 'instrument_symbol',
            'strategy_name', 'side', 'order_type', 'quantity', 'filled_quantity',
            'price', 'stop_price', 'avg_fill_price', 'commission', 'status',
            'submitted_at', 'filled_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'filled_quantity', 'avg_fill_price', 'commission',
            'submitted_at', 'filled_at', 'created_at', 'updated_at'
        ]

    def get_fields(self):
        fields = super().get_fields()
        user = _request_user(self)
        if user is not None:
            # Orders may only reference the requesting user's accounts and strategies.
            fields['account'].queryset = TradingAccount.objects.filter(user=user)
            fields['strategy'].queryset = Strategy.objects.filter(account__user=user)
        return fields

    def validate(self, data):
        # Partial updates (PATCH) omit unchanged fields; fall back to the stored values.
        def current(field):
            return data[field] if field in data else getattr(self.instance, field, None)

        order_type = current('order_type')
        if order_type in ['limit', 'stop_limit'] and not current('price'):
            raise serializers.ValidationError("Price is required for limit orders")
        
        if order_type in ['stop', 'stop_limit'] and not current('stop_price'):
            raise serializers.ValidationError("Stop price is required for stop orders")
        
        quantity = current('quantity')
        if quantity is not None and quantity <= 0:
            raise serializers.ValidationError("Quantity must be positive")
        
        return data


class TradeSerializer(serializers.ModelSerializer):
    order_id = serializers.CharField(source='order.id', read_only=True)
    instrument_symbol = serializers.CharField(source='order.instrument.symbol', read_only=True)
    
    class Meta:
        model = Trade
        fields = [
            'id', 'order', 'order_id', 'instrument_symbol', 'quantity',
            'price', 'commission', 'execution_timestamp', 'trade_id', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class PositionSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)
    instrument_name = serializers.CharField(source='instrument.name', read_only=True)
    
    class Meta:
        model = Position
        fields = [
            'id', 'account', 'instrument', 'instrument_symbol', 'instrument_name',
            'quantity', 'avg_cost', 'unrealized_pnl', 'realized_pnl',
            'market_value', 'last_price', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class PortfolioSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioSnapshot
        fields = [
            'id', 'account', 'timestamp', 'total_value', 'cash_balance',
            'positions_value', 'daily_pnl', 'total_pnl', 'leverage',
            'exposure', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class BacktestResultSerializer(serializers.ModelSerializer):
    strategy_name = serializers.CharField(source='strategy.name', read_only=True)
    
    class Meta:
        model = BacktestResult
        fields = [
            'id', 'strategy', 'strategy_name', 'start_date', 'end_date',
            'initial_capital', 'final_capital', 'total_return', 'annualized_return',
            'volatility', 'sharpe_ratio', 'max_drawdown', 'calmar_ratio',
            'total_trades', 'winning_trades', 'losing_trades', 'win_rate',
            'avg_trade_pnl', 'avg_winning_trade', 'avg_losing_trade',
            'metadata', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class OrderCreateSerializer(serializers.Serializer):
    """Simplified serializer for creating orders via API"""
    symbol = serializers.CharField(max_length=20)
    side = serializers.ChoiceField(choices=['buy', 'sell'])
    order_type = serializers.ChoiceField(choices=['market', 'limit', 'stop', 'stop_limit'])
    quantity = serializers.DecimalField(max_digits=15, decimal_places=4, min_value=0.0001)
    price = serializers.DecimalField(max_digits=15, decimal_places=4, required=False, allow_null=True)
    stop_price = serializers.DecimalField(max_digits=15, decimal_places=4, required=False, allow_null=True)
    strategy_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, data):
        if data['order_type'] in ['limit', 'stop_limit'] and not data.get('price'):
            raise serializers.ValidationError("Price is required for limit orders")
        
        if data['order_type'] in ['stop', 'stop_limit'] and not data.get('stop_price'):
            raise serializers.ValidationError("Stop price is required for stop orders")
        
        return data


class PortfolioSummarySerializer(serializers.Serializer):
    """Summary serializer for portfolio overview"""
    account_id = serializers.UUIDField()
    account_name = serializers.CharField()
    total_value = serializers.DecimalField(max_digits=20, decimal_places=2)
    cash_balance = serializers.DecimalField(max_digits=20, decimal_places=2)
    positions_value = serializers.DecimalField(max_digits=20, decimal_places=2)
    daily_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    daily_pnl_percentage = serializers.DecimalField(max_digits=10, decimal_places=4)
    total_pnl = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_pnl_percentage = serializers.DecimalField(max_digits=10, decimal_places=4)
    leverage = serializers.DecimalField(max_digits=10, decimal_places=4)
    exposure = serializers.DecimalField(max_digits=20, decimal_places=2)
    position_count = serializers.IntegerField()
    largest_position_symbol = serializers.CharField(allow_null=True)
    largest_position_value = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)


class MarketDataSummarySerializer(serializers.Serializer):
    """Summary serializer for market data overview"""
    symbol = serializers.CharField()
    last_price = serializers.DecimalField(max_digits=15, decimal_places=4)
    daily_change = serializers.DecimalField(max_digits=15, decimal_places=4)
    daily_change_percent = serializers.DecimalField(max_digits=10, decimal_places=4)
    volume = serializers.IntegerField()
    high_52w = serializers.DecimalField(max_digits=15, decimal_places=4, allow_null=True)
    low_52w = serializers.DecimalField(max_digits=15, decimal_places=4, allow_null=True)
    market_cap = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    pe_ratio = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)