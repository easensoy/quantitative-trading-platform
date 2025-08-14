from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd
from collections import defaultdict
import asyncio

from src.core.models import (
    Portfolio, Position, Fill, Instrument, Strategy, PnLAttribution,
    MarketData
)


@dataclass
class AttributionFactor:
    name: str
    value: float
    contribution: float
    percentage: float


@dataclass
class PositionPnL:
    instrument: Instrument
    position: Position
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    price_attribution: float
    fx_attribution: float
    carry_attribution: float
    other_attribution: float
    current_price: float
    previous_price: float


@dataclass
class StrategyPnL:
    strategy_id: str
    positions_pnl: List[PositionPnL]
    total_unrealized_pnl: float
    total_realized_pnl: float
    total_pnl: float
    attribution_factors: List[AttributionFactor]
    benchmark_pnl: float
    alpha: float


class PnLCalculator(ABC):
    @abstractmethod
    def calculate_position_pnl(
        self,
        position: Position,
        current_price: float,
        previous_price: float,
        fills: List[Fill]
    ) -> PositionPnL:
        pass


class BasicPnLCalculator(PnLCalculator):
    def calculate_position_pnl(
        self,
        position: Position,
        current_price: float,
        previous_price: float,
        fills: List[Fill]
    ) -> PositionPnL:
        unrealized_pnl = position.quantity * (current_price - position.avg_price)
        
        realized_pnl = sum(
            fill.quantity * (fill.price - position.avg_price)
            for fill in fills
            if fill.instrument.symbol == position.instrument.symbol
        )
        
        total_pnl = unrealized_pnl + realized_pnl
        
        price_attribution = position.quantity * (current_price - previous_price)
        
        return PositionPnL(
            instrument=position.instrument,
            position=position,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            price_attribution=price_attribution,
            fx_attribution=0.0,
            carry_attribution=0.0,
            other_attribution=total_pnl - price_attribution,
            current_price=current_price,
            previous_price=previous_price
        )


class AdvancedPnLCalculator(PnLCalculator):
    def __init__(self, risk_free_rate: float = 0.02):
        self.risk_free_rate = risk_free_rate

    def calculate_position_pnl(
        self,
        position: Position,
        current_price: float,
        previous_price: float,
        fills: List[Fill],
        fx_rate: float = 1.0,
        previous_fx_rate: float = 1.0,
        dividend_yield: float = 0.0
    ) -> PositionPnL:
        base_currency_quantity = position.quantity * fx_rate
        
        unrealized_pnl_local = position.quantity * (current_price - position.avg_price)
        unrealized_pnl = unrealized_pnl_local * fx_rate
        
        realized_pnl = sum(
            fill.quantity * (fill.price - position.avg_price) * fx_rate
            for fill in fills
            if fill.instrument.symbol == position.instrument.symbol
        )
        
        price_attribution = position.quantity * (current_price - previous_price) * fx_rate
        
        fx_attribution = position.quantity * previous_price * (fx_rate - previous_fx_rate)
        
        days_held = (datetime.utcnow() - position.timestamp).days
        carry_attribution = (
            position.quantity * previous_price * fx_rate *
            (dividend_yield - self.risk_free_rate) * (days_held / 365.25)
        )
        
        total_pnl = unrealized_pnl + realized_pnl
        other_attribution = total_pnl - price_attribution - fx_attribution - carry_attribution
        
        return PositionPnL(
            instrument=position.instrument,
            position=position,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            price_attribution=price_attribution,
            fx_attribution=fx_attribution,
            carry_attribution=carry_attribution,
            other_attribution=other_attribution,
            current_price=current_price,
            previous_price=previous_price
        )


class FactorAttributionEngine:
    def __init__(self):
        self.factor_models = {}
        self.risk_factors = ['market', 'size', 'value', 'momentum', 'quality', 'volatility']

    def calculate_factor_attribution(
        self,
        portfolio: Portfolio,
        factor_returns: pd.DataFrame,
        factor_exposures: pd.DataFrame,
        period_return: float
    ) -> List[AttributionFactor]:
        attribution_factors = []
        
        if factor_exposures.empty or factor_returns.empty:
            return attribution_factors
        
        portfolio_weights = self._calculate_portfolio_weights(portfolio)
        
        for factor in self.risk_factors:
            if factor in factor_exposures.columns and factor in factor_returns.columns:
                factor_exposure = self._calculate_portfolio_factor_exposure(
                    portfolio_weights, factor_exposures[factor]
                )
                
                factor_return = factor_returns[factor].iloc[-1] if len(factor_returns) > 0 else 0
                
                factor_contribution = factor_exposure * factor_return
                
                factor_percentage = (
                    (factor_contribution / period_return * 100)
                    if period_return != 0 else 0
                )
                
                attribution_factors.append(AttributionFactor(
                    name=factor,
                    value=factor_exposure,
                    contribution=factor_contribution,
                    percentage=factor_percentage
                ))
        
        return attribution_factors

    def _calculate_portfolio_weights(self, portfolio: Portfolio) -> pd.Series:
        total_value = sum(
            pos.quantity * pos.avg_price for pos in portfolio.positions.values()
        )
        
        if total_value == 0:
            return pd.Series(dtype=float)
        
        weights = {}
        for symbol, position in portfolio.positions.items():
            weights[symbol] = (position.quantity * position.avg_price) / total_value
        
        return pd.Series(weights)

    def _calculate_portfolio_factor_exposure(
        self,
        weights: pd.Series,
        factor_exposures: pd.Series
    ) -> float:
        common_assets = weights.index.intersection(factor_exposures.index)
        
        if len(common_assets) == 0:
            return 0.0
        
        aligned_weights = weights.loc[common_assets]
        aligned_exposures = factor_exposures.loc[common_assets]
        
        return (aligned_weights * aligned_exposures).sum()


class BrinsonAttributionEngine:
    def calculate_brinson_attribution(
        self,
        portfolio_weights: pd.Series,
        benchmark_weights: pd.Series,
        portfolio_returns: pd.Series,
        benchmark_returns: pd.Series,
        sector_mapping: Optional[Dict[str, str]] = None
    ) -> Dict[str, float]:
        if sector_mapping is None:
            sector_mapping = {asset: 'default_sector' for asset in portfolio_weights.index}
        
        sectors = list(set(sector_mapping.values()))
        
        results = {
            'allocation_effect': 0.0,
            'selection_effect': 0.0,
            'interaction_effect': 0.0,
            'total_active_return': 0.0,
            'sector_breakdown': {}
        }
        
        for sector in sectors:
            sector_assets = [asset for asset, sec in sector_mapping.items() if sec == sector]
            
            if not sector_assets:
                continue
            
            wp_sector = portfolio_weights.reindex(sector_assets, fill_value=0).sum()
            wb_sector = benchmark_weights.reindex(sector_assets, fill_value=0).sum()
            
            if wp_sector > 0:
                rp_sector = (
                    portfolio_weights.reindex(sector_assets, fill_value=0) *
                    portfolio_returns.reindex(sector_assets, fill_value=0)
                ).sum() / wp_sector
            else:
                rp_sector = 0
            
            if wb_sector > 0:
                rb_sector = (
                    benchmark_weights.reindex(sector_assets, fill_value=0) *
                    benchmark_returns.reindex(sector_assets, fill_value=0)
                ).sum() / wb_sector
            else:
                rb_sector = 0
            
            allocation_effect = (wp_sector - wb_sector) * rb_sector
            selection_effect = wb_sector * (rp_sector - rb_sector)
            interaction_effect = (wp_sector - wb_sector) * (rp_sector - rb_sector)
            
            results['allocation_effect'] += allocation_effect
            results['selection_effect'] += selection_effect
            results['interaction_effect'] += interaction_effect
            
            results['sector_breakdown'][sector] = {
                'allocation_effect': allocation_effect,
                'selection_effect': selection_effect,
                'interaction_effect': interaction_effect
            }
        
        results['total_active_return'] = (
            results['allocation_effect'] +
            results['selection_effect'] +
            results['interaction_effect']
        )
        
        return results


class RealTimePnLEngine:
    def __init__(self, pnl_calculator: Optional[PnLCalculator] = None):
        self.pnl_calculator = pnl_calculator or AdvancedPnLCalculator()
        self.factor_attribution = FactorAttributionEngine()
        self.brinson_attribution = BrinsonAttributionEngine()
        self.previous_prices: Dict[str, float] = {}
        self.previous_portfolio_values: Dict[str, float] = {}
        self.fills_cache: Dict[str, List[Fill]] = defaultdict(list)
        
    async def calculate_realtime_pnl(
        self,
        portfolio: Portfolio,
        current_market_data: Dict[str, MarketData],
        strategy_id: Optional[str] = None
    ) -> StrategyPnL:
        positions_pnl = []
        total_unrealized = 0.0
        total_realized = 0.0
        
        for symbol, position in portfolio.positions.items():
            if symbol in current_market_data:
                current_price = current_market_data[symbol].last or current_market_data[symbol].mid_price or 0
                previous_price = self.previous_prices.get(symbol, current_price)
                
                fills = self.fills_cache.get(position.instrument.symbol, [])
                
                position_pnl = self.pnl_calculator.calculate_position_pnl(
                    position, current_price, previous_price, fills
                )
                
                positions_pnl.append(position_pnl)
                total_unrealized += position_pnl.unrealized_pnl
                total_realized += position_pnl.realized_pnl
                
                self.previous_prices[symbol] = current_price
        
        total_pnl = total_unrealized + total_realized
        
        attribution_factors = []
        
        alpha = 0.0
        benchmark_pnl = 0.0
        
        strategy_pnl = StrategyPnL(
            strategy_id=strategy_id or "default",
            positions_pnl=positions_pnl,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            total_pnl=total_pnl,
            attribution_factors=attribution_factors,
            benchmark_pnl=benchmark_pnl,
            alpha=alpha
        )
        
        return strategy_pnl

    def add_fill(self, fill: Fill) -> None:
        self.fills_cache[fill.instrument.symbol].append(fill)

    def calculate_portfolio_attribution(
        self,
        portfolio: Portfolio,
        benchmark_portfolio: Portfolio,
        current_market_data: Dict[str, MarketData],
        factor_returns: Optional[pd.DataFrame] = None,
        factor_exposures: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        portfolio_weights = self._get_portfolio_weights(portfolio, current_market_data)
        benchmark_weights = self._get_portfolio_weights(benchmark_portfolio, current_market_data)
        
        portfolio_returns = self._calculate_returns(portfolio, current_market_data)
        benchmark_returns = self._calculate_returns(benchmark_portfolio, current_market_data)
        
        brinson_result = self.brinson_attribution.calculate_brinson_attribution(
            portfolio_weights, benchmark_weights, portfolio_returns, benchmark_returns
        )
        
        factor_attribution = []
        if factor_returns is not None and factor_exposures is not None:
            portfolio_return = (portfolio_weights * portfolio_returns).sum()
            factor_attribution = self.factor_attribution.calculate_factor_attribution(
                portfolio, factor_returns, factor_exposures, portfolio_return
            )
        
        return {
            'brinson_attribution': brinson_result,
            'factor_attribution': factor_attribution,
            'portfolio_weights': portfolio_weights.to_dict(),
            'benchmark_weights': benchmark_weights.to_dict()
        }

    def _get_portfolio_weights(
        self,
        portfolio: Portfolio,
        market_data: Dict[str, MarketData]
    ) -> pd.Series:
        total_value = 0.0
        position_values = {}
        
        for symbol, position in portfolio.positions.items():
            if symbol in market_data:
                current_price = market_data[symbol].last or market_data[symbol].mid_price or 0
                position_value = position.quantity * current_price
                position_values[symbol] = position_value
                total_value += position_value
        
        if total_value == 0:
            return pd.Series(dtype=float)
        
        weights = {symbol: value / total_value for symbol, value in position_values.items()}
        return pd.Series(weights)

    def _calculate_returns(
        self,
        portfolio: Portfolio,
        market_data: Dict[str, MarketData]
    ) -> pd.Series:
        returns = {}
        
        for symbol, position in portfolio.positions.items():
            if symbol in market_data:
                current_price = market_data[symbol].last or market_data[symbol].mid_price or 0
                previous_price = self.previous_prices.get(symbol, current_price)
                
                if previous_price > 0:
                    returns[symbol] = (current_price - previous_price) / previous_price
                else:
                    returns[symbol] = 0.0
        
        return pd.Series(returns)

    async def generate_pnl_report(
        self,
        strategy_pnl: StrategyPnL,
        time_period: str = "daily"
    ) -> Dict[str, Any]:
        report = {
            'timestamp': datetime.utcnow().isoformat(),
            'strategy_id': strategy_pnl.strategy_id,
            'time_period': time_period,
            'summary': {
                'total_pnl': strategy_pnl.total_pnl,
                'unrealized_pnl': strategy_pnl.total_unrealized_pnl,
                'realized_pnl': strategy_pnl.total_realized_pnl,
                'benchmark_pnl': strategy_pnl.benchmark_pnl,
                'alpha': strategy_pnl.alpha,
                'number_of_positions': len(strategy_pnl.positions_pnl)
            },
            'position_breakdown': [],
            'attribution_factors': []
        }
        
        for pos_pnl in strategy_pnl.positions_pnl:
            position_detail = {
                'symbol': pos_pnl.instrument.symbol,
                'quantity': pos_pnl.position.quantity,
                'avg_price': pos_pnl.position.avg_price,
                'current_price': pos_pnl.current_price,
                'unrealized_pnl': pos_pnl.unrealized_pnl,
                'realized_pnl': pos_pnl.realized_pnl,
                'total_pnl': pos_pnl.total_pnl,
                'attribution': {
                    'price': pos_pnl.price_attribution,
                    'fx': pos_pnl.fx_attribution,
                    'carry': pos_pnl.carry_attribution,
                    'other': pos_pnl.other_attribution
                }
            }
            report['position_breakdown'].append(position_detail)
        
        for factor in strategy_pnl.attribution_factors:
            factor_detail = {
                'name': factor.name,
                'value': factor.value,
                'contribution': factor.contribution,
                'percentage': factor.percentage
            }
            report['attribution_factors'].append(factor_detail)
        
        return report


class PnLMonitor:
    def __init__(self, pnl_engine: RealTimePnLEngine):
        self.pnl_engine = pnl_engine
        self.monitoring_tasks: Dict[str, asyncio.Task] = {}
        self.pnl_history: Dict[str, List[StrategyPnL]] = defaultdict(list)
        self.alerts_threshold = {
            'daily_loss_limit': -10000,
            'drawdown_limit': -0.05,
            'var_limit': -5000
        }

    async def start_monitoring(
        self,
        portfolio: Portfolio,
        market_data_stream: Any,
        strategy_id: str,
        update_frequency: timedelta = timedelta(seconds=30)
    ) -> None:
        if strategy_id in self.monitoring_tasks:
            await self.stop_monitoring(strategy_id)
        
        task = asyncio.create_task(
            self._monitor_loop(portfolio, market_data_stream, strategy_id, update_frequency)
        )
        self.monitoring_tasks[strategy_id] = task

    async def stop_monitoring(self, strategy_id: str) -> None:
        if strategy_id in self.monitoring_tasks:
            self.monitoring_tasks[strategy_id].cancel()
            try:
                await self.monitoring_tasks[strategy_id]
            except asyncio.CancelledError:
                pass
            del self.monitoring_tasks[strategy_id]

    async def _monitor_loop(
        self,
        portfolio: Portfolio,
        market_data_stream: Any,
        strategy_id: str,
        update_frequency: timedelta
    ) -> None:
        while True:
            try:
                current_market_data = await self._get_current_market_data(market_data_stream)
                
                strategy_pnl = await self.pnl_engine.calculate_realtime_pnl(
                    portfolio, current_market_data, strategy_id
                )
                
                self.pnl_history[strategy_id].append(strategy_pnl)
                
                await self._check_alerts(strategy_pnl, strategy_id)
                
                await asyncio.sleep(update_frequency.total_seconds())
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in PnL monitoring for {strategy_id}: {e}")
                await asyncio.sleep(update_frequency.total_seconds())

    async def _get_current_market_data(self, market_data_stream: Any) -> Dict[str, MarketData]:
        return {}

    async def _check_alerts(self, strategy_pnl: StrategyPnL, strategy_id: str) -> None:
        if strategy_pnl.total_pnl < self.alerts_threshold['daily_loss_limit']:
            await self._send_alert(
                f"Daily loss limit exceeded for {strategy_id}: {strategy_pnl.total_pnl}"
            )
        
        pnl_series = [pnl.total_pnl for pnl in self.pnl_history[strategy_id]]
        if len(pnl_series) > 1:
            peak = max(pnl_series)
            current = pnl_series[-1]
            drawdown = (current - peak) / peak if peak != 0 else 0
            
            if drawdown < self.alerts_threshold['drawdown_limit']:
                await self._send_alert(
                    f"Drawdown limit exceeded for {strategy_id}: {drawdown:.2%}"
                )

    async def _send_alert(self, message: str) -> None:
        print(f"ALERT: {message}")

    def get_pnl_history(self, strategy_id: str, lookback_days: int = 30) -> List[StrategyPnL]:
        if strategy_id not in self.pnl_history:
            return []
        
        cutoff_time = datetime.utcnow() - timedelta(days=lookback_days)
        
        return [
            pnl for pnl in self.pnl_history[strategy_id]
            if hasattr(pnl, 'timestamp') and pnl.timestamp >= cutoff_time
        ]


def create_pnl_calculator(calculator_type: str = "advanced") -> PnLCalculator:
    if calculator_type == "basic":
        return SimplePnLCalculator()
    elif calculator_type == "advanced":
        return AdvancedPnLCalculator()
    return AdvancedPnLCalculator()