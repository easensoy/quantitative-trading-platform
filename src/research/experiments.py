"""Experiment runners on top of BacktestEngine.

Every run uses a fresh engine and a fresh strategy instance (no shared state), and gets
a deterministic run id derived from its inputs, so identical inputs always produce the
same id and the same numbers.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

from src.analytics.performance import calendar_years, summary_statistics
from src.backtesting.engine import BacktestConfig, BacktestEngine
from src.research.datasets import MarketDataset
from src.research.strategies import STRATEGY_VERSION, MomentumParameters, TimeSeriesMomentumStrategy


@dataclass(frozen=True)
class ExecutionSettings:
    initial_capital: float = 1_000_000.0
    commission: float = 0.001  # fraction of fill notional
    slippage: float = 0.0005  # fraction of the reference close, applied against the trader
    currency: str = "USD"

    def describe(self) -> str:
        return (f"next-bar close fills, {self.slippage * 1e4:.0f} bps slippage, "
                f"{self.commission * 1e4:.0f} bps commission, no financing or borrow costs")


@dataclass
class BacktestRecord:
    """Everything a report needs from one backtest, detached from the engine."""
    run_id: str
    label: str
    strategy_version: str
    params: Dict
    dataset_name: str
    dataset_origin: str
    dataset_fingerprint: str
    settings: ExecutionSettings
    start: pd.Timestamp
    end: pd.Timestamp
    trade_from: pd.Timestamp
    equity: pd.Series
    cash: pd.Series
    quantities: pd.DataFrame
    marks: pd.DataFrame
    stale_marks: pd.Series
    executions: pd.DataFrame
    orders: pd.DataFrame
    strategy_errors: List[Tuple[str, str]] = field(default_factory=list)
    runtime_seconds: float = 0.0

    @property
    def evaluation_equity(self) -> pd.Series:
        """Equity from the first tradable bar on (warm-up bars before it are excluded)."""
        return self.equity.loc[self.trade_from:]

    def manifest(self) -> Dict:
        return {
            "run_id": self.run_id,
            "label": self.label,
            "strategy_version": self.strategy_version,
            "parameters": self.params,
            "dataset": {"name": self.dataset_name, "origin": self.dataset_origin,
                        "prices_sha256": self.dataset_fingerprint},
            "execution": {**asdict(self.settings), "model": self.settings.describe()},
            "engine_start": str(self.start.date()),
            "evaluation_start": str(self.trade_from.date()),
            "end": str(self.end.date()),
            "bars": int(len(self.equity)),
            "fills": int(len(self.executions)),
            "orders": int(len(self.orders)),
            "rejected_orders": int((~self.orders["accepted"]).sum()) if len(self.orders) else 0,
            "strategy_errors": len(self.strategy_errors),
            # No wall-clock runtime here: the manifest describes inputs and results, so a
            # rerun on the same inputs reproduces it byte for byte. Timings live in
            # engineering.json.
        }


def make_run_id(dataset: MarketDataset, params: MomentumParameters, settings: ExecutionSettings,
                start, end, trade_from) -> str:
    payload = {
        "dataset": dataset.fingerprint,
        "strategy": STRATEGY_VERSION,
        "params": params.as_dict(),
        "settings": asdict(settings),
        "window": [str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date()),
                   str(pd.Timestamp(trade_from).date())],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:10]


def run_backtest(dataset: MarketDataset, params: MomentumParameters = MomentumParameters(),
                 settings: ExecutionSettings = ExecutionSettings(), start=None, end=None,
                 trade_from=None, label: Optional[str] = None) -> BacktestRecord:
    calendar = dataset.calendar
    start = pd.Timestamp(start) if start is not None else calendar[0]
    end = pd.Timestamp(end) if end is not None else calendar[-1]
    trade_from = pd.Timestamp(trade_from) if trade_from is not None else start
    bars = {s: f.loc[start:end] for s, f in dataset.bars.items()}
    bars = {s: f for s, f in bars.items() if not f.empty}

    engine = BacktestEngine(BacktestConfig(
        start_date=start.to_pydatetime(), end_date=end.to_pydatetime(),
        initial_capital=settings.initial_capital, commission=settings.commission,
        slippage=settings.slippage,
    ))
    strategy = TimeSeriesMomentumStrategy(params, trade_from=trade_from)
    began = time.perf_counter()
    asyncio.run(engine.run_backtest(strategy, bars))
    runtime = time.perf_counter() - began

    index = pd.DatetimeIndex([entry.timestamp for entry in engine.ledger])
    quantities = pd.DataFrame([entry.quantities for entry in engine.ledger], index=index).reindex(
        columns=sorted(dataset.symbols)).fillna(0).astype(int)
    marks = pd.DataFrame([entry.marks for entry in engine.ledger], index=index).reindex(columns=sorted(dataset.symbols))
    executions = pd.DataFrame([{
        "order_id": e.order_id, "trade_id": e.trade_id, "symbol": e.symbol, "side": e.side,
        "quantity": e.quantity, "submitted_at": e.submitted_at, "filled_at": e.filled_at,
        "reference_price": e.reference_price, "fill_price": e.fill_price,
        "commission": e.commission, "slippage_cost": e.slippage_cost,
    } for e in engine.broker.executions], columns=[
        "order_id", "trade_id", "symbol", "side", "quantity", "submitted_at", "filled_at",
        "reference_price", "fill_price", "commission", "slippage_cost"])
    orders = pd.DataFrame([{
        "decided_at": r.decided_at, "symbol": r.order.instrument.symbol, "side": r.order.side.value,
        "quantity": r.order.quantity, "accepted": r.accepted, "reason": r.reason,
        "status": r.order.status.value,
    } for r in engine.order_log], columns=["decided_at", "symbol", "side", "quantity", "accepted", "reason", "status"])

    return BacktestRecord(
        run_id=make_run_id(dataset, params, settings, start, end, trade_from),
        label=label or f"{STRATEGY_VERSION} {params.label()}",
        strategy_version=STRATEGY_VERSION,
        params=params.as_dict(),
        dataset_name=dataset.name,
        dataset_origin=dataset.origin,
        dataset_fingerprint=dataset.fingerprint,
        settings=settings,
        start=start, end=end, trade_from=trade_from,
        equity=pd.Series([entry.equity for entry in engine.ledger], index=index, name="equity"),
        cash=pd.Series([entry.cash for entry in engine.ledger], index=index, name="cash"),
        quantities=quantities,
        marks=marks,
        stale_marks=pd.Series([len(entry.stale_marks) for entry in engine.ledger], index=index),
        executions=executions,
        orders=orders,
        strategy_errors=[(str(t), message) for t, message in engine.strategy_errors],
        runtime_seconds=runtime,
    )


# --------------------------------------------------------------------------- sweeps

def _warmup_start(dataset: MarketDataset, trade_from: pd.Timestamp, params: MomentumParameters) -> pd.Timestamp:
    """Earliest bar the strategy needs before trade_from (plus a margin for halts)."""
    calendar = dataset.calendar
    position = int(calendar.searchsorted(trade_from))
    need = max(params.lookback, params.vol_window) + 1 + 10
    return calendar[max(0, position - need)]


def evaluate(dataset: MarketDataset, params: MomentumParameters, settings: ExecutionSettings,
             trade_from: pd.Timestamp, end: pd.Timestamp) -> Dict:
    """One isolated run, summarized; failures are reported instead of raised."""
    row = {"lookback": params.lookback, "rebalance_every": params.rebalance_every,
           "label": params.label(), "status": "ok", "error": ""}
    try:
        record = run_backtest(dataset, params, settings, start=_warmup_start(dataset, trade_from, params),
                              end=end, trade_from=trade_from)
    except Exception as exc:  # a failed configuration is a result, not a crash
        row.update(status="error", error=repr(exc))
        return row
    equity = record.evaluation_equity
    stats = summary_statistics(equity)
    years = calendar_years(equity.index)
    costs = float(record.executions["commission"].sum() + record.executions["slippage_cost"].sum())
    traded = float((record.executions["quantity"] * record.executions["fill_price"]).sum())
    row.update(run_id=record.run_id, fills=len(record.executions), runtime_seconds=record.runtime_seconds,
               cost_pa=costs / settings.initial_capital / years if years > 0 else float("nan"),
               turnover_pa=traded / equity.mean() / years if years > 0 else float("nan"),
               **{k: v for k, v in stats.items() if k not in ("start", "end")})
    if record.strategy_errors:
        row.update(status="error", error=record.strategy_errors[0][1])
    elif len(record.executions) == 0:
        row["status"] = "no_trades"
    return row


_WORKER_DATASET: Optional[MarketDataset] = None


def _init_worker(dataset: MarketDataset) -> None:
    global _WORKER_DATASET
    _WORKER_DATASET = dataset


def _evaluate_task(task) -> Dict:
    params, settings, trade_from, end, tag = task
    row = evaluate(_WORKER_DATASET, params, settings, trade_from, end)
    row["tag"] = tag
    return row


def run_many(dataset: MarketDataset, tasks: Sequence[tuple], jobs: int = 1) -> List[Dict]:
    """Evaluate tasks (params, settings, trade_from, end, tag), in separate processes if jobs > 1."""
    if jobs <= 1:
        _init_worker(dataset)
        return [_evaluate_task(task) for task in tasks]
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker, initargs=(dataset,)) as pool:
        return list(pool.map(_evaluate_task, tasks))


def parameter_grid(lookbacks: Sequence[int], rebalances: Sequence[int],
                   base: MomentumParameters = MomentumParameters()) -> List[MomentumParameters]:
    return [MomentumParameters(**{**base.as_dict(), "lookback": lb, "rebalance_every": rb})
            for lb in lookbacks for rb in rebalances]


def parameter_sweep(dataset: MarketDataset, grid: Sequence[MomentumParameters],
                    settings: ExecutionSettings, jobs: int = 1) -> pd.DataFrame:
    calendar = dataset.calendar
    tasks = [(p, settings, calendar[0], calendar[-1], "full") for p in grid]
    return pd.DataFrame(run_many(dataset, tasks, jobs))


@dataclass
class WalkForwardWindow:
    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    candidates: pd.DataFrame  # in-sample results for every parameter set
    selected: MomentumParameters
    selected_train_sharpe: float
    test: BacktestRecord


@dataclass
class WalkForwardResult:
    windows: List[WalkForwardWindow]
    train_bars: int
    test_bars: int
    selection_metric: str
    trials_per_window: int

    def oos_returns(self) -> pd.Series:
        parts = [w.test.evaluation_equity.pct_change().iloc[1:] for w in self.windows]
        return pd.concat(parts)


def walk_forward(dataset: MarketDataset, grid: Sequence[MomentumParameters], settings: ExecutionSettings,
                 train_bars: int = 504, test_bars: int = 126, jobs: int = 1) -> WalkForwardResult:
    """Rolling train/test evaluation.

    For each window the parameter set with the best in-sample Sharpe on the training
    bars is chosen, then run once on the following, untouched test bars. Every window
    starts flat with the initial capital; history before a window is read for signals
    only. The final window absorbs any bars left over at the end of the data.
    """
    calendar = dataset.calendar
    starts = list(range(train_bars, len(calendar) - test_bars + 1, test_bars))
    bounds = []
    for k, test_start in enumerate(starts):
        test_stop = starts[k + 1] if k + 1 < len(starts) else len(calendar)
        bounds.append((test_start - train_bars, test_start, test_stop))

    tasks = [(p, settings, calendar[a], calendar[b - 1], k)
             for k, (a, b, _) in enumerate(bounds) for p in grid]
    rows = pd.DataFrame(run_many(dataset, tasks, jobs))

    windows = []
    for k, (a, b, c) in enumerate(bounds):
        candidates = rows[rows["tag"] == k].reset_index(drop=True)
        eligible = candidates[(candidates["status"] == "ok") & candidates["sharpe"].notna()]
        best = eligible.loc[eligible["sharpe"].idxmax()]
        selected = next(p for p in grid if p.label() == best["label"])
        test = run_backtest(dataset, selected, settings,
                            start=_warmup_start(dataset, calendar[b], selected),
                            end=calendar[c - 1], trade_from=calendar[b],
                            label=f"walk-forward window {k + 1} ({selected.label()})")
        windows.append(WalkForwardWindow(k + 1, calendar[a], calendar[b - 1], calendar[b], calendar[c - 1],
                                         candidates, selected, float(best["sharpe"]), test))
    return WalkForwardResult(windows, train_bars, test_bars, "in-sample Sharpe (net of costs)", len(grid))
