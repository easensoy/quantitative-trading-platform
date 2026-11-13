"""Deterministic synthetic market data for examples and tests (no market data access)."""
import numpy as np
import pandas as pd


def generate_ohlcv(
    start: str = "2023-01-01",
    end: str = "2023-12-31",
    start_price: float = 100.0,
    daily_volatility: float = 0.01,
    drift: float = 0.0,
    seed: int = 42,
    freq: str = "D",
) -> pd.DataFrame:
    """Geometric random-walk bars with consistent OHLC values.

    Each bar opens at the previous close, and high/low bracket open and close, so
    low <= min(open, close) <= max(open, close) <= high always holds. The same seed
    always produces the same frame.
    """
    dates = pd.date_range(start=start, end=end, freq=freq)
    rng = np.random.default_rng(seed)
    n = len(dates)

    close = start_price * np.exp(np.cumsum(rng.normal(drift, daily_volatility, n)))
    open_ = np.concatenate(([start_price], close[:-1]))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, daily_volatility / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, daily_volatility / 2, n)))
    volume = rng.integers(1_000_000, 5_000_000, n)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
