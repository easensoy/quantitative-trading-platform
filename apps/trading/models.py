from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from apps.market_data.models import Instrument
import uuid
from decimal import Decimal


class TradingAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('paper', 'Paper Trading'),
        ('live', 'Live Trading'),
        ('backtest', 'Backtest'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trading_accounts')
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPE_CHOICES)
    
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2, validators=[MinValueValidator(0)])
    current_capital = models.DecimalField(max_digits=20, decimal_places=2, validators=[MinValueValidator(0)])
    available_capital = models.DecimalField(max_digits=20, decimal_places=2, validators=[MinValueValidator(0)])
    
    max_position_size = models.DecimalField(max_digits=20, decimal_places=2, validators=[MinValueValidator(0)])
    max_portfolio_risk = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.02'))
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'trading_accounts'

    def __str__(self):
        return f"{self.name} ({self.account_type})"


class Strategy(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('stopped', 'Stopped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    strategy_type = models.CharField(max_length=50)  # momentum, mean_reversion, arbitrage, etc.
    parameters = models.JSONField(default=dict)  # Strategy-specific parameters
    
    account = models.ForeignKey(TradingAccount, on_delete=models.CASCADE, related_name='strategies')
    instruments = models.ManyToManyField(Instrument, related_name='strategies')
    
    allocation_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, 
        validators=[MinValueValidator(0)],
        help_text="Percentage of account capital allocated to this strategy"
    )
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'strategies'

    def __str__(self):
        return f"{self.name} ({self.strategy_type})"


class Order(models.Model):
    SIDE_CHOICES = [
        ('buy', 'Buy'),
        ('sell', 'Sell'),
    ]

    ORDER_TYPE_CHOICES = [
        ('market', 'Market'),
        ('limit', 'Limit'),
        ('stop', 'Stop'),
        ('stop_limit', 'Stop Limit'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('partially_filled', 'Partially Filled'),
        ('filled', 'Filled'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(TradingAccount, on_delete=models.CASCADE, related_name='orders')
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name='orders', null=True, blank=True)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='orders')
    
    side = models.CharField(max_length=4, choices=SIDE_CHOICES)
    order_type = models.CharField(max_length=15, choices=ORDER_TYPE_CHOICES)
    
    quantity = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    filled_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    
    price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)  # For limit orders
    stop_price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)  # For stop orders
    
    avg_fill_price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    commission = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    submitted_at = models.DateTimeField(null=True, blank=True)
    filled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        indexes = [
            models.Index(fields=['account', 'status']),
            models.Index(fields=['instrument', 'created_at']),
            models.Index(fields=['strategy']),
        ]

    def __str__(self):
        return f"{self.side.upper()} {self.quantity} {self.instrument.symbol} @ {self.price or 'MARKET'}"


class Trade(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='trades')
    
    quantity = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    price = models.DecimalField(max_digits=15, decimal_places=4, validators=[MinValueValidator(0)])
    commission = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    
    execution_timestamp = models.DateTimeField()
    trade_id = models.CharField(max_length=100, unique=True)  # External trade ID from broker
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'trades'
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['execution_timestamp']),
        ]

    def __str__(self):
        return f"Trade {self.trade_id}: {self.quantity} @ {self.price}"


class Position(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(TradingAccount, on_delete=models.CASCADE, related_name='positions')
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name='positions')
    
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    avg_cost = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    unrealized_pnl = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    realized_pnl = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    
    market_value = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    last_price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'positions'
        unique_together = [['account', 'instrument']]
        indexes = [
            models.Index(fields=['account']),
            models.Index(fields=['instrument']),
        ]

    def __str__(self):
        return f"{self.account.name}: {self.quantity} {self.instrument.symbol}"


class PortfolioSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(TradingAccount, on_delete=models.CASCADE, related_name='snapshots')
    
    timestamp = models.DateTimeField()
    total_value = models.DecimalField(max_digits=20, decimal_places=2)
    cash_balance = models.DecimalField(max_digits=20, decimal_places=2)
    positions_value = models.DecimalField(max_digits=20, decimal_places=2)
    
    daily_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_pnl = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    leverage = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    exposure = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'portfolio_snapshots'
        unique_together = [['account', 'timestamp']]
        indexes = [
            models.Index(fields=['account', 'timestamp']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        return f"{self.account.name} Portfolio @ {self.timestamp}"


class BacktestResult(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name='backtest_results')
    
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.DecimalField(max_digits=20, decimal_places=2)
    final_capital = models.DecimalField(max_digits=20, decimal_places=2)
    
    total_return = models.DecimalField(max_digits=10, decimal_places=6)
    annualized_return = models.DecimalField(max_digits=10, decimal_places=6)
    volatility = models.DecimalField(max_digits=10, decimal_places=6)
    sharpe_ratio = models.DecimalField(max_digits=10, decimal_places=6)
    
    max_drawdown = models.DecimalField(max_digits=10, decimal_places=6)
    calmar_ratio = models.DecimalField(max_digits=10, decimal_places=6)
    
    total_trades = models.IntegerField()
    winning_trades = models.IntegerField()
    losing_trades = models.IntegerField()
    win_rate = models.DecimalField(max_digits=5, decimal_places=4)
    
    avg_trade_pnl = models.DecimalField(max_digits=15, decimal_places=4)
    avg_winning_trade = models.DecimalField(max_digits=15, decimal_places=4)
    avg_losing_trade = models.DecimalField(max_digits=15, decimal_places=4)
    
    metadata = models.JSONField(default=dict)  # Additional backtest metrics
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'backtest_results'

    def __str__(self):
        return f"Backtest {self.strategy.name}: {self.start_date} to {self.end_date}"