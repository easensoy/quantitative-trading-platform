from rest_framework import serializers
from .models import (
    Instrument, MarketData, TechnicalIndicator, FundamentalData,
    RiskMetrics, DataProvider, DataQualityCheck
)


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = [
            'symbol', 'name', 'asset_type', 'exchange', 'currency',
            'sector', 'industry', 'market_cap', 'is_active'
        ]


class DataProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataProvider
        fields = ['name', 'is_active', 'rate_limit_per_minute', 'created_at']


class TechnicalIndicatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = TechnicalIndicator
        fields = [
            'sma_20', 'sma_50', 'ema_20', 'bollinger_upper', 'bollinger_lower',
            'rsi', 'macd', 'volume_ratio', 'momentum_20d', 'calculated_at'
        ]


class MarketDataSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    technical_indicators = TechnicalIndicatorSerializer(read_only=True)
    
    class Meta:
        model = MarketData
        fields = [
            'id', 'instrument', 'instrument_symbol', 'provider', 'provider_name',
            'timestamp', 'open_price', 'high_price', 'low_price', 'close_price',
            'volume', 'daily_return', 'volatility_30d', 'data_quality_score',
            'technical_indicators', 'created_at'
        ]


class FundamentalDataSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    
    class Meta:
        model = FundamentalData
        fields = [
            'id', 'instrument', 'instrument_symbol', 'provider', 'provider_name',
            'period_end_date', 'period_type', 'revenue', 'net_income',
            'total_assets', 'total_debt', 'shareholders_equity', 'eps',
            'pe_ratio', 'pb_ratio', 'debt_to_equity', 'roe', 'created_at'
        ]


class RiskMetricsSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source='instrument.symbol', read_only=True)
    instrument_name = serializers.CharField(source='instrument.name', read_only=True)
    
    class Meta:
        model = RiskMetrics
        fields = [
            'id', 'instrument', 'instrument_symbol', 'instrument_name',
            'calculation_date', 'volatility_30d', 'volatility_90d', 'volatility_1y',
            'avg_return_30d_annualized', 'avg_return_1y_annualized',
            'sharpe_ratio_1y', 'current_drawdown', 'max_drawdown_1y',
            'var_95_1y', 'var_99_1y', 'expected_shortfall_95',
            'beta_1y', 'r_squared_1y', 'information_ratio_1y',
            'volatility_category', 'beta_category', 'risk_score', 'calculated_at'
        ]


class DataQualityCheckSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    
    class Meta:
        model = DataQualityCheck
        fields = [
            'id', 'provider', 'provider_name', 'check_type', 'check_name',
            'status', 'score', 'threshold', 'message', 'metadata', 'checked_at'
        ]


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