import asyncio
from typing import Dict, List, Optional, Callable
from datetime import datetime
import signal
import logging

from src.core.models import Instrument, Order, Portfolio, Strategy
from src.core.container import ServiceRegistry, Injectable
from src.services.application_service import TradingApplicationService, ApplicationFactory
from src.services.market_data_service import MarketDataService
from src.services.order_execution_service import OrderExecutionService
from src.services.portfolio_service import PortfolioService
from src.services.risk_service import RiskService
from src.services.strategy_service import StrategyService


class TradingOrchestrator(Injectable):
    def __init__(self):
        self.container = ServiceRegistry.get_container()
        self.application_service: Optional[TradingApplicationService] = None
        
        self.market_data_service: Optional[MarketDataService] = None
        self.order_execution_service: Optional[OrderExecutionService] = None
        self.portfolio_service: Optional[PortfolioService] = None
        self.risk_service: Optional[RiskService] = None
        self.strategy_service: Optional[StrategyService] = None
        
        self._running = False
        self.logger = logging.getLogger(__name__)
        
    async def initialize(self) -> None:
        self.application_service = ApplicationFactory.create_application()
        await self.application_service.initialize()
        
        self.market_data_service = self.container.get("market_data_service")
        self.order_execution_service = self.container.get("order_execution_service")
        self.portfolio_service = self.container.get("portfolio_service")
        self.risk_service = self.container.get("risk_service")
        self.strategy_service = self.container.get("strategy_service")
        
        self.logger.info("Orchestrator initialized with all services")
    
    async def add_instrument(self, symbol: str, asset_type: str = "equity", exchange: str = "NYSE") -> None:
        from src.core.models import AssetType
        asset_type_enum = AssetType.EQUITY if asset_type == "equity" else AssetType.EQUITY
        await self.application_service.add_instrument(symbol, asset_type_enum, exchange)
        
    async def add_strategy(self, strategy: Strategy, handler: Callable) -> None:
        await self.application_service.add_strategy(strategy, handler)
    
    async def get_system_status(self) -> Dict:
        if not self.application_service:
            return {"status": "not_initialized"}
        return await self.application_service.get_system_status()
    
    async def get_portfolio_summary(self) -> Dict:
        if not self.application_service:
            return {}
        return await self.application_service.get_portfolio_summary()
    
    async def submit_order(self, order: Order) -> Optional[str]:
        """Submit an order; returns None if the pre-trade risk check rejects it."""
        if not self.order_execution_service:
            return None
        # The application wires RiskService.validate_order into OrderExecutionService as a
        # pre-trade check, so orchestrator and strategy orders pass through the same gate.
        return await self.order_execution_service.submit_order(order)
    
    async def cancel_order(self, order_id: str) -> bool:
        if not self.order_execution_service:
            return False
        return await self.order_execution_service.cancel_order(order_id)
    
    async def pause_strategy(self, strategy_id: str) -> None:
        if self.strategy_service:
            await self.strategy_service.pause_strategy(strategy_id)
    
    async def resume_strategy(self, strategy_id: str) -> None:
        if self.strategy_service:
            await self.strategy_service.resume_strategy(strategy_id)
    
    async def get_active_strategies(self) -> List[Strategy]:
        if not self.strategy_service:
            return []
        return await self.strategy_service.get_active_strategies()
    
    async def emergency_stop(self) -> None:
        if self.application_service:
            await self.application_service.emergency_stop()
    
    async def run_backtest(self, strategy_func: Callable, market_data: Dict, config: Dict):
        from src.backtesting.engine import BacktestEngine, BacktestConfig
        
        backtest_config = BacktestConfig(
            start_date=config["start_date"],
            end_date=config["end_date"],
            initial_capital=config.get("initial_capital", 1000000)
        )
        
        engine = BacktestEngine(backtest_config)
        return await engine.run_backtest(strategy_func, market_data)
    
    async def start(self):
        if not self.application_service:
            await self.initialize()
        
        self._running = True
        self.logger.info("Trading orchestrator starting...")
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        await self.application_service.start()
    
    async def stop(self):
        self._running = False
        if self.application_service:
            await self.application_service.stop()
        self.logger.info("Trading orchestrator stopped")
    
    def _signal_handler(self, signum, frame):
        self.logger.info(f"Received signal {signum}")
        asyncio.create_task(self.stop())
    
