"""Exposure, concentration and diversification from a backtest ledger."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

UNCLASSIFIED = "Unclassified (no sector metadata)"


def position_values(quantities: pd.DataFrame, marks: pd.DataFrame) -> pd.DataFrame:
    """Signed market value per symbol; flat positions are worth 0 even without a mark."""
    values = quantities * marks.reindex_like(quantities)
    return values.where(quantities != 0, 0.0).fillna(0.0)


def weights(quantities: pd.DataFrame, marks: pd.DataFrame, equity: pd.Series) -> pd.DataFrame:
    return position_values(quantities, marks).div(equity, axis=0)


def exposures(quantities: pd.DataFrame, marks: pd.DataFrame, equity: pd.Series) -> pd.DataFrame:
    w = weights(quantities, marks, equity)
    long, short = w.clip(lower=0).sum(axis=1), w.clip(upper=0).sum(axis=1)
    return pd.DataFrame({"long": long, "short": short, "gross": long - short, "net": long + short})


def concentration(w: pd.DataFrame) -> pd.DataFrame:
    """Effective number of positions, (sum |w|)^2 / sum w^2, and the largest |weight|."""
    absolute = w.abs()
    gross = absolute.sum(axis=1)
    effective_n = (gross ** 2 / (w ** 2).sum(axis=1)).where(gross > 0)
    return pd.DataFrame({"effective_positions": effective_n, "max_abs_weight": absolute.max(axis=1)})


def sector_weights(w: pd.DataFrame, sectors: Dict[str, Optional[str]]) -> pd.DataFrame:
    """Net weight per sector; symbols without sector metadata are grouped visibly."""
    labels = {s: sectors.get(s) or UNCLASSIFIED for s in w.columns}
    return w.T.groupby(labels).sum().T


def return_correlations(closes: pd.DataFrame, min_overlap: int = 126) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Pairwise correlations of daily returns over each pair's common dates.

    Returns (correlations, overlap counts). Pairs with fewer than min_overlap common
    observations get NaN so a short history cannot pass for a reliable estimate.
    """
    filled = closes.ffill()
    returns = (filled / filled.shift(1) - 1.0).where(closes.notna() & closes.shift(1).notna())
    observed = returns.notna().astype(int)
    overlap = observed.T @ observed
    corr = returns.corr(min_periods=2)
    return corr.where(overlap >= min_overlap), overlap


def history_coverage(closes: pd.DataFrame) -> pd.DataFrame:
    rows = {}
    for symbol in closes.columns:
        series = closes[symbol]
        first, last = series.first_valid_index(), series.last_valid_index()
        span = series.loc[first:last]
        rows[symbol] = {"first_bar": first, "bars": int(span.notna().sum()),
                        "missing_inside_listing": int(span.isna().sum())}
    return pd.DataFrame.from_dict(rows, orient="index")
