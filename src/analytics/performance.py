"""Return and risk statistics for daily equity curves (definitions: docs/methodology.md).

Annualization uses the sample's observed frequency (return observations per calendar
year) unless a value is passed: about 252 for exchange data with holidays, about 261 for a
Monday-Friday calendar without holidays such as the synthetic demo universe. A fixed 252
would misstate both cases differently.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = 252  # fallback when a sample is too short to infer its frequency


def periods_per_year(index: pd.DatetimeIndex) -> float:
    """Return observations per calendar year implied by consecutive timestamps."""
    if len(index) < 3:
        return float(PERIODS_PER_YEAR)
    years = (index[-1] - index[0]).days / 365.25
    return (len(index) - 1) / years if years > 0 else float(PERIODS_PER_YEAR)


def calendar_years(index: pd.DatetimeIndex) -> float:
    return (index[-1] - index[0]).days / 365.25


def assert_business_daily(index: pd.DatetimeIndex) -> None:
    """Fail loudly on timestamps that daily annualization would mis-scale (weekend bars,
    duplicates, or unordered dates)."""
    if len(index) < 3:
        return
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("timestamps must be unique and increasing")
    weekend = index.dayofweek >= 5
    if weekend.any():
        raise ValueError(f"{int(weekend.sum())} weekend timestamps: data is not business-daily")


def simple_returns(equity: pd.Series) -> pd.Series:
    return equity.pct_change().iloc[1:]


def cumulative_returns(returns: pd.Series) -> pd.Series:
    return (1.0 + returns).cumprod() - 1.0


def drawdown(equity: pd.Series) -> pd.Series:
    """Fractional distance below the running peak (0 at a new high, negative below)."""
    return equity / equity.cummax() - 1.0


def annualized_volatility(returns: pd.Series, ppy: float = PERIODS_PER_YEAR) -> float:
    return float(returns.std(ddof=1) * np.sqrt(ppy)) if len(returns) > 1 else float("nan")


def sharpe_ratio(returns: pd.Series, ppy: float = PERIODS_PER_YEAR) -> float:
    std = returns.std(ddof=1)
    if len(returns) < 2 or not np.isfinite(std) or std == 0:
        return float("nan")
    return float(returns.mean() / std * np.sqrt(ppy))


def summary_statistics(equity: pd.Series, benchmark_returns: Optional[pd.Series] = None,
                       ppy: Optional[float] = None) -> Dict[str, float]:
    ppy = periods_per_year(equity.index) if ppy is None else ppy
    returns = simple_returns(equity)
    n = len(returns)
    stats: Dict[str, float] = {
        "start": equity.index[0],
        "end": equity.index[-1],
        "observations": n,
        "periods_per_year": float(ppy),
        "initial_equity": float(equity.iloc[0]),
        "final_equity": float(equity.iloc[-1]),
        "net_pnl": float(equity.iloc[-1] - equity.iloc[0]),
    }
    if n < 2:
        return stats
    growth = equity.iloc[-1] / equity.iloc[0]
    downside = np.sqrt((np.minimum(returns, 0.0) ** 2).mean())
    max_dd = float(drawdown(equity).min())
    cagr = float(growth ** (ppy / n) - 1.0) if growth > 0 else float("nan")
    active_days = returns[returns != 0]
    stats.update({
        "total_return": float(growth - 1.0),
        "cagr": cagr,
        "annualized_volatility": annualized_volatility(returns, ppy),
        "sharpe": sharpe_ratio(returns, ppy),
        "sortino": float(returns.mean() / downside * np.sqrt(ppy)) if downside > 0 else float("nan"),
        "max_drawdown": max_dd,
        "calmar": float(cagr / abs(max_dd)) if max_dd < 0 and np.isfinite(cagr) else float("nan"),
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "hit_rate": float((active_days > 0).mean()) if len(active_days) else float("nan"),
        "skewness": float(returns.skew()),
        "excess_kurtosis": float(returns.kurt()),
    })
    if benchmark_returns is not None:
        aligned = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
        aligned.columns = ["strategy", "benchmark"]
        if len(aligned) > 2 and aligned["benchmark"].var() > 0:
            active = aligned["strategy"] - aligned["benchmark"]
            tracking_error = active.std(ddof=1) * np.sqrt(ppy)
            stats.update({
                "benchmark_total_return": float((1 + aligned["benchmark"]).prod() - 1),
                "beta": float(aligned.cov().iloc[0, 1] / aligned["benchmark"].var()),
                "correlation": float(aligned.corr().iloc[0, 1]),
                "tracking_error": float(tracking_error),
                "information_ratio": float(active.mean() * ppy / tracking_error)
                if tracking_error > 0 else float("nan"),
            })
    return stats


def rolling_volatility(returns: pd.Series, window: int = 63, ppy: float = PERIODS_PER_YEAR) -> pd.Series:
    return returns.rolling(window).std(ddof=1) * np.sqrt(ppy)


def rolling_sharpe(returns: pd.Series, window: int = 126, ppy: float = PERIODS_PER_YEAR) -> pd.Series:
    rolling = returns.rolling(window)
    std = rolling.std(ddof=1)
    return rolling.mean() / std.where(std > 0) * np.sqrt(ppy)


def monthly_returns(returns: pd.Series) -> pd.DataFrame:
    """Compounded monthly returns as a year x month table with a full-year column."""
    by_month = (1.0 + returns).groupby([returns.index.year, returns.index.month]).prod() - 1.0
    table = by_month.unstack(level=1).reindex(columns=range(1, 13))
    table.index.name, table.columns.name = "year", "month"
    table["year"] = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    return table


def equal_weight_benchmark(closes: pd.DataFrame) -> pd.Series:
    """Daily-rebalanced equal-weight index of the instruments with a return that day.

    Frictionless. A halted instrument contributes no return on the missing day; the
    return over the gap is taken on the day trading resumes.
    """
    filled = closes.ffill()
    returns = (filled / filled.shift(1) - 1.0).where(closes.notna())
    return returns.mean(axis=1, skipna=True).iloc[1:].fillna(0.0)
