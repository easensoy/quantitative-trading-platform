"""Fills to round trips (FIFO), turnover and execution-cost diagnostics.

Orders, fills and closed trades are different things: an order is a request, a fill is
an execution, and a closed trade is a FIFO match between an opening and a closing fill.
A rebalancing strategy partially reduces positions, so one fill can close several lots
and one lot can be closed by several fills.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Tuple

import numpy as np
import pandas as pd

from src.analytics.performance import calendar_years


def round_trips(executions: pd.DataFrame, final_marks: pd.Series) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Match fills first-in-first-out per symbol.

    Returns (closed, open_lots). Commissions are allocated per share to the matched
    quantity on both legs. open_lots carries unrealized P&L at final_marks, so
    closed.net_pnl.sum() + open_lots.unrealized_net.sum() equals the strategy's net P&L.
    """
    lots = defaultdict(deque)
    closed = []
    ordered = executions.sort_values(["filled_at", "trade_id"], kind="stable",
                                     key=lambda col: col if col.name == "filled_at"
                                     else col.str.split("_").str[-1].astype(int))
    for row in ordered.itertuples(index=False):
        sign = 1 if row.side == "buy" else -1
        remaining = int(row.quantity)
        commission_per_share = row.commission / row.quantity
        book = lots[row.symbol]
        while remaining and book and np.sign(book[0]["quantity"]) == -sign:
            lot = book[0]
            matched = min(remaining, abs(lot["quantity"]))
            direction = np.sign(lot["quantity"])
            gross = (row.fill_price - lot["price"]) * matched * direction
            commission = (lot["commission_per_share"] + commission_per_share) * matched
            closed.append({
                "symbol": row.symbol,
                "direction": "long" if direction > 0 else "short",
                "quantity": matched,
                "entry_time": lot["time"], "exit_time": row.filled_at,
                "entry_price": lot["price"], "exit_price": row.fill_price,
                "holding_bars": int(np.busday_count(lot["time"].date(), row.filled_at.date())),
                "gross_pnl": gross,
                "commission": commission,
                "net_pnl": gross - commission,
                "return": (gross - commission) / (lot["price"] * matched),
            })
            lot["quantity"] -= matched * direction
            remaining -= matched
            if lot["quantity"] == 0:
                book.popleft()
        if remaining:
            book.append({"quantity": sign * remaining, "price": row.fill_price,
                         "time": row.filled_at, "commission_per_share": commission_per_share})

    open_rows = []
    for symbol, book in lots.items():
        for lot in book:
            mark = final_marks.get(symbol, np.nan)
            open_rows.append({
                "symbol": symbol, "direction": "long" if lot["quantity"] > 0 else "short",
                "quantity": abs(lot["quantity"]), "entry_time": lot["time"], "entry_price": lot["price"],
                "mark": mark,
                "unrealized_net": (mark - lot["price"]) * lot["quantity"]
                - lot["commission_per_share"] * abs(lot["quantity"]),
            })
    return pd.DataFrame(closed), pd.DataFrame(open_rows)


def trade_statistics(closed: pd.DataFrame) -> dict:
    if closed.empty:
        return {"closed_trades": 0}
    wins, losses = closed[closed["net_pnl"] > 0], closed[closed["net_pnl"] < 0]
    return {
        "closed_trades": int(len(closed)),
        "winning_trades": int(len(wins)),  # break-even lots count as neither
        "losing_trades": int(len(losses)),
        "win_rate": float(len(wins) / len(closed)),
        "average_win": float(wins["net_pnl"].mean()) if len(wins) else float("nan"),
        "average_loss": float(losses["net_pnl"].mean()) if len(losses) else float("nan"),
        "profit_factor": float(wins["net_pnl"].sum() / -losses["net_pnl"].sum()) if len(losses) else float("nan"),
        "median_holding_bars": float(closed["holding_bars"].median()),
        "total_net_pnl": float(closed["net_pnl"].sum()),
    }


def monthly_turnover(executions: pd.DataFrame, equity: pd.Series) -> pd.DataFrame:
    """Traded notional and costs per month, relative to that month's average equity."""
    fills = executions.assign(notional=executions["quantity"] * executions["fill_price"],
                              month=executions["filled_at"].dt.to_period("M"))
    per_month = fills.groupby("month")[["notional", "commission", "slippage_cost"]].sum()
    avg_equity = equity.groupby(equity.index.to_period("M")).mean()
    per_month = per_month.reindex(avg_equity.index).fillna(0.0)
    per_month["turnover"] = per_month["notional"] / avg_equity
    per_month["cost_bps_of_equity"] = (per_month["commission"] + per_month["slippage_cost"]) / avg_equity * 1e4
    return per_month


def annualized_turnover(executions: pd.DataFrame, equity: pd.Series) -> float:
    notional = (executions["quantity"] * executions["fill_price"]).sum()
    years = calendar_years(equity.index)
    return float(notional / equity.mean() / years) if years > 0 else float("nan")


def fill_delays(executions: pd.DataFrame) -> pd.Series:
    """Business days between the decision bar and the fill bar."""
    return pd.Series(np.busday_count(executions["submitted_at"].values.astype("datetime64[D]"),
                                     executions["filled_at"].values.astype("datetime64[D]")),
                     index=executions.index, name="fill_delay_days")
