"""P&L decomposition that reconciles exactly to the change in equity.

For fill i with signed quantity q (+buy, -sell), reference close r, fill price p and
commission c, and final position Q marked at M:

    frictionless P&L = sum(-q * r) + Q * M           (trading at the reference closes)
    slippage cost    = sum(q * (p - r))              (already inside the fill prices)
    net P&L          = frictionless - slippage - commissions = equity change

Slippage is shown as a component of the gap between frictionless and net P&L; it is
not subtracted from the net figure a second time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class PnLDecomposition:
    frictionless: float
    slippage: float
    commissions: float
    financing: Optional[float]  # None: not modeled by the execution model
    net: float
    equity_change: float
    by_symbol: pd.DataFrame

    @property
    def residual(self) -> float:
        return self.equity_change - self.net


def decompose_pnl(executions: pd.DataFrame, final_quantities: pd.Series, final_marks: pd.Series,
                  initial_equity: float, final_equity: float) -> PnLDecomposition:
    signed = np.where(executions["side"] == "buy", 1.0, -1.0) * executions["quantity"].astype(float)
    frame = pd.DataFrame({
        "symbol": executions["symbol"],
        "reference_flow": -signed * executions["reference_price"],
        "slippage": signed * (executions["fill_price"] - executions["reference_price"]),
        "commission": executions["commission"],
        "traded_notional": executions["quantity"] * executions["fill_price"],
    })
    by_symbol = frame.groupby("symbol").sum()
    symbols = sorted(set(by_symbol.index) | set(final_quantities[final_quantities != 0].index))
    by_symbol = by_symbol.reindex(symbols).fillna(0.0)
    held = final_quantities.reindex(symbols).fillna(0)
    by_symbol["final_value"] = (held * final_marks.reindex(symbols)).where(held != 0, 0.0).fillna(0.0)
    by_symbol["frictionless"] = by_symbol["reference_flow"] + by_symbol["final_value"]
    by_symbol["net"] = by_symbol["frictionless"] - by_symbol["slippage"] - by_symbol["commission"]
    by_symbol = by_symbol[["frictionless", "slippage", "commission", "net", "traded_notional", "final_value"]]
    return PnLDecomposition(
        frictionless=float(by_symbol["frictionless"].sum()),
        slippage=float(by_symbol["slippage"].sum()),
        commissions=float(by_symbol["commission"].sum()),
        financing=None,
        net=float(by_symbol["net"].sum()),
        equity_change=float(final_equity - initial_equity),
        by_symbol=by_symbol,
    )
