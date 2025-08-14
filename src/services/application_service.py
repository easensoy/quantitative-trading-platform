from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from datetime import datetime
import asyncio
import logging

from src.core.models import Instrument, AssetType, Strategy
from src.core.event_bus import EventBus
from src.core.container import ServiceRegistry, Injectable, service
from src.core.config import get_config

from src.services.market_data_service import MarketDataService, MarketDataFactory
from src.services.order_execution_service import OrderExecutionService, OrderExecutionFactory  
from src.services.portfolio_service import PortfolioService, PortfolioFactory
from src.services.risk_service import RiskService, RiskFactory
from src.services.strategy_service import StrategyService, StrategyFactory


class ApplicationServiceInterface(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        pass
    
    @abstractmethod
    async def start(self) -> None:
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        pass
    
    @abstractmethod
    async def get_system_status(self) -> Dict:
        pass


@service("application_service")
class TradingApplicationService(ApplicationServiceInterface, Injectable):
    def __init__(self):
        self.config = get_config()
        self.container = ServiceRegistry.get_container()
        self.event_bus: Optional[EventBus] = None
        
        self.market_data_service: Optional[MarketDataService] = None
        self.order_execution_service: Optional[OrderExecutionService] = None
        self.portfolio_service: Optional[PortfolioService] = None
        self.risk_service: Optional[RiskService] = None
        self.strategy_service: Optional[StrategyService] = None
        
        self.running = False
        self.startup_time: Optional[datetime] = None
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    async def initialize(self) -> None:
        self.logger.info("Initializing Trading Application...")
        
        from src.core.event_bus import create_event_bus
        self.event_bus = create_event_bus()
        self.container.register_singleton("event_bus", self.event_bus)
        
        self.market_data_service = MarketDataFactory.create_service(
            self.event_bus, 
            self.config.get("market_data", {}).get("provider", "simulated")
        )
        self.container.register_singleton("market_data_service", self.market_data_service)
        
        self.order_execution_service = OrderExecutionFactory.create_service(
            self.event_bus,
            "basic"
        )
        self.container.register_singleton("order_execution_service", self.order_execution_service)
        
        initial_capital = self.config.get("initial_capital", 1000000)
        self.portfolio_service = PortfolioFactory.create_service(
            self.event_bus,
            initial_capital
        )
        self.container.register_singleton("portfolio_service", self.portfolio_service)
        
        self.risk_service = RiskFactory.create_service(self.event_bus, "basic")
        self.container.register_singleton("risk_service", self.risk_service)
        
        self.strategy_service = StrategyFactory.create_service(self.event_bus)
        self.container.register_singleton("strategy_service", self.strategy_service)
        
        await self._setup_service_interactions()
        
        self.logger.info("Trading Application initialized successfully")
    
    async def start(self) -> None:
        if not self.event_bus:
            await self.initialize()
        
        self.logger.info("Starting Trading Application...")
        self.startup_time = datetime.utcnow()
        self.running = True
        
        await self.market_data_service.start_streaming()
        await self.risk_service.start_monitoring(30)
        
        await self._setup_default_instruments()
        await self._setup_default_strategies()
        
        self.logger.info("Trading Application started successfully")
        
        await self._run_main_loop()
    
    async def stop(self) -> None:
        self.logger.info("Stopping Trading Application...")
        self.running = False
        
        if self.market_data_service:
            await self.market_data_service.stop_streaming()
        
        if self.risk_service:
            await self.risk_service.stop_monitoring()
        
        self.logger.info("Trading Application stopped")
    
    async def get_system_status(self) -> Dict:
        if not self.running:
            return {"status": "stopped"}
        
        portfolio = await self.portfolio_service.get_portfolio()
        market_data = self.market_data_service.latest_data
        
        portfolio_metrics = await self.portfolio_service.get_portfolio_metrics(market_data)
        strategy_summary = await self.strategy_service.get_strategy_summary()
        order_metrics = await self.order_execution_service.get_order_metrics()
        
        uptime = (datetime.utcnow() - self.startup_time).total_seconds() if self.startup_time else 0
        
        return {
            "status": "running",
            "uptime_seconds": uptime,
            "startup_time": self.startup_time.isoformat() if self.startup_time else None,
            "portfolio": portfolio_metrics,
            "strategies": strategy_summary,
            "orders": order_metrics,
            "market_data": {
                "symbols_subscribed": len(self.market_data_service.subscribed_instruments),
                "latest_data_count": len(market_data)
            },
            "risk": {
                "monitoring_active": self.risk_service.monitoring_active,
                "alerts_count": len(await self.risk_service.get_risk_alerts())
            }
        }
    
    async def add_instrument(self, symbol: str, asset_type: AssetType = AssetType.EQUITY, exchange: str = "NYSE") -> None:
        instrument = Instrument(symbol=symbol, asset_type=asset_type, exchange=exchange)
        await self.market_data_service.subscribe_to_instruments([instrument])
        
        self.logger.info(f"Added instrument: {symbol}")
    
    async def add_strategy(self, strategy: Strategy, handler) -> None:
        await self.strategy_service.register_strategy(strategy, handler)
        self.logger.info(f"Added strategy: {strategy.name}")
    
    async def get_portfolio_summary(self) -> Dict:
        portfolio = await self.portfolio_service.get_portfolio()
        market_data = self.market_data_service.latest_data
        
        return {
            "portfolio_value": await self.portfolio_service.calculate_portfolio_value(market_data),
            "cash": portfolio.cash,
            "positions": await self.portfolio_service.get_position_summary(market_data),
            "metrics": await self.portfolio_service.get_portfolio_metrics(market_data)
        }
    
    async def get_risk_summary(self) -> Dict:
        portfolio = await self.portfolio_service.get_portfolio()
        market_data = self.market_data_service.latest_data
        
        risk_metrics = await self.risk_service.calculate_portfolio_risk(portfolio, market_data)
        risk_alerts = await self.risk_service.get_risk_alerts()
        violations = await self.risk_service.monitor_risk_limits(portfolio)
        
        return {
            "metrics": risk_metrics,
            "alerts": risk_alerts[-10:],
            "violations": violations
        }
    
    async def emergency_stop(self) -> None:
        self.logger.critical("EMERGENCY STOP TRIGGERED")
        
        active_orders = await self.order_execution_service.get_active_orders()
        for order in active_orders:
            await self.order_execution_service.cancel_order(order.id)
        
        strategies = await self.strategy_service.get_active_strategies()
        for strategy in strategies:
            await self.strategy_service.pause_strategy(strategy.id)
        
        await self.event_bus.publish("emergency_stop", {
            "timestamp": datetime.utcnow(),
            "cancelled_orders": len(active_orders),
            "paused_strategies": len(strategies)
        })
        
        self.logger.critical("Emergency stop completed")
    
    async def _setup_service_interactions(self) -> None:
        self.order_execution_service.add_fill_callback(self.portfolio_service.update_position)
        
        async def risk_validation_callback(order, portfolio):
            return await self.risk_service.validate_order(order, portfolio)
        
        self.portfolio_service.add_value_callback(self._handle_portfolio_value_change)
        self.risk_service.add_risk_callback(self._handle_risk_alert)
        self.strategy_service.add_strategy_callback(self._handle_strategy_event)
    
    async def _setup_default_instruments(self) -> None:
        default_instruments = [
            Instrument("AAPL", AssetType.EQUITY, "NASDAQ"),
            Instrument("GOOGL", AssetType.EQUITY, "NASDAQ"), 
            Instrument("MSFT", AssetType.EQUITY, "NASDAQ"),
            Instrument("TSLA", AssetType.EQUITY, "NASDAQ"),
            Instrument("SPY", AssetType.EQUITY, "NYSE")
        ]
        
        await self.market_data_service.subscribe_to_instruments(default_instruments)
        self.logger.info(f"Subscribed to {len(default_instruments)} default instruments")
    
    async def _setup_default_strategies(self) -> None:
        from src.core.models import Order, OrderSide, OrderType
        
        async def momentum_handler(market_data, portfolio):
            orders = []
            if hasattr(market_data, 'last') and market_data.last:
                price = market_data.last
                
                if price > 105:
                    order = Order(
                        id="",
                        instrument=market_data.instrument,
                        side=OrderSide.BUY,
                        order_type=OrderType.MARKET,
                        quantity=10
                    )
                    orders.append(order)
            return orders
        
        momentum_strategy = StrategyFactory.create_momentum_strategy()
        await self.strategy_service.register_strategy(momentum_strategy, momentum_handler)
        
        mean_reversion_strategy = StrategyFactory.create_mean_reversion_strategy()
        
        async def mean_reversion_handler(market_data, portfolio):
            return []
        
        await self.strategy_service.register_strategy(mean_reversion_strategy, mean_reversion_handler)
        
        self.logger.info("Default strategies registered")
    
    async def _run_main_loop(self) -> None:
        while self.running:
            try:
                await asyncio.sleep(10)
                
                system_status = await self.get_system_status()
                self.logger.info(f"System Status: Portfolio Value=${system_status['portfolio']['current_value']:,.2f}")
                
            except KeyboardInterrupt:
                await self.stop()
                break
            except Exception as e:
                self.logger.error(f"Main loop error: {e}")
                await asyncio.sleep(5)
    
    async def _handle_portfolio_value_change(self, new_value: float, market_data: Dict) -> None:
        if new_value < 900000:
            self.logger.warning(f"Portfolio value dropped to ${new_value:,.2f}")
    
    async def _handle_risk_alert(self, alert: Dict) -> None:
        self.logger.warning(f"Risk Alert: {alert['message']}")
        
        if alert.get("severity") == "critical":
            self.logger.critical("Critical risk alert - considering emergency stop")
    
    async def _handle_strategy_event(self, event_type: str, strategy: Strategy) -> None:
        self.logger.info(f"Strategy {event_type}: {strategy.name}")


class ApplicationFactory:
    @staticmethod
    def create_application() -> TradingApplicationService:
        return TradingApplicationService()