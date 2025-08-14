from dataclasses import dataclass
from typing import Dict, List, Optional
import os
from pathlib import Path


@dataclass
class DatabaseConfig:
    mysql_host: str = os.getenv("MYSQL_HOST", "localhost")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "trading_user")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "trading_db")
    
    clickhouse_host: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    clickhouse_port: int = int(os.getenv("CLICKHOUSE_PORT", "9000"))
    clickhouse_user: str = os.getenv("CLICKHOUSE_USER", "default")
    clickhouse_password: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    clickhouse_database: str = os.getenv("CLICKHOUSE_DATABASE", "trading_analytics")
    
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")


@dataclass
class AIConfig:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    max_tokens: int = int(os.getenv("MAX_TOKENS", "4000"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.1"))


@dataclass
class MonitoringConfig:
    enable_telemetry: bool = os.getenv("ENABLE_TELEMETRY", "true").lower() == "true"
    jaeger_endpoint: str = os.getenv("JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
    prometheus_port: int = int(os.getenv("PROMETHEUS_PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


@dataclass
class TradingConfig:
    max_position_size: float = float(os.getenv("MAX_POSITION_SIZE", "1000000"))
    max_portfolio_risk: float = float(os.getenv("MAX_PORTFOLIO_RISK", "0.02"))
    default_commission: float = float(os.getenv("DEFAULT_COMMISSION", "0.001"))
    market_impact_model: str = os.getenv("MARKET_IMPACT_MODEL", "sqrt")
    risk_free_rate: float = float(os.getenv("RISK_FREE_RATE", "0.02"))


@dataclass
class BacktestConfig:
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "1000000"))
    benchmark_symbol: str = os.getenv("BENCHMARK_SYMBOL", "SPY")
    start_date: str = os.getenv("BACKTEST_START_DATE", "2020-01-01")
    end_date: str = os.getenv("BACKTEST_END_DATE", "2023-12-31")
    frequency: str = os.getenv("BACKTEST_FREQUENCY", "1D")


@dataclass
class AppConfig:
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8080"))
    
    database: DatabaseConfig = DatabaseConfig()
    ai: AIConfig = AIConfig()
    monitoring: MonitoringConfig = MonitoringConfig()
    trading: TradingConfig = TradingConfig()
    backtest: BacktestConfig = BacktestConfig()
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"


def get_config() -> Dict:
    config = AppConfig()
    return {
        "mode": os.getenv("MODE", "live"),
        "initial_capital": config.trading.max_position_size,
        "market_data": {
            "provider": os.getenv("MARKET_DATA_PROVIDER", "simulated")
        },
        "event_bus": {
            "type": os.getenv("EVENT_BUS_TYPE", "memory"),
            "url": f"redis://{config.database.redis_host}:{config.database.redis_port}"
        },
        "risk": {
            "max_position_size": config.trading.max_position_size,
            "max_portfolio_leverage": 3.0,
            "max_daily_loss": 0.05
        },
        "execution": {
            "commission": config.trading.default_commission,
            "slippage": 0.0005
        }
    }