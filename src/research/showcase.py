"""The README showcase study: configuration, calculations and consistency checks.

build_showcase() runs every experiment and analytic behind the README figures and
returns plain data (ShowcaseResults); src.reporting renders it. The configuration below
was fixed before the first run; changing it is a new study, not a tweak.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.analytics import attribution, capacity, distribution, drawdowns, exposure, performance, trades, uncertainty
from src.research import benchmarks, provenance
from src.research.datasets import MarketDataset, load_dataset
from src.research.experiments import (
    BacktestRecord, ExecutionSettings, WalkForwardResult, parameter_grid, parameter_sweep, run_backtest,
    walk_forward,
)
from src.research.strategies import STRATEGY_VERSION, MomentumParameters, TimeSeriesMomentumStrategy

REPO_ROOT = Path(__file__).resolve().parents[2]
# Version of the definitions in docs/methodology.md (metrics, validation methods, checks);
# it changes whenever one of them does. Recorded in the manifest with the document's hash.
METHODOLOGY_VERSION = "1.0"
METHODOLOGY_DOCUMENT = "docs/methodology.md"


@dataclass(frozen=True)
class ShowcaseConfig:
    dataset_dir: Path = REPO_ROOT / "data" / "demo" / "synthetic_universe_v1"
    params: MomentumParameters = MomentumParameters()
    settings: ExecutionSettings = ExecutionSettings()
    rolling_vol_window: int = 63  # about three months
    rolling_sharpe_window: int = 126  # about six months
    correlation_min_overlap: int = 252
    sweep_lookbacks: Tuple[int, ...] = (10, 20, 40, 60, 120, 250)
    sweep_rebalances: Tuple[int, ...] = (1, 5, 10, 21)
    train_bars: int = 504  # two years
    test_bars: int = 126  # six months
    bootstrap_horizon: Optional[int] = None  # None: one year of observations
    bootstrap_mean_block: int = 21
    bootstrap_samples: int = 5000
    bootstrap_seed: int = 20261121
    capital_levels: Tuple[float, ...] = (1e6, 3e6, 1e7, 3e7, 1e8, 3e8, 1e9, 3e9)
    impact_coefficients: Tuple[float, ...] = (0.5, 1.0, 2.0)
    benchmark_symbols: Tuple[int, ...] = (1, 4, 16)
    benchmark_bars: Tuple[int, ...] = (252, 504, 1008, 2016)
    benchmark_repeats: int = 3
    bus_events: int = 20_000
    latency_orders: int = 2_000


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class ShowcaseResults:
    config: ShowcaseConfig
    dataset: MarketDataset
    record: BacktestRecord
    benchmark_returns: pd.Series
    stats: Dict
    returns: pd.Series
    rolling_vol: pd.Series
    rolling_sharpe: pd.Series
    monthly: pd.DataFrame
    episodes: pd.DataFrame
    top_drawdowns: pd.DataFrame
    max_drawdown_episode: Optional[pd.Series]  # the episode behind stats["max_drawdown"]; None if no drawdown
    return_summary: Dict
    qq: Tuple[np.ndarray, np.ndarray]
    exposures: pd.DataFrame
    weights: pd.DataFrame
    concentration: pd.DataFrame
    sector_weights: pd.DataFrame
    correlations: pd.DataFrame
    overlap: pd.DataFrame
    coverage: pd.DataFrame
    decomposition: attribution.PnLDecomposition
    closed_trades: pd.DataFrame
    open_lots: pd.DataFrame
    trade_stats: Dict
    turnover: pd.DataFrame
    annual_turnover: float
    fill_delays: pd.Series
    sweep: pd.DataFrame
    walk_forward: WalkForwardResult
    oos_stats: Dict
    bootstrap: pd.DataFrame
    regimes: Optional[pd.DataFrame]
    benchmark_regimes: Optional[pd.DataFrame]
    capacity_curves: Dict[str, pd.DataFrame]
    ppy: float
    liquidity: pd.DataFrame
    engineering: Optional[Dict]
    environment: Dict
    provenance: Dict  # source, dependencies, inputs and versions; see src/research/provenance.py
    checks: List[Check] = field(default_factory=list)
    # Presentation-ready derivations (still calculations; figures only draw them).
    cumulative: Optional[pd.DataFrame] = None
    drawdown_series: Optional[pd.Series] = None
    regime_spans: List[Tuple[pd.Timestamp, pd.Timestamp]] = field(default_factory=list)
    symbol_order: List[str] = field(default_factory=list)
    symbol_labels: Dict[str, str] = field(default_factory=dict)
    weekly_weights: Optional[pd.DataFrame] = None
    weight_status: Optional[pd.DataFrame] = None  # 0 not listed, 1 warm-up, 2 eligible
    required_history: int = 0  # bars the signal needs before an instrument can trade
    focus_symbol: str = ""
    focus_closes: Optional[pd.Series] = None
    focus_fills: Optional[pd.DataFrame] = None
    focus_position: Optional[pd.Series] = None
    wf_table: Optional[pd.DataFrame] = None
    oos_equity: Optional[pd.Series] = None
    wf_reference: Optional[pd.Series] = None
    sweep_sharpe: Optional[pd.DataFrame] = None
    sweep_cost: Optional[pd.DataFrame] = None
    sweep_status: Optional[pd.DataFrame] = None
    bootstrap_quantiles: Dict[str, float] = field(default_factory=dict)
    capacity_breakeven: float = float("nan")
    latency: Dict[str, Dict] = field(default_factory=dict)
    scaling_slope: float = float("nan")
    throughput: float = float("nan")

    @property
    def years(self) -> float:
        return performance.calendar_years(self.record.equity.index)


def report_provenance(dataset: MarketDataset, strategy_version: str) -> Dict:
    """Source, dependency and input fingerprints plus versions for the manifest."""
    inputs = {"dataset": dataset.name, "origin": dataset.origin, "files": dataset.file_fingerprints()}
    versions = {"strategy": strategy_version, "methodology": METHODOLOGY_VERSION,
                "methodology_document": {METHODOLOGY_DOCUMENT: provenance.file_fingerprints(
                    REPO_ROOT, [METHODOLOGY_DOCUMENT])[METHODOLOGY_DOCUMENT]}}
    return provenance.collect(inputs, versions, REPO_ROOT)


def max_drawdown_episode(episodes: pd.DataFrame, max_drawdown: float) -> Optional[pd.Series]:
    """drawdowns.deepest_episode(), refusing to continue if it does not match the reported value."""
    episode = drawdowns.deepest_episode(episodes)
    depth = 0.0 if episode is None else float(episode["depth"])
    if not abs(depth - max_drawdown) <= 1e-12:
        raise ValueError(f"deepest drawdown episode ({depth:.6%}) does not match max drawdown ({max_drawdown:.6%})")
    return episode


def build_showcase(config: ShowcaseConfig = ShowcaseConfig(), dataset: Optional[MarketDataset] = None,
                   jobs: int = 1, include_engineering: bool = True, log=print) -> ShowcaseResults:
    dataset = dataset or load_dataset(config.dataset_dir)
    log(f"dataset {dataset.name} ({dataset.origin}): {len(dataset.symbols)} instruments, "
        f"{len(dataset.calendar)} dates")

    record = run_backtest(dataset, config.params, config.settings,
                          label=f"{STRATEGY_VERSION} {config.params.label()} (pre-registered)")
    log(f"main run {record.run_id}: {len(record.executions)} fills in {record.runtime_seconds:.2f}s")
    closes, volumes = dataset.closes(), dataset.volumes()
    benchmark_returns = performance.equal_weight_benchmark(closes)
    equity = record.equity
    returns = performance.simple_returns(equity)
    ppy = performance.periods_per_year(equity.index)
    years = performance.calendar_years(equity.index)
    horizon = config.bootstrap_horizon or int(round(ppy))
    final_q, final_marks = record.quantities.iloc[-1], record.marks.iloc[-1]

    decomposition = attribution.decompose_pnl(record.executions, final_q, final_marks,
                                              config.settings.initial_capital, equity.iloc[-1])
    closed, open_lots = trades.round_trips(record.executions, final_marks)
    w = exposure.weights(record.quantities, record.marks, equity)
    corr, overlap = exposure.return_correlations(closes, config.correlation_min_overlap)

    log("parameter sweep ...")
    grid = parameter_grid(config.sweep_lookbacks, config.sweep_rebalances, base=config.params)
    sweep = parameter_sweep(dataset, grid, config.settings, jobs=jobs)
    log("walk-forward ...")
    wf = walk_forward(dataset, grid, config.settings, config.train_bars, config.test_bars, jobs=jobs)
    oos = wf.oos_returns()
    oos_equity = pd.concat([pd.Series([config.settings.initial_capital], index=[wf.windows[0].test_start]),
                            config.settings.initial_capital * (1 + oos).cumprod()])
    oos_equity = oos_equity[~oos_equity.index.duplicated(keep="first")]

    log("bootstrap ...")
    paths = uncertainty.stationary_bootstrap(returns.to_numpy(), horizon,
                                             config.bootstrap_mean_block, config.bootstrap_samples,
                                             config.bootstrap_seed)
    regimes = benchmark_regimes = None
    if dataset.regimes is not None:
        regimes = uncertainty.regime_statistics(returns, dataset.regimes, ppy)
        benchmark_regimes = uncertainty.regime_statistics(benchmark_returns, dataset.regimes, ppy)

    liquidity = capacity.fill_liquidity(record.executions, closes, volumes)
    curves = {
        f"impact_{y:g}": capacity.capacity_curve(liquidity, decomposition.frictionless,
                                                 config.settings.initial_capital, config.capital_levels,
                                                 years,
                                                 impact_coefficient=y)
        for y in config.impact_coefficients
    }
    curves["no_commission"] = capacity.capacity_curve(liquidity, decomposition.frictionless,
                                                      config.settings.initial_capital, config.capital_levels,
                                                      years,
                                                      impact_coefficient=1.0, commission_scale=0.0)

    engineering = run_engineering(config, log) if include_engineering else None
    stats = performance.summary_statistics(equity, benchmark_returns)
    episodes = drawdowns.drawdown_episodes(equity)

    results = ShowcaseResults(
        config=config, dataset=dataset, record=record, benchmark_returns=benchmark_returns,
        stats=stats, returns=returns,
        rolling_vol=performance.rolling_volatility(returns, config.rolling_vol_window, ppy),
        rolling_sharpe=performance.rolling_sharpe(returns, config.rolling_sharpe_window, ppy),
        monthly=performance.monthly_returns(returns),
        episodes=episodes, top_drawdowns=drawdowns.largest_drawdowns(equity, 5),
        max_drawdown_episode=max_drawdown_episode(episodes, stats["max_drawdown"]),
        return_summary=distribution.return_distribution(returns), qq=distribution.normal_qq(returns),
        exposures=exposure.exposures(record.quantities, record.marks, equity), weights=w,
        concentration=exposure.concentration(w),
        sector_weights=exposure.sector_weights(w, {s: dataset.sector_of(s) for s in dataset.symbols}),
        correlations=corr, overlap=overlap, coverage=exposure.history_coverage(closes),
        decomposition=decomposition, closed_trades=closed, open_lots=open_lots,
        trade_stats=trades.trade_statistics(closed),
        turnover=trades.monthly_turnover(record.executions, equity),
        annual_turnover=trades.annualized_turnover(record.executions, equity),
        fill_delays=trades.fill_delays(record.executions),
        sweep=sweep, walk_forward=wf, oos_stats=performance.summary_statistics(oos_equity),
        bootstrap=uncertainty.path_statistics(paths, ppy), regimes=regimes, benchmark_regimes=benchmark_regimes,
        capacity_curves=curves, ppy=ppy, liquidity=liquidity, engineering=engineering,
        environment=benchmarks.machine_info(),
        provenance=report_provenance(dataset, record.strategy_version),
    )
    derive_presentation_data(results, oos_equity)
    results.checks = run_checks(results)
    return results


def run_engineering(config: ShowcaseConfig, log=print) -> Dict:
    """Measure the engine on this machine. Latency samples are reduced to summaries and
    quantile curves so the result can be stored and reused without re-measuring."""
    log("engineering benchmarks ...")
    samples = {
        "event bus dispatch": benchmarks.event_bus_latency(config.bus_events),
        "order to portfolio": benchmarks.order_to_portfolio_latency(config.latency_orders),
    }
    probabilities = np.linspace(0.0, 1.0, 401)
    return {
        "measured_on": str(pd.Timestamp.now().date()),
        "machine": benchmarks.machine_info(),
        "scaling": benchmarks.backtest_scaling(config.benchmark_symbols, config.benchmark_bars,
                                               config.benchmark_repeats),
        "latency": {name: benchmarks.latency_summary(values) for name, values in samples.items()},
        "latency_curves": {name: {"probability": probabilities.tolist(),
                                  "us": np.quantile(values / 1e3, probabilities).tolist()}
                           for name, values in samples.items()},
    }


def _contiguous_spans(mask: pd.Series) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    spans, start, previous = [], None, None
    for date, flag in mask.items():
        if flag and start is None:
            start = date
        if not flag and start is not None:
            spans.append((start, previous))
            start = None
        previous = date
    if start is not None:
        spans.append((start, previous))
    return spans


def derive_presentation_data(res: ShowcaseResults, oos_equity: pd.Series) -> None:
    rec, ds, cfg = res.record, res.dataset, res.config
    returns, bench = res.returns, res.benchmark_returns.reindex(res.returns.index)
    strategy_growth, bench_growth = (1 + returns).cumprod(), (1 + bench).cumprod()
    res.cumulative = pd.DataFrame({"strategy": strategy_growth - 1, "benchmark": bench_growth - 1,
                                   "relative": strategy_growth / bench_growth - 1})
    res.drawdown_series = performance.drawdown(rec.equity)
    if ds.regimes is not None:
        regimes = ds.regimes.reindex(rec.equity.index)
        res.regime_spans = _contiguous_spans(regimes == "turbulent")

    sector_rank = {s: i for i, s in enumerate(sorted({ds.sector_of(x) or "~" for x in ds.symbols}))}
    res.symbol_order = sorted(ds.symbols, key=lambda s: (sector_rank[ds.sector_of(s) or "~"], s))
    res.symbol_labels = {s: f"{s} · {ds.sector_of(s) or 'no sector'}" for s in ds.symbols}

    weekly = res.weights.resample("W-FRI").last()
    res.weekly_weights = weekly
    closes = ds.closes()
    bars_so_far = closes.notna().cumsum().reindex(weekly.index, method="ffill")
    need = TimeSeriesMomentumStrategy(cfg.params).required_history
    status = pd.DataFrame(2, index=weekly.index, columns=weekly.columns)
    status = status.where(bars_so_far >= need, 1).where(bars_so_far > 0, 0)
    res.weight_status = status
    res.required_history = need

    focus = res.decomposition.by_symbol["net"].abs().idxmax()
    res.focus_symbol = focus
    res.focus_closes = ds.bars[focus]["close"]
    res.focus_fills = rec.executions[rec.executions["symbol"] == focus]
    res.focus_position = rec.quantities[focus]

    rows = []
    for w in res.walk_forward.windows:
        test_returns = w.test.evaluation_equity.pct_change().iloc[1:]
        rows.append({"window": w.index, "train_start": w.train_start, "train_end": w.train_end,
                     "test_start": w.test_start, "test_end": w.test_end, "selected": w.selected.label(),
                     "train_sharpe": w.selected_train_sharpe,
                     "test_sharpe": performance.sharpe_ratio(test_returns, res.ppy),
                     "test_return": float(w.test.evaluation_equity.iloc[-1] / w.test.evaluation_equity.iloc[0] - 1)})
    res.wf_table = pd.DataFrame(rows)
    res.oos_equity = oos_equity
    reference = rec.equity.loc[oos_equity.index[0]:]
    res.wf_reference = reference / reference.iloc[0] * cfg.settings.initial_capital

    sweep = res.sweep.set_index(["lookback", "rebalance_every"])
    res.sweep_sharpe = sweep["sharpe"].unstack()
    res.sweep_cost = sweep["cost_pa"].unstack()
    res.sweep_status = sweep["status"].unstack()

    boot = res.bootstrap
    res.bootstrap_quantiles = {
        "p_loss": float((boot["total_return"] < 0).mean()),
        "p_dd_20": float((boot["max_drawdown"] < -0.20).mean()),
        **{f"return_p{p}": float(boot["total_return"].quantile(p / 100)) for p in (5, 50, 95)},
        **{f"drawdown_p{p}": float(boot["max_drawdown"].quantile(p / 100)) for p in (5, 50, 95)},
        **{f"sharpe_p{p}": float(boot["sharpe"].quantile(p / 100)) for p in (5, 50, 95)},
    }

    curve = res.capacity_curves["impact_1"]
    negative = curve[curve["net_return_pa"] < 0]
    if len(negative) and negative.index[0] > 0:
        i = negative.index[0]
        x0, x1 = np.log(curve.loc[i - 1, "capital"]), np.log(curve.loc[i, "capital"])
        y0, y1 = curve.loc[i - 1, "net_return_pa"], curve.loc[i, "net_return_pa"]
        res.capacity_breakeven = float(np.exp(x0 + (0 - y0) * (x1 - x0) / (y1 - y0)))

    if res.engineering:
        attach_engineering(res, res.engineering)


def attach_engineering(res: ShowcaseResults, eng: Dict) -> None:
    res.engineering = eng
    res.latency = eng["latency"]
    scaling = eng["scaling"]
    if len(scaling) > 1:
        slope, _ = np.polyfit(np.log(scaling["symbol_bars"]), np.log(scaling["median_seconds"]), 1)
        res.scaling_slope = float(slope)
        largest = scaling[scaling["symbol_bars"] >= scaling["symbol_bars"].quantile(0.75)]
        res.throughput = float(largest["symbol_bars_per_second"].median())


def run_checks(results: ShowcaseResults) -> List[Check]:
    r = results.record
    equity = r.equity
    checks: List[Check] = []

    def check(name, passed, detail):
        checks.append(Check(name, bool(passed), detail))

    try:
        performance.assert_business_daily(equity.index)
        check("Business-day calendar", True, f"{len(equity)} bars, no weekend or duplicate timestamps")
    except ValueError as exc:
        check("Business-day calendar", False, str(exc))
    growth = equity.iloc[-1] / equity.iloc[0]
    cagr_calendar = growth ** (1 / results.years) - 1
    calendar = results.dataset.manifest.get("calendar", "calendar taken from the data")
    error = np.sqrt(results.ppy / 252) - 1
    check("Annualization", 240 <= results.ppy <= 270 and abs(results.stats["cagr"] - cagr_calendar) < 1e-9,
          f"{results.ppy:.1f} return observations per calendar year over {results.years:.2f} years; "
          f"calendar: {calendar}; a fixed 252 would {'understate' if error > 0 else 'overstate'} volatility by "
          f"{abs(error):.1%}")
    finite = np.isfinite(equity.to_numpy()).all() and (equity > 0).all()
    check("Equity finite and positive", finite, f"min {equity.min():,.0f}, max {equity.max():,.0f}")
    marked = (r.quantities * r.marks.reindex_like(r.quantities)).where(r.quantities != 0, 0.0).fillna(0.0).sum(axis=1)
    gap = (equity - (r.cash + marked)).abs().max()
    check("Ledger identity", gap < 1e-6, f"max |equity - (cash + positions at marks)| = {gap:.2e}")
    missing = int(r.marks.where(r.quantities != 0).isna().where(r.quantities != 0, False).sum().sum())
    check("No missing marks", missing == 0,
          f"{missing} open positions without a mark; {int((r.stale_marks > 0).sum())} bars used a carried-forward close")
    d = results.decomposition
    check("P&L decomposition reconciles", abs(d.residual) < 0.01,
          f"frictionless - slippage - commissions = {d.net:,.2f}; equity change = {d.equity_change:,.2f}")
    realized = results.closed_trades["net_pnl"].sum() if len(results.closed_trades) else 0.0
    unrealized = results.open_lots["unrealized_net"].sum() if len(results.open_lots) else 0.0
    check("FIFO trades reconcile", abs(realized + unrealized - d.equity_change) < 0.01,
          f"realized {realized:,.2f} + open {unrealized:,.2f} vs {d.equity_change:,.2f}")
    check("Slippage counted once", abs(d.slippage - r.executions["slippage_cost"].sum()) < 1e-6,
          "slippage is inside fill prices; shown as a component, not deducted again")
    required = ["total_return", "cagr", "annualized_volatility", "sharpe", "sortino", "max_drawdown", "beta"]
    bad = [k for k in required if not np.isfinite(results.stats.get(k, np.nan))]
    check("Finite headline metrics", not bad, "all finite" if not bad else f"non-finite: {bad}")
    common = results.returns.index.intersection(results.benchmark_returns.index)
    check("Benchmark alignment", len(common) == len(results.returns),
          f"{len(common)} of {len(results.returns)} strategy dates have a benchmark return")
    wf = results.walk_forward
    disjoint = all(w.train_end < w.test_start for w in wf.windows) and all(
        a.test_end < b.test_start for a, b in zip(wf.windows, wf.windows[1:]))
    check("Walk-forward separation", disjoint,
          f"{len(wf.windows)} windows; every test window starts after its training window ends")
    failed = results.sweep[results.sweep["status"] != "ok"]
    grid_size = len(results.config.sweep_lookbacks) * len(results.config.sweep_rebalances)
    check("Sweep accounted for", len(results.sweep) == grid_size,
          f"{len(results.sweep)} runs, {len(failed)} not ok (kept in the report)")
    check("No strategy errors", not r.strategy_errors, f"{len(r.strategy_errors)} errors during the main run")
    return checks
