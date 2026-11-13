from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
import os


def _env(name: str, default: Optional[str], cast: Callable[[str], Any] = str):
    """Dataclass field whose value is read from the environment when the config is created.

    Reading at instantiation (not at import) keeps each AppConfig() consistent with the
    current environment and gives every instance its own nested config objects.
    """
    def factory():
        value = os.getenv(name, default)
        return None if value is None else cast(value)
    return field(default_factory=factory)


def _env_bool(name: str, default: str):
    return _env(name, default, lambda value: value.lower() == "true")


@dataclass
class DatabaseConfig:
    mysql_host: str = _env("MYSQL_HOST", "localhost")
    mysql_port: int = _env("MYSQL_PORT", "3306", int)
    mysql_user: str = _env("MYSQL_USER", "trading_user")
    mysql_password: str = _env("MYSQL_PASSWORD", "")
    mysql_database: str = _env("MYSQL_DATABASE", "trading_db")
    
    clickhouse_host: str = _env("CLICKHOUSE_HOST", "localhost")
    clickhouse_port: int = _env("CLICKHOUSE_PORT", "9000", int)
    clickhouse_user: str = _env("CLICKHOUSE_USER", "default")
    clickhouse_password: str = _env("CLICKHOUSE_PASSWORD", "")
    clickhouse_database: str = _env("CLICKHOUSE_DATABASE", "trading_analytics")
    
    redis_host: str = _env("REDIS_HOST", "localhost")
    redis_port: int = _env("REDIS_PORT", "6379", int)
    redis_password: Optional[str] = _env("REDIS_PASSWORD", None)


@dataclass
class AIConfig:
    openai_api_key: str = _env("OPENAI_API_KEY", "")
    openai_model: str = _env("OPENAI_MODEL", "gpt-4")
    embedding_model: str = _env("EMBEDDING_MODEL", "text-embedding-ada-002")
    max_tokens: int = _env("MAX_TOKENS", "4000", int)
    temperature: float = _env("TEMPERATURE", "0.1", float)


@dataclass
class MonitoringConfig:
    enable_telemetry: bool = _env_bool("ENABLE_TELEMETRY", "true")
    jaeger_endpoint: str = _env("JAEGER_ENDPOINT", "http://localhost:14268/api/traces")
    prometheus_port: int = _env("PROMETHEUS_PORT", "8000", int)
    log_level: str = _env("LOG_LEVEL", "INFO")


@dataclass
class TradingConfig:
    max_position_size: float = _env("MAX_POSITION_SIZE", "1000000", float)
    max_portfolio_risk: float = _env("MAX_PORTFOLIO_RISK", "0.02", float)
    default_commission: float = _env("DEFAULT_COMMISSION", "0.001", float)
    market_impact_model: str = _env("MARKET_IMPACT_MODEL", "sqrt")
    risk_free_rate: float = _env("RISK_FREE_RATE", "0.02", float)


@dataclass
class BacktestConfig:
    initial_capital: float = _env("INITIAL_CAPITAL", "1000000", float)
    benchmark_symbol: str = _env("BENCHMARK_SYMBOL", "SPY")
    start_date: str = _env("BACKTEST_START_DATE", "2020-01-01")
    end_date: str = _env("BACKTEST_END_DATE", "2023-12-31")
    frequency: str = _env("BACKTEST_FREQUENCY", "1D")


@dataclass
class AppConfig:
    environment: str = _env("ENVIRONMENT", "development")
    debug: bool = _env_bool("DEBUG", "false")
    api_host: str = _env("API_HOST", "0.0.0.0")
    api_port: int = _env("API_PORT", "8080", int)
    
    # Nested configs need default_factory: a shared instance default is mutable state
    # and Python 3.11+ rejects it at class creation.
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    
    @property
    def is_production(self) -> bool:
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        return self.environment == "development"


def _optional_env(name: str, cast: Callable[[str], Any]) -> Any:
    value = os.getenv(name, "").strip()
    return cast(value) if value else None


def get_config() -> Dict:
    config = AppConfig()
    return {
        "mode": os.getenv("MODE", "live"),
        "initial_capital": config.backtest.initial_capital,
        "run_duration_seconds": _optional_env("RUN_DURATION_SECONDS", float),
        "market_data": {
            "provider": os.getenv("MARKET_DATA_PROVIDER", "simulated"),
            "poll_interval": float(os.getenv("MARKET_DATA_POLL_INTERVAL", "1.0")),
            "seed": _optional_env("SIMULATION_SEED", int),
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
