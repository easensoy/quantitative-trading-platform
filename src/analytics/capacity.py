"""Modeled capital and capacity sensitivity (an ex-post cost model, not a backtest).

The observed fills are re-priced at larger capital assuming every order scales linearly
with capital and the strategy does not adapt. On top of the engine's commission and
slippage it charges square-root market impact per fill:

    impact cost = Y * sigma * sqrt(shares / ADV) * notional

with sigma the instrument's trailing daily return volatility and ADV its trailing mean
daily volume, both known before the fill. Participation is fill shares / volume of the
fill bar. All of this is a model with explicit assumptions; only the base-capital row
corresponds to the simulated run.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def fill_liquidity(executions: pd.DataFrame, closes: pd.DataFrame, volumes: pd.DataFrame,
                   window: int = 20) -> pd.DataFrame:
    log_returns = np.log(closes.ffill()).diff().where(closes.notna())
    sigma = log_returns.rolling(window, min_periods=window // 2).std().shift(1)
    adv = volumes.rolling(window, min_periods=window // 2).mean().shift(1)

    def lookup(frame: pd.DataFrame) -> list:
        return [frame.at[t, s] for t, s in zip(executions["filled_at"], executions["symbol"])]

    out = executions[["symbol", "filled_at", "quantity", "reference_price", "fill_price", "commission",
                      "slippage_cost"]].copy()
    out["sigma"] = lookup(sigma)
    out["adv"] = lookup(adv)
    out["bar_volume"] = lookup(volumes)
    out["notional"] = out["quantity"] * out["fill_price"]
    return out


def capacity_curve(liquidity: pd.DataFrame, frictionless_pnl: float, base_capital: float,
                   capital_levels: Sequence[float], years: float, impact_coefficient: float = 1.0,
                   commission_scale: float = 1.0) -> pd.DataFrame:
    """Modeled net return per year (simple, % of capital) at each capital level."""
    usable = liquidity.dropna(subset=["sigma", "adv"])
    impact_base = (impact_coefficient * usable["sigma"] * np.sqrt(usable["quantity"] / usable["adv"])
                   * usable["notional"]).sum()
    commission = liquidity["commission"].sum() * commission_scale
    slippage = liquidity["slippage_cost"].sum()
    rows = []
    for capital in capital_levels:
        k = capital / base_capital
        participation = liquidity["quantity"] * k / liquidity["bar_volume"]
        impact = impact_base * k ** 1.5
        frictionless = frictionless_pnl * k
        net = frictionless - commission * k - slippage * k - impact
        rows.append({
            "capital": capital,
            "frictionless_return_pa": frictionless / capital / years,
            "commission_pa": commission * k / capital / years,
            "slippage_pa": slippage * k / capital / years,
            "impact_pa": impact / capital / years,
            "net_return_pa": net / capital / years,
            "participation_median": float(participation.median()),
            "participation_p95": float(participation.quantile(0.95)),
            "participation_max": float(participation.max()),
            "fills_above_10pct_participation": int((participation > 0.10).sum()),
            "fills_priced": int(len(usable)),
        })
    return pd.DataFrame(rows)
