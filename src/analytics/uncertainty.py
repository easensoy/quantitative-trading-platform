"""Resampling and regime-conditional statistics.

Bootstrap outcomes are conditional estimates: they reshuffle the observed history, so
they inherit its length, its regimes and its luck, and say nothing about data the
history does not contain.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.performance import PERIODS_PER_YEAR


def stationary_bootstrap(returns: np.ndarray, horizon: int, mean_block: float, samples: int,
                         seed: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap: geometric block lengths with the given mean,
    circular wrap-around. Returns a (samples, horizon) array of resampled returns."""
    rng = np.random.default_rng(seed)
    n = len(returns)
    restart = rng.random((samples, horizon)) < 1.0 / mean_block
    restart[:, 0] = True
    starts = rng.integers(0, n, size=(samples, horizon))
    index = np.empty((samples, horizon), dtype=np.int64)
    index[:, 0] = starts[:, 0]
    for t in range(1, horizon):
        index[:, t] = np.where(restart[:, t], starts[:, t], (index[:, t - 1] + 1) % n)
    return returns[index]


def path_statistics(paths: np.ndarray, ppy: float = PERIODS_PER_YEAR) -> pd.DataFrame:
    growth = np.cumprod(1.0 + paths, axis=1)
    peaks = np.maximum.accumulate(np.concatenate([np.ones((len(paths), 1)), growth], axis=1), axis=1)[:, 1:]
    std = paths.std(axis=1, ddof=1)
    return pd.DataFrame({
        "total_return": growth[:, -1] - 1.0,
        "max_drawdown": (growth / peaks - 1.0).min(axis=1),
        "sharpe": np.where(std > 0, paths.mean(axis=1) / np.where(std > 0, std, 1) * np.sqrt(ppy), np.nan),
    })


def regime_statistics(returns: pd.Series, regimes: pd.Series, ppy: float = PERIODS_PER_YEAR) -> pd.DataFrame:
    """Annualized performance by regime label (labels known only for synthetic data)."""
    aligned = pd.concat([returns.rename("r"), regimes.rename("regime")], axis=1, join="inner").dropna()
    rows = {}
    for regime, group in aligned.groupby("regime"):
        r = group["r"]
        std = r.std(ddof=1)
        rows[regime] = {
            "days": int(len(r)),
            "share_of_days": len(r) / len(aligned),
            "annualized_return": float(r.mean() * ppy),
            "annualized_volatility": float(std * np.sqrt(ppy)),
            "sharpe": float(r.mean() / std * np.sqrt(ppy)) if std > 0 else float("nan"),
            "worst_day": float(r.min()),
        }
    return pd.DataFrame.from_dict(rows, orient="index")
