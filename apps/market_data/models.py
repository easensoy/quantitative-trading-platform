from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid


class DataProvider(models.Model):
    name = models.CharField(max_length=50, unique=True)
    api_key = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    rate_limit_per_minute = models.IntegerField(default=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'data_providers'

    def __str__(self):
        return self.name


class Instrument(models.Model):
    ASSET_TYPE_CHOICES = [
        ('equity', 'Equity'),
        ('bond', 'Bond'),
        ('option', 'Option'),
        ('future', 'Future'),
        ('forex', 'Forex'),
        ('crypto', 'Cryptocurrency'),
        ('commodity', 'Commodity'),
    ]

    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPE_CHOICES)
    exchange = models.CharField(max_length=50)
    currency = models.CharField(max_length=3, default='USD')
    sector = models.CharField(max_length=100, blank=True)
    industry = models.CharField(max_length=100, blank=True)
    market_cap = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'instruments'
        indexes = [
            models.Index(fields=['symbol']),
            models.Index(fields=['asset_type']),
            models.Index(fields=['exchange']),
        ]

    def __str__(self):
        return f"{self.symbol} ({self.name})"


class MarketData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='market_data')
    provider = models.ForeignKey(DataProvider, on_delete=models.CASCADE)
    timestamp = models.DateTimeField()
    
    open_price = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    high_price = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    low_price = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    close_price = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    volume = models.BigIntegerField(validators=[MinValueValidator(0)])
    
    daily_return = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    volatility_30d = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    data_quality_score = models.DecimalField(
        max_digits=3, decimal_places=2, 
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        default=1.0
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'market_data'
        unique_together = [['instrument', 'timestamp', 'provider']]
        indexes = [
            models.Index(fields=['instrument', 'timestamp']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['provider']),
        ]
        ordering = ['-timestamp']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.high_price < self.low_price:
            raise ValidationError('High price cannot be less than low price')
        if self.high_price < max(self.open_price, self.close_price):
            raise ValidationError('High price must be >= open and close prices')
        if self.low_price > min(self.open_price, self.close_price):
            raise ValidationError('Low price must be <= open and close prices')

    def __str__(self):
        return f"{self.instrument.symbol} @ {self.timestamp}"


class TechnicalIndicator(models.Model):
    market_data = models.OneToOneField(MarketData, on_delete=models.CASCADE, related_name='technical_indicators')
    
    sma_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    sma_50 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    ema_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    bollinger_upper = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    bollinger_lower = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    rsi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    macd = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    volume_ratio = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    momentum_20d = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'technical_indicators'


class FundamentalData(models.Model):
    PERIOD_TYPE_CHOICES = [
        ('annual', 'Annual'),
        ('quarterly', 'Quarterly'),
        ('ttm', 'Trailing Twelve Months'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='fundamental_data')
    provider = models.ForeignKey(DataProvider, on_delete=models.CASCADE)
    
    period_end_date = models.DateField()
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPE_CHOICES)
    
    revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    net_income = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    total_assets = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    total_debt = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    shareholders_equity = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    
    eps = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    pe_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pb_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    debt_to_equity = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    roe = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fundamental_data'
        unique_together = [['instrument', 'period_end_date', 'period_type', 'provider']]
        indexes = [
            models.Index(fields=['instrument', 'period_end_date']),
            models.Index(fields=['period_end_date']),
        ]

    def __str__(self):
        return f"{self.instrument.symbol} {self.period_type} {self.period_end_date}"


class RiskMetrics(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='risk_metrics')
    calculation_date = models.DateField()
    
    volatility_30d = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    volatility_90d = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    volatility_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    avg_return_30d_annualized = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    avg_return_1y_annualized = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    sharpe_ratio_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    current_drawdown = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    max_drawdown_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    var_95_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    var_99_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    expected_shortfall_95 = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    beta_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    r_squared_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    information_ratio_1y = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    
    VOLATILITY_CATEGORY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
        ('unknown', 'Unknown'),
    ]
    volatility_category = models.CharField(max_length=10, choices=VOLATILITY_CATEGORY_CHOICES, default='unknown')
    
    BETA_CATEGORY_CHOICES = [
        ('defensive', 'Defensive'),
        ('market', 'Market'),
        ('aggressive', 'Aggressive'),
        ('unknown', 'Unknown'),
    ]
    beta_category = models.CharField(max_length=10, choices=BETA_CATEGORY_CHOICES, default='unknown')
    
    risk_score = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        null=True, blank=True
    )
    
    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'risk_metrics'
        unique_together = [['instrument', 'calculation_date']]
        indexes = [
            models.Index(fields=['instrument', 'calculation_date']),
            models.Index(fields=['calculation_date']),
        ]

    def __str__(self):
        return f"{self.instrument.symbol} Risk Metrics {self.calculation_date}"


class DataQualityCheck(models.Model):
    CHECK_TYPE_CHOICES = [
        ('completeness', 'Completeness'),
        ('accuracy', 'Accuracy'),
        ('consistency', 'Consistency'),
        ('timeliness', 'Timeliness'),
    ]

    STATUS_CHOICES = [
        ('passed', 'Passed'),
        ('warning', 'Warning'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(DataProvider, on_delete=models.CASCADE)
    check_type = models.CharField(max_length=20, choices=CHECK_TYPE_CHOICES)
    check_name = models.CharField(max_length=100)
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    score = models.DecimalField(
        max_digits=5, decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    
    threshold = models.DecimalField(max_digits=5, decimal_places=4)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'data_quality_checks'
        indexes = [
            models.Index(fields=['provider', 'checked_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.provider.name} - {self.check_name} ({self.status})"