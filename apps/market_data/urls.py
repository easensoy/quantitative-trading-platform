from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'instruments', views.InstrumentViewSet, basename='instrument')
router.register(r'market-data', views.MarketDataViewSet, basename='marketdata')
router.register(r'risk-metrics', views.RiskMetricsViewSet, basename='riskmetrics')
router.register(r'providers', views.DataProviderViewSet, basename='dataprovider')

urlpatterns = [
    path('', include(router.urls)),
]