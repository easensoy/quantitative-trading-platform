from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from enum import Enum

from src.core.models import (
    Portfolio, Position, Instrument, FixedIncomeInstrument, CommodityInstrument,
    AssetType, MarketData, RiskManager
)


class RiskMetricType(Enum):
    VAR_95 = "var_95"
    VAR_99 = "var_99"
    EXPECTED_SHORTFALL = "expected_shortfall"
    MAXIMUM_DRAWDOWN = "maximum_drawdown"
    VOLATILITY = "volatility"
    BETA = "beta"
    CORRELATION = "correlation"
    CONCENTRATION = "concentration"


@dataclass
class RiskLimit:
    metric_type: RiskMetricType
    limit_value: float
    asset_type: Optional[AssetType] = None
    instrument_symbol: Optional[str] = None
    strategy_id: Optional[str] = None
    breach_count: int = 0
    last_breach: Optional[datetime] = None


@dataclass
class RiskMetric:
    metric_type: RiskMetricType
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    asset_type: Optional[AssetType] = None
    instrument_symbol: Optional[str] = None
    strategy_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class MultiAssetRiskManager(RiskManager):
    def __init__(self):
        self.risk_limits: List[RiskLimit] = []
        self.position_limits: Dict[str, float] = {}
        self.correlation_matrix: Optional[pd.DataFrame] = None
        self.volatility_estimates: Dict[str, float] = {}
        self.risk_metrics_history: List[RiskMetric] = []
    def add_risk_limit(self, limit: RiskLimit):
        self.risk_limits.append(limit)
    def validate_order(self, order, portfolio: Portfolio) -> bool:
        position_check = self._check_position_limits(order, portfolio)
        concentration_check = self._check_concentration_limits(order, portfolio)
        var_check = self._check_var_limits(order, portfolio)
        return position_check and concentration_check and var_check
    def calculate_risk_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        metrics = {}
        metrics.update(self._calculate_var_metrics(portfolio))
        metrics.update(self._calculate_concentration_metrics(portfolio))
        metrics.update(self._calculate_correlation_metrics(portfolio))
        metrics.update(self._calculate_asset_specific_metrics(portfolio))
        self._store_risk_metrics(metrics)
        self._check_limit_breaches(metrics)
        return metrics
    def _check_position_limits(self, order, portfolio: Portfolio) -> bool:
        symbol = order.instrument.symbol
        current_position = portfolio.get_position(symbol)
        current_quantity = current_position.quantity if current_position else 0
        new_quantity = current_quantity
        if order.side.value == "buy":
            new_quantity += order.quantity
        else:
            new_quantity -= order.quantity
        position_limit = self.position_limits.get(symbol, float('inf'))
        return abs(new_quantity) <= position_limit
    def _check_concentration_limits(self, order, portfolio: Portfolio) -> bool:
        total_portfolio_value = abs(portfolio.total_notional)
        if total_portfolio_value == 0:
            return True
        symbol = order.instrument.symbol
        order_value = order.quantity * order.price if order.price else 0
        current_position = portfolio.get_position(symbol)
        current_value = abs(current_position.notional) if current_position else 0
        if order.side.value == "buy":
            new_value = current_value + order_value
        else:
            new_value = max(0, current_value - order_value)
        concentration = new_value / max(total_portfolio_value, order_value)
        concentration_limit = self._get_concentration_limit(order.instrument.asset_type)
        return concentration <= concentration_limit
    def _get_concentration_limit(self, asset_type: AssetType) -> float:
        limits = {
            AssetType.EQUITY: 0.10,
            AssetType.BOND: 0.15,
            AssetType.GOVERNMENT_BOND: 0.20,
            AssetType.CORPORATE_BOND: 0.12,
            AssetType.COMMODITY: 0.08,
            AssetType.COMMODITY_FUTURE: 0.08,
            AssetType.FX: 0.15
        }
        return limits.get(asset_type, 0.05)
    def _check_var_limits(self, order, portfolio: Portfolio) -> bool:
        var_95 = self._calculate_portfolio_var(portfolio, confidence_level=0.95)
        var_limit = None
        for limit in self.risk_limits:
            if limit.metric_type == RiskMetricType.VAR_95:
                var_limit = limit.limit_value
                break
        if var_limit is None:
            return True
        return var_95 <= var_limit
    def _calculate_var_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        var_95 = self._calculate_portfolio_var(portfolio, confidence_level=0.95)
        var_99 = self._calculate_portfolio_var(portfolio, confidence_level=0.99)
        expected_shortfall = self._calculate_expected_shortfall(portfolio, confidence_level=0.95)
        return {
            "var_95": var_95,
            "var_99": var_99,
            "expected_shortfall_95": expected_shortfall
        }
    def _calculate_portfolio_var(self, portfolio: Portfolio, confidence_level: float = 0.95) -> float:
        positions_data = []
        for symbol, position in portfolio.positions.items():
            volatility = self.volatility_estimates.get(symbol, 0.20)
            position_value = abs(position.notional)
            positions_data.append({
                'symbol': symbol,
                'value': position_value,
                'volatility': volatility,
                'asset_type': position.instrument.asset_type
            })
        if not positions_data:
            return 0.0
        total_value = sum(pos['value'] for pos in positions_data)
        if total_value == 0:
            return 0.0
        portfolio_volatility = self._calculate_portfolio_volatility(positions_data)
        z_score = self._get_z_score(confidence_level)
        var = total_value * portfolio_volatility * z_score
        return var
    
    def _calculate_portfolio_volatility(self, positions_data: List[Dict]) -> float:
        if len(positions_data) <= 1:
            return positions_data[0]['volatility'] if positions_data else 0.0
        total_value = sum(pos['value'] for pos in positions_data)
        weights = [pos['value'] / total_value for pos in positions_data]
        volatilities = [pos['volatility'] for pos in positions_data]
        portfolio_variance = 0.0
        for i in range(len(positions_data)):
            for j in range(len(positions_data)):
                correlation = self._get_correlation(positions_data[i], positions_data[j])
                portfolio_variance += weights[i] * weights[j] * volatilities[i] * volatilities[j] * correlation
        return np.sqrt(max(portfolio_variance, 0.0))
    
    def _get_correlation(self, pos1: Dict, pos2: Dict) -> float:
        if pos1['symbol'] == pos2['symbol']:
            return 1.0
        if self.correlation_matrix is not None:
            if pos1['symbol'] in self.correlation_matrix.index and pos2['symbol'] in self.correlation_matrix.columns:
                return self.correlation_matrix.loc[pos1['symbol'], pos2['symbol']]
        return self._estimate_correlation_by_asset_type(pos1['asset_type'], pos2['asset_type'])
    
    def _estimate_correlation_by_asset_type(self, asset_type1: AssetType, asset_type2: AssetType) -> float:
        correlation_matrix = {
            (AssetType.EQUITY, AssetType.EQUITY): 0.7,
            (AssetType.EQUITY, AssetType.BOND): -0.2,
            (AssetType.EQUITY, AssetType.COMMODITY): 0.3,
            (AssetType.BOND, AssetType.BOND): 0.8,
            (AssetType.BOND, AssetType.COMMODITY): -0.1,
            (AssetType.COMMODITY, AssetType.COMMODITY): 0.5,
            (AssetType.GOVERNMENT_BOND, AssetType.CORPORATE_BOND): 0.7,
            (AssetType.COMMODITY_FUTURE, AssetType.COMMODITY): 0.9,
        }
        key1 = (asset_type1, asset_type2)
        key2 = (asset_type2, asset_type1)
        return correlation_matrix.get(key1, correlation_matrix.get(key2, 0.3))
    
    def _get_z_score(self, confidence_level: float) -> float:
        z_scores = {
            0.90: 1.28,
            0.95: 1.645,
            0.99: 2.326,
            0.999: 3.09
        }
        return z_scores.get(confidence_level, 1.645)
    
    def _calculate_expected_shortfall(self, portfolio: Portfolio, confidence_level: float = 0.95) -> float:
        var = self._calculate_portfolio_var(portfolio, confidence_level)
        adjustment_factor = 1.2 if confidence_level == 0.95 else 1.4
        return var * adjustment_factor
    
    def _calculate_concentration_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        total_value = abs(portfolio.total_notional)
        if total_value == 0:
            return {
                "max_position_concentration": 0.0,
                "top_5_concentration": 0.0,
                "herfindahl_index": 0.0
            }
        position_weights = []
        asset_type_concentrations = {}
        for symbol, position in portfolio.positions.items():
            weight = abs(position.notional) / total_value
            position_weights.append(weight)
            asset_type = position.instrument.asset_type
            if asset_type not in asset_type_concentrations:
                asset_type_concentrations[asset_type] = 0.0
            asset_type_concentrations[asset_type] += weight
        max_concentration = max(position_weights) if position_weights else 0.0
        sorted_weights = sorted(position_weights, reverse=True)
        top_5_concentration = sum(sorted_weights[:5])
        herfindahl_index = sum(w ** 2 for w in position_weights)
        return {
            "max_position_concentration": max_concentration,
            "top_5_concentration": top_5_concentration,
            "herfindahl_index": herfindahl_index,
            **{f"{asset_type.value}_concentration": conc for asset_type, conc in asset_type_concentrations.items()}
        }
    
    def _calculate_correlation_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        symbols = list(portfolio.positions.keys())
        if len(symbols) < 2:
            return {"average_correlation": 0.0}
        correlations = []
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                pos1_data = {
                    'symbol': symbols[i],
                    'asset_type': portfolio.positions[symbols[i]].instrument.asset_type
                }
                pos2_data = {
                    'symbol': symbols[j],
                    'asset_type': portfolio.positions[symbols[j]].instrument.asset_type
                }
                correlation = self._get_correlation(pos1_data, pos2_data)
                correlations.append(correlation)
        average_correlation = np.mean(correlations) if correlations else 0.0
        return {"average_correlation": average_correlation}
    
    def _calculate_asset_specific_metrics(self, portfolio: Portfolio) -> Dict[str, float]:
        metrics = {}
        fi_positions = []
        commodity_positions = []
        for symbol, position in portfolio.positions.items():
            if isinstance(position.instrument, FixedIncomeInstrument):
                fi_positions.append(position)
            elif isinstance(position.instrument, CommodityInstrument):
                commodity_positions.append(position)
        if fi_positions:
            metrics.update(self._calculate_fixed_income_risk_metrics(fi_positions))
        if commodity_positions:
            metrics.update(self._calculate_commodity_risk_metrics(commodity_positions))
        return metrics
    
    def _calculate_fixed_income_risk_metrics(self, positions: List[Position]) -> Dict[str, float]:
        if not positions:
            return {}
        total_value = sum(abs(pos.notional) for pos in positions)
        if total_value == 0:
            return {}
        weighted_duration = 0.0
        weighted_convexity = 0.0
        credit_exposure = 0.0
        for position in positions:
            if isinstance(position.instrument, FixedIncomeInstrument):
                weight = abs(position.notional) / total_value
                duration = getattr(position.instrument, 'duration', 5.0) or 5.0
                convexity = getattr(position.instrument, 'convexity', 25.0) or 25.0
                weighted_duration += weight * duration
                weighted_convexity += weight * convexity
                if not position.instrument.is_government:
                    credit_exposure += weight
        dv01 = total_value * weighted_duration / 10000
        return {
            "fixed_income_duration": weighted_duration,
            "fixed_income_convexity": weighted_convexity,
            "fixed_income_dv01": dv01,
            "credit_exposure": credit_exposure
        }
    
    def _calculate_commodity_risk_metrics(self, positions: List[Position]) -> Dict[str, float]:
        if not positions:
            return {}
        
        total_value = sum(abs(pos.notional) for pos in positions)
        energy_exposure = 0.0
        metals_exposure = 0.0
        agriculture_exposure = 0.0
        for position in positions:
            if isinstance(position.instrument, CommodityInstrument):
                weight = abs(position.notional) / total_value
                if position.instrument.is_energy:
                    energy_exposure += weight
                elif position.instrument.is_metals:
                    metals_exposure += weight
                elif position.instrument.is_agriculture:
                    agriculture_exposure += weight
        return {
            "commodity_energy_exposure": energy_exposure,
            "commodity_metals_exposure": metals_exposure,
            "commodity_agriculture_exposure": agriculture_exposure
        }
    
    def _store_risk_metrics(self, metrics: Dict[str, float]):
        timestamp = datetime.utcnow()
        for metric_name, value in metrics.items():
            risk_metric = RiskMetric(
                metric_type=RiskMetricType(metric_name) if metric_name in [rm.value for rm in RiskMetricType] else None,
                value=value,
                timestamp=timestamp,
                metadata={'metric_name': metric_name}
            )
            self.risk_metrics_history.append(risk_metric)
        cutoff_time = datetime.utcnow() - timedelta(days=30)
        self.risk_metrics_history = [
            metric for metric in self.risk_metrics_history 
            if metric.timestamp > cutoff_time
        ]
    
    def _check_limit_breaches(self, metrics: Dict[str, float]):
        for limit in self.risk_limits:
            metric_key = limit.metric_type.value
            if metric_key in metrics:
                current_value = metrics[metric_key]
                if current_value > limit.limit_value:
                    limit.breach_count += 1
                    limit.last_breach = datetime.utcnow()
                    print(f"RISK LIMIT BREACH: {limit.metric_type.value} = {current_value:.4f} exceeds limit {limit.limit_value:.4f}")
    
    def get_risk_report(self, portfolio: Portfolio) -> Dict:
        metrics = self.calculate_risk_metrics(portfolio)
        breached_limits = [
            {
                'metric': limit.metric_type.value,
                'current_value': metrics.get(limit.metric_type.value, 0),
                'limit_value': limit.limit_value,
                'breach_count': limit.breach_count,
                'last_breach': limit.last_breach
            }
            for limit in self.risk_limits
            if limit.breach_count > 0
        ]
        return {
            'timestamp': datetime.utcnow(),
            'portfolio_value': portfolio.total_notional,
            'risk_metrics': metrics,
            'breached_limits': breached_limits,
            'position_count': len(portfolio.positions),
            'asset_allocation': self._get_asset_allocation(portfolio)
        }
    
    def _get_asset_allocation(self, portfolio: Portfolio) -> Dict[str, float]:
        total_value = abs(portfolio.total_notional)
        if total_value == 0:
            return {}
        allocation = {}
        for symbol, position in portfolio.positions.items():
            asset_type = position.instrument.asset_type.value
            weight = abs(position.notional) / total_value
            if asset_type not in allocation:
                allocation[asset_type] = 0.0
            allocation[asset_type] += weight
        return allocation
    
    def update_volatility_estimates(self, market_data: Dict[str, MarketData]):
        for symbol, data in market_data.items():
            if hasattr(data, 'volatility_estimate'):
                self.volatility_estimates[symbol] = data.volatility_estimate
            else:
                self.volatility_estimates[symbol] = self._estimate_volatility_by_asset_type(
                    data.instrument.asset_type
                )
    
    def _estimate_volatility_by_asset_type(self, asset_type: AssetType) -> float:
        volatilities = {
            AssetType.EQUITY: 0.20,
            AssetType.BOND: 0.05,
            AssetType.GOVERNMENT_BOND: 0.03,
            AssetType.CORPORATE_BOND: 0.08,
            AssetType.COMMODITY: 0.30,
            AssetType.COMMODITY_FUTURE: 0.35,
            AssetType.FX: 0.12
        }
        
        return volatilities.get(asset_type, 0.20)


class ScenarioAnalyzer:
    def __init__(self, risk_manager: MultiAssetRiskManager):
        self.risk_manager = risk_manager
        
    def run_stress_test(self, portfolio: Portfolio, scenario: Dict[str, float]) -> Dict:
        original_volatilities = self.risk_manager.volatility_estimates.copy()
        try:
            for symbol, shock in scenario.items():
                if symbol in self.risk_manager.volatility_estimates:
                    self.risk_manager.volatility_estimates[symbol] *= (1 + shock)
            stressed_metrics = self.risk_manager.calculate_risk_metrics(portfolio)
            self.risk_manager.volatility_estimates = original_volatilities
            base_metrics = self.risk_manager.calculate_risk_metrics(portfolio)
            return {
                'scenario': scenario,
                'base_metrics': base_metrics,
                'stressed_metrics': stressed_metrics,
                'impact': {
                    metric: stressed_metrics.get(metric, 0) - base_metrics.get(metric, 0)
                    for metric in base_metrics.keys()
                }
            }
        finally:
            self.risk_manager.volatility_estimates = original_volatilities
    
    def run_historical_simulation(self, portfolio: Portfolio, historical_returns: pd.DataFrame) -> Dict:
        portfolio_returns = []
        for _, day_returns in historical_returns.iterrows():
            daily_pnl = 0.0
            total_value = abs(portfolio.total_notional)
            for symbol, position in portfolio.positions.items():
                if symbol in day_returns:
                    position_return = day_returns[symbol]
                    position_pnl = position.notional * position_return
                    daily_pnl += position_pnl
            if total_value > 0:
                portfolio_return = daily_pnl / total_value
                portfolio_returns.append(portfolio_return)
        if not portfolio_returns:
            return {'var_95': 0, 'var_99': 0, 'max_drawdown': 0}
        portfolio_returns = np.array(portfolio_returns)
        var_95 = np.percentile(portfolio_returns, 5) * abs(portfolio.total_notional)
        var_99 = np.percentile(portfolio_returns, 1) * abs(portfolio.total_notional)
        cumulative_returns = np.cumprod(1 + portfolio_returns)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        max_drawdown = np.min(drawdown)
        return {
            'historical_var_95': abs(var_95),
            'historical_var_99': abs(var_99),
            'max_drawdown': abs(max_drawdown),
            'volatility': np.std(portfolio_returns) * np.sqrt(252),
            'sharpe_ratio': np.mean(portfolio_returns) / np.std(portfolio_returns) * np.sqrt(252) if np.std(portfolio_returns) > 0 else 0
        }