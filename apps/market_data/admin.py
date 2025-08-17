from django.contrib import admin
from django.db.models import Count, Avg
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
import json

from .models import (
    DataProvider, Instrument, MarketData, TechnicalIndicator,
    FundamentalData, RiskMetrics, DataQualityCheck
)


@admin.register(DataProvider)
class DataProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'rate_limit_per_minute', 'data_count', 'latest_update', 'quality_status']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
    
    def data_count(self, obj):
        return MarketData.objects.filter(provider=obj).count()
    data_count.short_description = 'Data Points'
    
    def latest_update(self, obj):
        latest = MarketData.objects.filter(provider=obj).order_by('-created_at').first()
        return latest.created_at if latest else 'No data'
    latest_update.short_description = 'Latest Update'
    
    def quality_status(self, obj):
        latest_check = DataQualityCheck.objects.filter(provider=obj).order_by('-checked_at').first()
        if latest_check:
            color = 'green' if latest_check.status == 'passed' else 'red' if latest_check.status == 'failed' else 'orange'
            return format_html(
                '<span style="color: {};">{}</span>',
                color,
                latest_check.status.upper()
            )
        return 'No checks'
    quality_status.short_description = 'Quality Status'


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'name', 'asset_type', 'exchange', 'sector', 'is_active', 'data_points', 'latest_price']
    list_filter = ['asset_type', 'exchange', 'sector', 'is_active']
    search_fields = ['symbol', 'name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('symbol', 'name', 'asset_type', 'exchange', 'currency')
        }),
        ('Classification', {
            'fields': ('sector', 'industry', 'market_cap')
        }),
        ('Status', {
            'fields': ('is_active', 'created_at', 'updated_at')
        }),
    )
    
    def data_points(self, obj):
        return MarketData.objects.filter(instrument=obj).count()
    data_points.short_description = 'Data Points'
    
    def latest_price(self, obj):
        latest = MarketData.objects.filter(instrument=obj).order_by('-timestamp').first()
        return f"${latest.close_price}" if latest else 'No data'
    latest_price.short_description = 'Latest Price'


class TechnicalIndicatorInline(admin.StackedInline):
    model = TechnicalIndicator
    extra = 0
    readonly_fields = ['calculated_at']


@admin.register(MarketData)
class MarketDataAdmin(admin.ModelAdmin):
    list_display = ['instrument', 'provider', 'timestamp', 'close_price', 'volume', 'daily_return', 'quality_score']
    list_filter = ['provider', 'timestamp', 'data_quality_score', 'instrument__asset_type']
    search_fields = ['instrument__symbol', 'instrument__name']
    date_hierarchy = 'timestamp'
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines = [TechnicalIndicatorInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('instrument', 'provider', 'timestamp')
        }),
        ('Price Data', {
            'fields': ('open_price', 'high_price', 'low_price', 'close_price', 'volume')
        }),
        ('Calculated Fields', {
            'fields': ('daily_return', 'volatility_30d', 'data_quality_score')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at')
        }),
    )
    
    def quality_score(self, obj):
        score = float(obj.data_quality_score)
        color = 'green' if score >= 0.8 else 'orange' if score >= 0.6 else 'red'
        return format_html(
            '<span style="color: {};">{:.2f}</span>',
            color,
            score
        )
    quality_score.short_description = 'Quality Score'


@admin.register(FundamentalData)
class FundamentalDataAdmin(admin.ModelAdmin):
    list_display = ['instrument', 'provider', 'period_end_date', 'period_type', 'revenue', 'eps', 'pe_ratio']
    list_filter = ['provider', 'period_type', 'period_end_date']
    search_fields = ['instrument__symbol', 'instrument__name']
    date_hierarchy = 'period_end_date'
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('instrument', 'provider', 'period_end_date', 'period_type')
        }),
        ('Financial Statements', {
            'fields': ('revenue', 'net_income', 'total_assets', 'total_debt', 'shareholders_equity')
        }),
        ('Ratios', {
            'fields': ('eps', 'pe_ratio', 'pb_ratio', 'debt_to_equity', 'roe')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at')
        }),
    )


@admin.register(RiskMetrics)
class RiskMetricsAdmin(admin.ModelAdmin):
    list_display = ['instrument', 'calculation_date', 'volatility_1y', 'sharpe_ratio_1y', 'risk_score', 'risk_category']
    list_filter = ['calculation_date', 'volatility_category', 'beta_category']
    search_fields = ['instrument__symbol', 'instrument__name']
    date_hierarchy = 'calculation_date'
    readonly_fields = ['id', 'calculated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('instrument', 'calculation_date')
        }),
        ('Volatility Metrics', {
            'fields': ('volatility_30d', 'volatility_90d', 'volatility_1y', 'volatility_category')
        }),
        ('Return Metrics', {
            'fields': ('avg_return_30d_annualized', 'avg_return_1y_annualized', 'sharpe_ratio_1y')
        }),
        ('Drawdown Metrics', {
            'fields': ('current_drawdown', 'max_drawdown_1y')
        }),
        ('Risk Metrics', {
            'fields': ('var_95_1y', 'var_99_1y', 'expected_shortfall_95')
        }),
        ('Market Relationship', {
            'fields': ('beta_1y', 'beta_category', 'r_squared_1y', 'information_ratio_1y')
        }),
        ('Overall Assessment', {
            'fields': ('risk_score',)
        }),
        ('Metadata', {
            'fields': ('id', 'calculated_at')
        }),
    )
    
    def risk_category(self, obj):
        score = float(obj.risk_score or 0)
        if score >= 70:
            color, category = 'red', 'HIGH'
        elif score >= 40:
            color, category = 'orange', 'MEDIUM'
        else:
            color, category = 'green', 'LOW'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            category
        )
    risk_category.short_description = 'Risk Category'


@admin.register(DataQualityCheck)
class DataQualityCheckAdmin(admin.ModelAdmin):
    list_display = ['provider', 'check_type', 'check_name', 'status', 'score', 'threshold', 'checked_at']
    list_filter = ['provider', 'check_type', 'status', 'checked_at']
    search_fields = ['provider__name', 'check_name']
    date_hierarchy = 'checked_at'
    readonly_fields = ['id', 'checked_at']
    
    fieldsets = (
        ('Check Information', {
            'fields': ('provider', 'check_type', 'check_name')
        }),
        ('Results', {
            'fields': ('status', 'score', 'threshold', 'message')
        }),
        ('Details', {
            'fields': ('metadata_display',),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('id', 'checked_at')
        }),
    )
    
    def metadata_display(self, obj):
        if obj.metadata:
            return format_html(
                '<pre>{}</pre>',
                json.dumps(obj.metadata, indent=2)
            )
        return 'No metadata'
    metadata_display.short_description = 'Metadata'


@admin.register(TechnicalIndicator)
class TechnicalIndicatorAdmin(admin.ModelAdmin):
    list_display = ['market_data', 'sma_20', 'sma_50', 'rsi', 'bollinger_signal', 'calculated_at']
    list_filter = ['calculated_at', 'market_data__instrument__asset_type']
    search_fields = ['market_data__instrument__symbol']
    date_hierarchy = 'calculated_at'
    readonly_fields = ['calculated_at']
    
    def bollinger_signal(self, obj):
        if obj.bollinger_upper and obj.bollinger_lower and obj.market_data:
            price = float(obj.market_data.close_price)
            upper = float(obj.bollinger_upper)
            lower = float(obj.bollinger_lower)
            
            if price > upper:
                return format_html('<span style="color: red;">OVERBOUGHT</span>')
            elif price < lower:
                return format_html('<span style="color: green;">OVERSOLD</span>')
            else:
                return format_html('<span style="color: blue;">NEUTRAL</span>')
        return 'N/A'
    bollinger_signal.short_description = 'Bollinger Signal'


# Admin site customization
admin.site.site_header = "QuantCore Trading Platform"
admin.site.site_title = "QuantCore Admin"
admin.site.index_title = "QuantCore Administration"