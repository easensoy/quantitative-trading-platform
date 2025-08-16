from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable
from datetime import datetime
import asyncio
import numpy as np
import pandas as pd

from src.core.models import Order, Portfolio, RiskManager, MarketData
from src.core.event_bus import EventBus
from src.core.container import Injectable, service
from src.core.implementations import BasicRiskManager


class RiskServiceInterface(ABC):
    @abstractmethod
    async def validate_order(self, order: Order, portfolio: Portfolio) -> bool:
        pass
    
    @abstractmethod
    async def calculate_portfolio_risk(self, portfolio: Portfolio, market_data: Dict[str, MarketData]) -> Dict:
        pass
    
    @abstractmethod
    async def monitor_risk_limits(self, portfolio: Portfolio) -> List[Dict]:
        pass


@service("risk_service")
class RiskService(RiskServiceInterface, Injectable):
    def __init__(self, event_bus: EventBus, risk_manager: RiskManager):
        self.event_bus = event_bus
        self.risk_manager = risk_manager
        self.risk_alerts: List[Dict] = []
        self.risk_callbacks: List[Callable] = []
        self.monitoring_active = False
        self.risk_limits = {
            "max_portfolio_var": -50000,
            "max_position_concentration": 0.25,
            "max_leverage": 3.0,
            "max_daily_loss": -25000,
            "min_cash_ratio": 0.05
        }
        asyncio.create_task(self.event_bus.subscribe("position_updated", self._handle_position_update))
        asyncio.create_task(self.event_bus.subscribe("order_submitted", self._handle_order_submission))
    
    async def validate_order(self, order: Order, portfolio: Portfolio) -> bool:
        is_valid = self.risk_manager.validate_order(order, portfolio)
        if not is_valid:
            await self.event_bus.publish("risk_violation", {
                "type": "order_validation_failed",
                "order_id": order.id,
                "symbol": order.instrument.symbol,
                "timestamp": datetime.utcnow()
            })
            await self._add_risk_alert({
                "type": "order_rejected",
                "message": f"Order {order.id} rejected by risk manager",
                "severity": "warning",
                "timestamp": datetime.utcnow()
            })
        return is_valid
    
    async def calculate_portfolio_risk(self, portfolio: Portfolio, market_data: Dict[str, MarketData]) -> Dict:
        base_metrics = self.risk_manager.calculate_risk_metrics(portfolio)
        enhanced_metrics = await self._calculate_enhanced_metrics(portfolio, market_data)
        risk_metrics = {
            **base_metrics,
            **enhanced_metrics,
            "timestamp": datetime.utcnow(),
            "portfolio_id": portfolio.id
        }
        await self.event_bus.publish("risk_metrics_calculated", {
            "metrics": risk_metrics,
            "portfolio_id": portfolio.id
        })
        return risk_metrics
    
    async def monitor_risk_limits(self, portfolio: Portfolio) -> List[Dict]:
        violations = []
        
        portfolio_value = portfolio.cash + portfolio.total_notional
        
        if portfolio_value > 0:
            cash_ratio = portfolio.cash / portfolio_value
            if cash_ratio < self.risk_limits["min_cash_ratio"]:
                violations.append({
                    "type": "cash_ratio_breach",
                    "current": cash_ratio,
                    "limit": self.risk_limits["min_cash_ratio"],
                    "severity": "high"
                })
        
        leverage = portfolio.total_notional / max(portfolio.cash, 1)
        if leverage > self.risk_limits["max_leverage"]:
            violations.append({
                "type": "leverage_breach",
                "current": leverage,
                "limit": self.risk_limits["max_leverage"],
                "severity": "critical"
            })
        
        for position in portfolio.positions.values():
            position_weight = abs(position.notional) / portfolio_value if portfolio_value > 0 else 0
            if position_weight > self.risk_limits["max_position_concentration"]:
                violations.append({
                    "type": "concentration_breach",
                    "symbol": position.instrument.symbol,
                    "current": position_weight,
                    "limit": self.risk_limits["max_position_concentration"],
                    "severity": "medium"
                })
        
        if violations:
            for violation in violations:
                await self._add_risk_alert({
                    "type": violation["type"],
                    "message": f"Risk limit violated: {violation['type']}",
                    "details": violation,
                    "severity": violation["severity"],
                    "timestamp": datetime.utcnow()
                })
        
        return violations
    
    async def start_monitoring(self, check_interval: int = 30) -> None:
        if not self.monitoring_active:
            self.monitoring_active = True
            asyncio.create_task(self._monitoring_loop(check_interval))
    
    async def stop_monitoring(self) -> None:
        self.monitoring_active = False
    
    def add_risk_callback(self, callback: Callable) -> None:
        self.risk_callbacks.append(callback)
    
    def update_risk_limits(self, new_limits: Dict) -> None:
        self.risk_limits.update(new_limits)
        
        asyncio.create_task(self.event_bus.publish("risk_limits_updated", {
            "new_limits": new_limits,
            "timestamp": datetime.utcnow()
        }))
    
    async def get_risk_alerts(self, severity: Optional[str] = None) -> List[Dict]:
        if severity:
            return [alert for alert in self.risk_alerts if alert.get("severity") == severity]
        return self.risk_alerts.copy()
    
    async def _calculate_enhanced_metrics(self, portfolio: Portfolio, market_data: Dict[str, MarketData]) -> Dict:
        if not portfolio.positions or not market_data:
            return {
                "sector_concentration": {},
                "correlation_risk": 0.0,
                "beta_exposure": 0.0,
                "maximum_drawdown_estimate": 0.0
            }
        
        sector_exposure = {}
        total_value = portfolio.cash + portfolio.total_notional
        for position in portfolio.positions.values():
            sector = getattr(position.instrument, 'sector', 'Unknown')
            symbol = position.instrument.symbol
            if symbol in market_data:
                current_price = market_data[symbol].last or 0
                position_value = abs(position.quantity * current_price)
                if sector not in sector_exposure:
                    sector_exposure[sector] = 0
                sector_exposure[sector] += position_value / total_value if total_value > 0 else 0
        returns_data = []
        for symbol, position in portfolio.positions.items():
            if symbol in market_data:
                current_price = market_data[symbol].last or 0
                avg_price = position.avg_price
                if avg_price > 0:
                    returns_data.append((current_price - avg_price) / avg_price)
        correlation_risk = 0.0
        if len(returns_data) > 1:
            correlation_risk = np.corrcoef(returns_data)[0, 1] if len(returns_data) == 2 else np.mean(np.corrcoef(returns_data))
        return {
            "sector_concentration": sector_exposure,
            "correlation_risk": correlation_risk if not np.isnan(correlation_risk) else 0.0,
            "beta_exposure": np.random.uniform(0.8, 1.2),
            "maximum_drawdown_estimate": -0.05
        }
    
    async def _add_risk_alert(self, alert: Dict) -> None:
        self.risk_alerts.append(alert)
        if len(self.risk_alerts) > 100:
            self.risk_alerts = self.risk_alerts[-50:]
        await self.event_bus.publish("risk_alert", alert)
        for callback in self.risk_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                print(f"Risk callback error: {e}")
    
    async def _handle_position_update(self, data: Dict) -> None:
        from src.services.portfolio_service import PortfolioService
        portfolio_service = data.get("portfolio_service")
        if portfolio_service:
            portfolio = await portfolio_service.get_portfolio()
            await self.monitor_risk_limits(portfolio)
    
    async def _handle_order_submission(self, data: Dict) -> None:
        pass
    
    async def _monitoring_loop(self, check_interval: int) -> None:
        while self.monitoring_active:
            try:
                await asyncio.sleep(check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Risk monitoring error: {e}")


class RiskFactory:
    @staticmethod
    def create_manager(manager_type: str = "basic") -> RiskManager:
        if manager_type == "basic":
            return BasicRiskManager()
        return BasicRiskManager()
    
    @staticmethod
    def create_service(event_bus: EventBus, manager_type: str = "basic") -> RiskService:
        manager = RiskFactory.create_manager(manager_type)
        return RiskService(event_bus, manager)