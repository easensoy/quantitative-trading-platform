"""Demonstration strategy for the research showcase.

TimeSeriesMomentumStrategy is a textbook time-series momentum rule with inverse-volatility
weights. Its default parameters were fixed before any backtest was run and are not tuned;
the parameter-robustness and walk-forward reports show how other settings behave.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.core.models import AssetType, Instrument, Order, OrderSide, OrderType, Portfolio

STRATEGY_VERSION = "tsmom-1.0"


@dataclass(frozen=True)
class MomentumParameters:
    lookback: int = 60  # bars used for the trend signal (about three months)
    rebalance_every: int = 5  # bars between rebalances (weekly)
    vol_window: int = 60  # bars used for realized volatility
    gross_target: float = 1.0  # sum of absolute weights before caps
    max_weight: float = 0.25  # cap on any single absolute weight
    min_trade_weight: float = 0.005  # skip trades smaller than 0.5% of equity

    def label(self) -> str:
        return f"L{self.lookback}-R{self.rebalance_every}"

    def as_dict(self) -> Dict:
        return asdict(self)


class TimeSeriesMomentumStrategy:
    """Long instruments whose trailing return is positive, short those whose is negative.

    At every rebalance each instrument with enough history gets the raw weight
    sign(log return over `lookback`) / realized volatility; raw weights are scaled to
    `gross_target` and capped at `max_weight`. Orders move the current position to the
    target in whole shares. They are market orders, so BacktestEngine fills them at the
    next bar's close plus slippage.

    trade_from lets walk-forward runs read history before a window without trading.
    """

    name = "Time-series momentum, inverse-volatility weights"
    version = STRATEGY_VERSION

    def __init__(self, params: MomentumParameters = MomentumParameters(), trade_from: Optional[pd.Timestamp] = None):
        if params.lookback < 1 or params.rebalance_every < 1 or params.vol_window < 2:
            raise ValueError(f"invalid parameters: {params}")
        self.params = params
        self.trade_from = pd.Timestamp(trade_from) if trade_from is not None else None
        self.closes: Dict[str, List[float]] = defaultdict(list)
        self.last_close: Dict[str, float] = {}
        self.tradable_bars = 0
        self.instruments: Dict[str, Instrument] = {}

    @property
    def required_history(self) -> int:
        return max(self.params.lookback, self.params.vol_window) + 1

    async def __call__(self, timestamp, market_data, portfolio: Portfolio) -> List[Order]:
        for symbol, bar in market_data.items():
            self.closes[symbol].append(bar.close)
            self.last_close[symbol] = bar.close

        if self.trade_from is not None and pd.Timestamp(timestamp) < self.trade_from:
            return []
        self.tradable_bars += 1
        if (self.tradable_bars - 1) % self.params.rebalance_every:
            return []
        return self._rebalance(market_data, portfolio)

    def target_weights(self, symbols: List[str]) -> Dict[str, float]:
        raw = {}
        for symbol in symbols:
            history = self.closes[symbol]
            if len(history) < self.required_history:
                continue
            prices = np.asarray(history[-self.required_history:], dtype=float)
            momentum = math.log(prices[-1] / prices[-1 - self.params.lookback])
            vol = np.diff(np.log(prices[-self.params.vol_window - 1:])).std(ddof=1) * math.sqrt(252)
            if momentum == 0 or not np.isfinite(vol) or vol <= 0:
                continue
            raw[symbol] = math.copysign(1.0, momentum) / vol
        total = sum(abs(v) for v in raw.values())
        if total == 0:
            return {}
        scale = self.params.gross_target / total
        cap = self.params.max_weight
        return {s: max(-cap, min(cap, w * scale)) for s, w in raw.items()}

    def _rebalance(self, market_data, portfolio: Portfolio) -> List[Order]:
        equity = portfolio.cash + sum(
            position.quantity * self.last_close.get(symbol, position.avg_price)
            for symbol, position in portfolio.positions.items()
        )
        if equity <= 0:
            return []
        weights = self.target_weights(sorted(market_data))
        orders = []
        for symbol in sorted(market_data):
            price = market_data[symbol].close
            target_qty = int(weights.get(symbol, 0.0) * equity / price)
            position = portfolio.get_position(symbol)
            delta = target_qty - (position.quantity if position else 0)
            if delta == 0 or abs(delta) * price < self.params.min_trade_weight * equity:
                continue
            instrument = self.instruments.setdefault(symbol, Instrument(symbol, AssetType.EQUITY, "SYNTH"))
            orders.append(Order(
                id="",
                instrument=instrument,
                side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=abs(delta),
                strategy_id=self.version,
            ))
        return orders
