from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
import pandas as pd
import numpy as np
from collections import defaultdict
import asyncio
from concurrent.futures import ThreadPoolExecutor

from src.core.models import (
    Instrument, Order, Fill, Position, Portfolio, Strategy,
    BacktestResult, OrderSide, OrderStatus, OrderType, Venue
)
from src.core.exceptions import BacktestError
from src.backtesting.market_impact import MarketImpactEngine
from src.core.config import get_config


@dataclass
class BacktestConfig:
    start_date: datetime
    end_date: datetime
    initial_capital: float
    commission: float = 0.001
    slippage: float = 0.0005
    market_impact_model: str = "sqrt"
    frequency: str = "1D"
    benchmark: Optional[str] = None


@dataclass
class ExecutionRecord:
    """One simulated fill with the reference price it was priced from.

    reference_price is the bar close the broker started from; fill_price already
    includes slippage, so slippage_cost is informational and must not be deducted
    from P&L a second time.
    """
    order_id: str
    trade_id: str
    symbol: str
    side: str
    quantity: int
    submitted_at: datetime
    filled_at: datetime
    reference_price: float
    fill_price: float
    commission: float

    @property
    def notional(self) -> float:
        return self.quantity * self.fill_price

    @property
    def slippage_cost(self) -> float:
        direction = 1 if self.side == OrderSide.BUY.value else -1
        return direction * (self.fill_price - self.reference_price) * self.quantity


@dataclass
class OrderRecord:
    """An order returned by the strategy, as accepted or rejected by the engine."""
    decided_at: datetime
    order: Order
    accepted: bool
    reason: Optional[str] = None


@dataclass
class LedgerEntry:
    """Portfolio state at the end of one bar, after fills and new orders."""
    timestamp: datetime
    cash: float
    equity: float
    quantities: Dict[str, int]
    marks: Dict[str, float]
    stale_marks: List[str]


@dataclass
class SimulatedMarketData:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    
    @property
    def mid_price(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.close
    
    @property
    def spread(self) -> Optional[float]:
        if self.bid and self.ask:
            return self.ask - self.bid
        return None


class SimulatedBroker:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.impact_engine = MarketImpactEngine(config.market_impact_model)
        self.pending_orders: Dict[str, Order] = {}
        self.filled_orders: List[Fill] = []
        self.executions: List[ExecutionRecord] = []
        self.submitted_at: Dict[str, datetime] = {}
        self.order_counter = 0

    def submit_order(self, order: Order, market_data: SimulatedMarketData) -> str:
        order.id = f"order_{self.order_counter}"
        self.order_counter += 1
        order.status = OrderStatus.SUBMITTED

        self.pending_orders[order.id] = order
        self.submitted_at[order.id] = market_data.timestamp
        return order.id
    
    def process_orders(self, market_data: SimulatedMarketData, symbol: Optional[str] = None) -> List[Fill]:
        """Try to fill pending orders against one bar.

        Pass the bar's symbol so only that instrument's orders are matched against it;
        without it, every pending order is priced from this bar (single-symbol use only).
        """
        fills = []
        orders_to_remove = []
        
        for order_id, order in self.pending_orders.items():
            if symbol is not None and order.instrument.symbol != symbol:
                continue
            fill = self._try_fill_order(order, market_data)
            if fill:
                fills.append(fill)
                self.filled_orders.append(fill)
                order.status = OrderStatus.FILLED
                order.filled_quantity = order.quantity
                order.avg_fill_price = fill.price
                orders_to_remove.append(order_id)
        
        for order_id in orders_to_remove:
            del self.pending_orders[order_id]
            
        return fills
    
    def _try_fill_order(self, order: Order, market_data: SimulatedMarketData) -> Optional[Fill]:
        fill_price = self._calculate_fill_price(order, market_data)
        if fill_price is None:
            return None
        
        commission = order.quantity * fill_price * self.config.commission
        trade_id = f"trade_{len(self.filled_orders)}"

        self.executions.append(ExecutionRecord(
            order_id=order.id,
            trade_id=trade_id,
            symbol=order.instrument.symbol,
            side=order.side.value,
            quantity=order.quantity,
            submitted_at=self.submitted_at.get(order.id, market_data.timestamp),
            filled_at=market_data.timestamp,
            reference_price=market_data.close,
            fill_price=fill_price,
            commission=commission,
        ))

        return Fill(
            order_id=order.id,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            timestamp=market_data.timestamp,
            venue=Venue.NYSE,
            trade_id=trade_id,
            commission=commission,
            strategy_id=order.strategy_id
        )
    
    def _calculate_fill_price(self, order: Order, market_data: SimulatedMarketData) -> Optional[float]:
        base_price = market_data.close
        
        if order.order_type == OrderType.MARKET:
            if order.side == OrderSide.BUY:
                fill_price = base_price * (1 + self.config.slippage)
            else:
                fill_price = base_price * (1 - self.config.slippage)
            
            return fill_price
            
        elif order.order_type == OrderType.LIMIT:
            if order.price is None:
                return None
                
            if order.side == OrderSide.BUY and base_price <= order.price:
                return min(order.price, base_price)
            elif order.side == OrderSide.SELL and base_price >= order.price:
                return max(order.price, base_price)
        
        return None


class PerformanceAnalyzer:
    @staticmethod
    def calculate_metrics(
        pnl_series: pd.Series,
        benchmark_series: Optional[pd.Series] = None,
        risk_free_rate: float = 0.02
    ) -> Dict[str, float]:
        if len(pnl_series) < 2:
            return {}
        
        returns = pnl_series.pct_change().dropna()
        
        if len(returns) == 0:
            return {}
        
        total_return = (pnl_series.iloc[-1] / pnl_series.iloc[0]) - 1
        
        annualized_return = (1 + total_return) ** (252 / len(returns)) - 1
        
        annualized_vol = returns.std() * np.sqrt(252)
        
        if annualized_vol > 0:
            sharpe_ratio = (annualized_return - risk_free_rate) / annualized_vol
        else:
            sharpe_ratio = 0
        
        running_max = pnl_series.expanding().max()
        drawdown = (pnl_series - running_max) / running_max
        max_drawdown = drawdown.min()
        
        positive_returns = returns[returns > 0]
        win_rate = len(positive_returns) / len(returns) if len(returns) > 0 else 0
        
        calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
        
        metrics = {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': annualized_vol,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'calmar_ratio': calmar_ratio,
            'win_rate': win_rate,
            'skewness': returns.skew(),
            'kurtosis': returns.kurtosis(),
            'var_95': returns.quantile(0.05),
            'cvar_95': returns[returns <= returns.quantile(0.05)].mean()
        }
        
        if benchmark_series is not None and len(benchmark_series) > 1:
            benchmark_returns = benchmark_series.pct_change().dropna()
            if len(benchmark_returns) > 0 and len(returns) == len(benchmark_returns):
                correlation = returns.corr(benchmark_returns)
                metrics['correlation_to_benchmark'] = correlation
                
                if benchmark_returns.std() > 0:
                    beta = returns.cov(benchmark_returns) / benchmark_returns.var()
                    metrics['beta'] = beta
                    
                    benchmark_annualized = (benchmark_returns.mean() + 1) ** 252 - 1
                    alpha = annualized_return - (risk_free_rate + beta * (benchmark_annualized - risk_free_rate))
                    metrics['alpha'] = alpha
        
        return metrics


class BacktestEngine:
    """Bar-by-bar simulation.

    Orders a strategy returns at bar t are filled by SimulatedBroker at the next bar of
    the same symbol (close price adjusted by slippage; limit orders only when marketable).
    Fills update both positions and cash, commissions included. Positions are valued at
    their symbol's latest close, carried forward over bars where the symbol has no data.
    No margin, financing or risk checks are applied, so a strategy can spend more cash
    than it has and cash earns no interest.

    After a run the engine exposes, for reporting: trades (fills), broker.executions
    (fills with reference prices), order_log (accepted and rejected orders with reasons),
    ledger (cash, equity, quantities and marks per bar) and strategy_errors.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.performance_analyzer = PerformanceAnalyzer()
        self._reset()

    def _reset(self) -> None:
        self.broker = SimulatedBroker(self.config)
        self.portfolio = Portfolio(
            id="backtest_portfolio",
            name="Backtest Portfolio",
            cash=self.config.initial_capital
        )
        self.equity_curve: List[float] = []
        self.timestamps: List[datetime] = []
        self.trades: List[Fill] = []
        self.positions_history: List[Position] = []
        self.order_log: List[OrderRecord] = []
        self.ledger: List[LedgerEntry] = []
        self.strategy_errors: List[tuple] = []
        self.last_marks: Dict[str, float] = {}
        
    async def run_backtest(
        self,
        strategy_func: Callable,
        market_data: Dict[str, pd.DataFrame],
        benchmark_data: Optional[pd.DataFrame] = None
    ) -> BacktestResult:
        if not market_data:
            raise BacktestError("No market data provided")

        # Each run starts from initial capital, so an engine can be reused.
        self._reset()
        
        all_timestamps = set()
        for df in market_data.values():
            all_timestamps.update(df.index)
        
        sorted_timestamps = sorted(all_timestamps)
        filtered_timestamps = [
            ts for ts in sorted_timestamps
            if self.config.start_date <= ts <= self.config.end_date
        ]
        
        if not filtered_timestamps:
            raise BacktestError("No data available for the specified date range")
        
        for timestamp in filtered_timestamps:
            await self._process_timestamp(timestamp, strategy_func, market_data)
        
        return self._generate_backtest_result(benchmark_data)
    
    async def _process_timestamp(
        self,
        timestamp: datetime,
        strategy_func: Callable,
        market_data: Dict[str, pd.DataFrame]
    ) -> None:
        current_market_data = {}
        
        for symbol, df in market_data.items():
            if timestamp in df.index:
                row = df.loc[timestamp]
                current_market_data[symbol] = SimulatedMarketData(
                    timestamp=timestamp,
                    open=row.get('open', row.get('Open', 0)),
                    high=row.get('high', row.get('High', 0)),
                    low=row.get('low', row.get('Low', 0)),
                    close=row.get('close', row.get('Close', 0)),
                    volume=int(row.get('volume', row.get('Volume', 0))),
                    bid=row.get('bid'),
                    ask=row.get('ask')
                )
        
        for symbol, bar in current_market_data.items():
            self.last_marks[symbol] = bar.close

        fills = []
        for symbol, market_data_point in current_market_data.items():
            batch_fills = self.broker.process_orders(market_data_point, symbol=symbol)
            fills.extend(batch_fills)

        for fill in fills:
            # apply_fill moves cash as well as positions; position-only updates made
            # every purchase look like a gain in the equity curve.
            self.portfolio.apply_fill(fill)
            self.trades.append(fill)

        try:
            new_orders = await strategy_func(timestamp, current_market_data, self.portfolio)

            for order in new_orders or []:
                reason = self._rejection_reason(order, current_market_data)
                if reason is None:
                    self.broker.submit_order(order, current_market_data[order.instrument.symbol])
                else:
                    order.status = OrderStatus.REJECTED
                self.order_log.append(OrderRecord(timestamp, order, reason is None, reason))
        except Exception as e:
            self.strategy_errors.append((timestamp, repr(e)))
            print(f"Strategy error at {timestamp}: {e}")

        portfolio_value = self._calculate_portfolio_value(current_market_data)
        self.equity_curve.append(portfolio_value)
        self.timestamps.append(timestamp)
        self.ledger.append(LedgerEntry(
            timestamp=timestamp,
            cash=self.portfolio.cash,
            equity=portfolio_value,
            quantities={s: p.quantity for s, p in self.portfolio.positions.items()},
            marks={s: self.last_marks.get(s, p.avg_price) for s, p in self.portfolio.positions.items()},
            stale_marks=[s for s in self.portfolio.positions if s not in current_market_data],
        ))

        # Copies, because positions are mutated in place by later fills.
        self.positions_history.extend(replace(pos) for pos in self.portfolio.positions.values())

    @staticmethod
    def _rejection_reason(order: Order, market_data: Dict[str, SimulatedMarketData]) -> Optional[str]:
        if order.quantity <= 0:
            return "non-positive quantity"
        if order.instrument.symbol not in market_data:
            # Previously these orders were dropped silently.
            return "no market data for symbol at decision time"
        return None

    def _calculate_portfolio_value(self, market_data: Dict[str, SimulatedMarketData]) -> float:
        """Cash plus positions at their latest close.

        A symbol without a bar at this timestamp (a halt or a gap in the data) keeps its
        last close; valuing it at zero would put a false drawdown in the equity curve.
        """
        total_value = self.portfolio.cash

        for symbol, position in self.portfolio.positions.items():
            current_price = self.last_marks.get(symbol)
            if current_price is None:
                current_price = position.avg_price
            total_value += position.quantity * current_price

        return total_value
    
    def _generate_backtest_result(self, benchmark_data: Optional[pd.DataFrame]) -> BacktestResult:
        if not self.equity_curve:
            raise BacktestError("No equity curve data available")
        
        pnl_series = pd.Series(self.equity_curve, index=self.timestamps)
        
        benchmark_series = None
        if benchmark_data is not None:
            benchmark_filtered = benchmark_data[
                (benchmark_data.index >= self.config.start_date) &
                (benchmark_data.index <= self.config.end_date)
            ]
            if not benchmark_filtered.empty:
                benchmark_series = benchmark_filtered.iloc[:, 0]
        
        metrics = self.performance_analyzer.calculate_metrics(
            pnl_series, benchmark_series, risk_free_rate=0.02
        )
        
        return BacktestResult(
            strategy_id="backtest_strategy",
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            initial_capital=self.config.initial_capital,
            final_capital=self.equity_curve[-1] if self.equity_curve else self.config.initial_capital,
            total_return=metrics.get('total_return', 0),
            sharpe_ratio=metrics.get('sharpe_ratio', 0),
            max_drawdown=metrics.get('max_drawdown', 0),
            win_rate=metrics.get('win_rate', 0),
            total_trades=len(self.trades),
            pnl_series=pnl_series,
            positions_history=self.positions_history
        )


class ParameterOptimizer:
    def __init__(self, backtest_engine: BacktestEngine):
        self.backtest_engine = backtest_engine
        
    async def optimize_parameters(
        self,
        strategy_func_factory: Callable,
        parameter_grid: Dict[str, List[Any]],
        market_data: Dict[str, pd.DataFrame],
        optimization_metric: str = "sharpe_ratio"
    ) -> Dict[str, Any]:
        best_params = None
        best_score = float('-inf')
        results = []
        
        param_combinations = self._generate_parameter_combinations(parameter_grid)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = []
            for params in param_combinations:
                strategy_func = strategy_func_factory(**params)
                task = asyncio.create_task(
                    self._run_single_optimization(strategy_func, market_data, params, optimization_metric)
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                continue
            
            score, params = result
            if score > best_score:
                best_score = score
                best_params = params
        
        return {
            'best_parameters': best_params,
            'best_score': best_score,
            'all_results': [r for r in results if not isinstance(r, Exception)]
        }
    
    async def _run_single_optimization(
        self,
        strategy_func: Callable,
        market_data: Dict[str, pd.DataFrame],
        params: Dict[str, Any],
        metric: str
    ) -> tuple[float, Dict[str, Any]]:
        try:
            result = await self.backtest_engine.run_backtest(strategy_func, market_data)
            
            if metric == "sharpe_ratio":
                score = result.sharpe_ratio
            elif metric == "total_return":
                score = result.total_return
            elif metric == "calmar_ratio":
                score = getattr(result, 'calmar_ratio', 0)
            else:
                score = result.sharpe_ratio
            
            return score, params
        except Exception as e:
            print(f"Optimization failed for params {params}: {e}")
            return float('-inf'), params
    
    def _generate_parameter_combinations(self, parameter_grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        import itertools
        
        keys = list(parameter_grid.keys())
        values = list(parameter_grid.values())
        
        combinations = []
        for combination in itertools.product(*values):
            param_dict = dict(zip(keys, combination))
            combinations.append(param_dict)
        
        return combinations