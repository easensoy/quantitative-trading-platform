class TradingException(Exception):
    pass


class InstrumentNotFoundError(TradingException):
    def __init__(self, symbol: str):
        super().__init__(f"Instrument not found: {symbol}")
        self.symbol = symbol


class OrderValidationError(TradingException):
    def __init__(self, message: str, order_id: str = None):
        super().__init__(message)
        self.order_id = order_id


class RiskLimitExceededError(TradingException):
    def __init__(self, limit_type: str, current_value: float, limit_value: float):
        super().__init__(f"{limit_type} limit exceeded: {current_value} > {limit_value}")
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value


class MarketDataError(TradingException):
    pass


class ExecutionError(TradingException):
    pass


class BacktestError(TradingException):
    pass


class DatabaseError(TradingException):
    pass


class ConfigurationError(TradingException):
    pass


class AIModelError(TradingException):
    pass