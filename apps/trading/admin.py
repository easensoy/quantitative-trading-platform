from django.contrib import admin
from django.db.models import Sum, Count, Avg
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
import json

from .models import (
    TradingAccount, Strategy, Order, Trade, Position,
    PortfolioSnapshot, BacktestResult
)


class PositionInline(admin.TabularInline):
    model = Position
    extra = 0
    readonly_fields = ['unrealized_pnl', 'realized_pnl', 'market_value', 'updated_at']
    fields = ['instrument', 'quantity', 'avg_cost', 'unrealized_pnl', 'realized_pnl', 'market_value']


class StrategyInline(admin.TabularInline):
    model = Strategy
    extra = 0
    readonly_fields = ['created_at']
    fields = ['name', 'strategy_type', 'allocation_percentage', 'status', 'created_at']


@admin.register(TradingAccount)
class TradingAccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'account_type', 'current_capital', 'pnl', 'position_count', 'is_active']
    list_filter = ['account_type', 'is_active', 'created_at']
    search_fields = ['name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PositionInline, StrategyInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'account_type', 'is_active')
        }),
        ('Capital Management', {
            'fields': ('initial_capital', 'current_capital', 'available_capital')
        }),
        ('Risk Parameters', {
            'fields': ('max_position_size', 'max_portfolio_risk')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def pnl(self, obj):
        pnl_value = obj.current_capital - obj.initial_capital
        color = 'green' if pnl_value >= 0 else 'red'
        return format_html(
            '<span style="color: {};">${:,.2f}</span>',
            color,
            pnl_value
        )
    pnl.short_description = 'P&L'
    
    def position_count(self, obj):
        return Position.objects.filter(account=obj, quantity__gt=0).count()
    position_count.short_description = 'Active Positions'


class OrderInline(admin.TabularInline):
    model = Order
    extra = 0
    readonly_fields = ['created_at', 'filled_at']
    fields = ['instrument', 'side', 'order_type', 'quantity', 'price', 'status', 'created_at']


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ['name', 'account', 'strategy_type', 'allocation_percentage', 'status', 'order_count', 'performance']
    list_filter = ['strategy_type', 'status', 'created_at']
    search_fields = ['name', 'description', 'account__name']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [OrderInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'strategy_type', 'account')
        }),
        ('Configuration', {
            'fields': ('parameters_display', 'allocation_percentage')
        }),
        ('Instruments', {
            'fields': ('instruments',)
        }),
        ('Status', {
            'fields': ('status', 'created_at', 'updated_at')
        }),
    )
    
    filter_horizontal = ['instruments']
    
    def parameters_display(self, obj):
        if obj.parameters:
            return format_html(
                '<pre>{}</pre>',
                json.dumps(obj.parameters, indent=2)
            )
        return 'No parameters'
    parameters_display.short_description = 'Parameters'
    
    def order_count(self, obj):
        return Order.objects.filter(strategy=obj).count()
    order_count.short_description = 'Orders'
    
    def performance(self, obj):
        backtest = BacktestResult.objects.filter(strategy=obj).order_by('-created_at').first()
        if backtest:
            color = 'green' if backtest.total_return >= 0 else 'red'
            return format_html(
                '<span style="color: {};">{:.2f}%</span>',
                color,
                backtest.total_return * 100
            )
        return 'No backtest'
    performance.short_description = 'Latest Performance'


class TradeInline(admin.TabularInline):
    model = Trade
    extra = 0
    readonly_fields = ['execution_timestamp', 'trade_id', 'created_at']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'account', 'instrument', 'side', 'order_type', 'quantity', 'price', 'status', 'created_at']
    list_filter = ['side', 'order_type', 'status', 'created_at', 'account__account_type']
    search_fields = ['id', 'instrument__symbol', 'account__name']
    date_hierarchy = 'created_at'
    readonly_fields = ['id', 'filled_quantity', 'avg_fill_price', 'commission', 'submitted_at', 'filled_at', 'created_at', 'updated_at']
    inlines = [TradeInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('id', 'account', 'strategy', 'instrument')
        }),
        ('Order Details', {
            'fields': ('side', 'order_type', 'quantity', 'price', 'stop_price')
        }),
        ('Execution', {
            'fields': ('filled_quantity', 'avg_fill_price', 'commission', 'status')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'submitted_at', 'filled_at', 'updated_at')
        }),
    )
    
    actions = ['cancel_orders']
    
    def cancel_orders(self, request, queryset):
        updated = queryset.filter(status__in=['pending', 'submitted']).update(status='cancelled')
        self.message_user(request, f'{updated} orders cancelled.')
    cancel_orders.short_description = 'Cancel selected orders'


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ['trade_id', 'order', 'instrument_symbol', 'quantity', 'price', 'commission', 'execution_timestamp']
    list_filter = ['execution_timestamp', 'order__side', 'order__account__account_type']
    search_fields = ['trade_id', 'order__instrument__symbol', 'order__account__name']
    date_hierarchy = 'execution_timestamp'
    readonly_fields = ['id', 'created_at']
    
    def instrument_symbol(self, obj):
        return obj.order.instrument.symbol
    instrument_symbol.short_description = 'Symbol'


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ['account', 'instrument', 'quantity', 'avg_cost', 'market_value', 'unrealized_pnl', 'pnl_percentage']
    list_filter = ['account', 'instrument__asset_type', 'updated_at']
    search_fields = ['account__name', 'instrument__symbol']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Position Information', {
            'fields': ('account', 'instrument', 'quantity', 'avg_cost')
        }),
        ('Current Valuation', {
            'fields': ('market_value', 'last_price')
        }),
        ('P&L', {
            'fields': ('unrealized_pnl', 'realized_pnl')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at')
        }),
    )
    
    def pnl_percentage(self, obj):
        if obj.avg_cost and obj.avg_cost > 0 and obj.quantity > 0:
            total_cost = obj.avg_cost * obj.quantity
            pnl_pct = (obj.unrealized_pnl / total_cost) * 100 if total_cost > 0 else 0
            color = 'green' if pnl_pct >= 0 else 'red'
            return format_html(
                '<span style="color: {};">{:.2f}%</span>',
                color,
                pnl_pct
            )
        return 'N/A'
    pnl_percentage.short_description = 'P&L %'


@admin.register(PortfolioSnapshot)
class PortfolioSnapshotAdmin(admin.ModelAdmin):
    list_display = ['account', 'timestamp', 'total_value', 'daily_pnl', 'total_pnl', 'leverage']
    list_filter = ['account', 'timestamp']
    search_fields = ['account__name']
    date_hierarchy = 'timestamp'
    readonly_fields = ['id', 'created_at']
    
    fieldsets = (
        ('Snapshot Information', {
            'fields': ('account', 'timestamp')
        }),
        ('Portfolio Values', {
            'fields': ('total_value', 'cash_balance', 'positions_value')
        }),
        ('Performance', {
            'fields': ('daily_pnl', 'total_pnl')
        }),
        ('Risk Metrics', {
            'fields': ('leverage', 'exposure')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at')
        }),
    )


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = ['strategy', 'start_date', 'end_date', 'total_return', 'sharpe_ratio', 'max_drawdown', 'total_trades']
    list_filter = ['strategy__strategy_type', 'start_date', 'end_date', 'created_at']
    search_fields = ['strategy__name', 'strategy__account__name']
    date_hierarchy = 'created_at'
    readonly_fields = ['id', 'created_at']
    
    fieldsets = (
        ('Backtest Information', {
            'fields': ('strategy', 'start_date', 'end_date')
        }),
        ('Capital', {
            'fields': ('initial_capital', 'final_capital')
        }),
        ('Returns', {
            'fields': ('total_return', 'annualized_return')
        }),
        ('Risk Metrics', {
            'fields': ('volatility', 'sharpe_ratio', 'max_drawdown', 'calmar_ratio')
        }),
        ('Trading Statistics', {
            'fields': ('total_trades', 'winning_trades', 'losing_trades', 'win_rate')
        }),
        ('Trade Analysis', {
            'fields': ('avg_trade_pnl', 'avg_winning_trade', 'avg_losing_trade')
        }),
        ('Additional Data', {
            'fields': ('metadata_display',),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('id', 'created_at')
        }),
    )
    
    def metadata_display(self, obj):
        if obj.metadata:
            return format_html(
                '<pre>{}</pre>',
                json.dumps(obj.metadata, indent=2)
            )
        return 'No additional data'
    metadata_display.short_description = 'Additional Metadata'