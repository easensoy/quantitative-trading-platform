from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from apps.trading.views import (
    TradingAccountViewSet, StrategyViewSet, OrderViewSet,
    PositionViewSet, TradeViewSet, BacktestResultViewSet
)

# API Router
router = DefaultRouter()
router.register(r'accounts', TradingAccountViewSet, basename='tradingaccount')
router.register(r'strategies', StrategyViewSet, basename='strategy')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'positions', PositionViewSet, basename='position')
router.register(r'trades', TradeViewSet, basename='trade')
router.register(r'backtests', BacktestResultViewSet, basename='backtestresult')

urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    
    # API Routes
    path('api/v1/', include(router.urls)),
    path('api/v1/auth/', include('rest_framework.urls')),
    
    # App-specific URLs
    path('api/v1/market-data/', include('apps.market_data.urls')),
]