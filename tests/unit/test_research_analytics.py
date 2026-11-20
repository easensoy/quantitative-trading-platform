"""Calculations behind the research reports, checked on hand-built cases and on small
synthetic backtests (no market data access)."""
import numpy as np
import pandas as pd
import pytest

from src.analytics.attribution import decompose_pnl
from src.analytics.capacity import capacity_curve, fill_liquidity
from src.analytics.distribution import normal_qq, return_distribution
from src.analytics.drawdowns import drawdown_episodes, largest_drawdowns
from src.analytics.exposure import exposures, return_correlations, sector_weights, weights, UNCLASSIFIED
from src.analytics.performance import (
    assert_business_daily, equal_weight_benchmark, monthly_returns, periods_per_year, summary_statistics,
)
from src.analytics.trades import round_trips, trade_statistics
from src.analytics.uncertainty import path_statistics, stationary_bootstrap
from src.research.datasets import InstrumentSpec, SyntheticUniverseSpec, generate_synthetic_universe
from src.research.experiments import ExecutionSettings, parameter_grid, run_backtest, run_many
from src.research.strategies import MomentumParameters

SMALL_SPEC = SyntheticUniverseSpec(
    name="test_universe", seed=7, start="2020-01-01", end="2021-12-31",
    instruments=(
        InstrumentSpec("AAA", "Tech", 100.0, 1.0, 0.5, 0.20, 1_000_000),
        InstrumentSpec("BBB", "Tech", 50.0, 1.1, 0.5, 0.25, 800_000),
        InstrumentSpec("CCC", None, 20.0, 1.2, 0.0, 0.30, 500_000, listed_from="2020-07-01"),
    ),
    halted_symbol="BBB", halted_days=2,
)
FAST = MomentumParameters(lookback=20, rebalance_every=5, vol_window=20)


@pytest.fixture(scope="module")
def dataset():
    return generate_synthetic_universe(SMALL_SPEC)


@pytest.fixture(scope="module")
def record(dataset):
    return run_backtest(dataset, FAST)


def series(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


# ------------------------------------------------------------------ performance

def test_drawdown_episodes_track_recovery_and_open_drawdowns():
    episodes = drawdown_episodes(series([100, 110, 99, 105, 111, 100, 95]))

    first, second = episodes.iloc[0], episodes.iloc[1]
    assert first["depth"] == pytest.approx(99 / 110 - 1)
    assert (first["peak_to_trough_bars"], first["recovery_bars"], first["duration_bars"]) == (1, 2, 3)
    assert first["recovered"]
    assert second["depth"] == pytest.approx(95 / 111 - 1)
    assert not second["recovered"] and pd.isna(second["recovery"])
    assert largest_drawdowns(series([100, 110, 99, 105, 111, 100, 95]), 1)["depth"].iloc[0] == pytest.approx(95 / 111 - 1)


def test_summary_statistics_definitions():
    returns = np.array([0.01, -0.005, 0.02, -0.01, 0.0, 0.015])
    equity = series(np.concatenate([[100.0], 100.0 * np.cumprod(1 + returns)]))
    benchmark = pd.Series(returns / 2, index=equity.index[1:])

    stats = summary_statistics(equity, benchmark, ppy=252)

    assert stats["total_return"] == pytest.approx(np.prod(1 + returns) - 1)
    assert stats["annualized_volatility"] == pytest.approx(returns.std(ddof=1) * np.sqrt(252))
    assert stats["sharpe"] == pytest.approx(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
    assert stats["hit_rate"] == pytest.approx(3 / 5)  # zero-return days are excluded
    assert stats["beta"] == pytest.approx(2.0)
    assert stats["correlation"] == pytest.approx(1.0)


def test_annualization_uses_observed_frequency():
    weekdays = pd.bdate_range("2019-01-01", "2023-12-29")  # no holidays: about 261 a year
    assert periods_per_year(weekdays) == pytest.approx(261.0, abs=0.5)
    equity = pd.Series(np.linspace(100, 121, len(weekdays)), index=weekdays)
    stats = summary_statistics(equity)
    years = (weekdays[-1] - weekdays[0]).days / 365.25
    assert stats["cagr"] == pytest.approx(1.21 ** (1 / years) - 1)


def test_business_daily_check_rejects_calendar_daily_data():
    assert_business_daily(pd.bdate_range("2024-01-01", periods=30))
    with pytest.raises(ValueError, match="weekend"):
        assert_business_daily(pd.date_range("2024-01-01", periods=30, freq="D"))


def test_monthly_returns_compound_within_month():
    returns = pd.Series([0.1, 0.1, -0.5], index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-02-01"]))
    table = monthly_returns(returns)
    assert table.loc[2024, 1] == pytest.approx(0.21)
    assert table.loc[2024, 2] == pytest.approx(-0.5)
    assert table.loc[2024, "year"] == pytest.approx(1.21 * 0.5 - 1)


def test_benchmark_takes_the_gap_return_when_trading_resumes():
    dates = pd.bdate_range("2024-01-01", periods=4)
    closes = pd.DataFrame({"A": [10.0, 11.0, 12.0, 13.2], "B": [20.0, np.nan, np.nan, 22.0]}, index=dates)
    benchmark = equal_weight_benchmark(closes)
    assert benchmark.iloc[0] == pytest.approx(0.1)  # only A trades
    assert benchmark.iloc[2] == pytest.approx((0.1 + 0.1) / 2)  # B: 22/20 - 1 over the halt


# ------------------------------------------------------------------ distribution and exposure

def test_empirical_and_modeled_tail_estimates_are_separate():
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.standard_t(4, 5000) * 0.01)
    summary = return_distribution(returns)
    assert summary["var95_empirical"] == pytest.approx(-np.quantile(returns, 0.05))
    assert summary["es95_empirical"] >= summary["var95_empirical"]
    assert summary["var95_normal"] == pytest.approx(-(returns.mean() - 1.6448536 * returns.std()), rel=1e-6)
    assert 2.5 < summary["t_dof"] < 6.5  # fat tails recovered by the t fit
    theoretical, sample = normal_qq(returns)
    assert len(theoretical) == len(sample) == 5000 and np.all(np.diff(sample) >= 0)


def test_exposure_identities_and_unclassified_sector():
    dates = pd.bdate_range("2024-01-01", periods=2)
    quantities = pd.DataFrame({"A": [10, 10], "B": [0, -5]}, index=dates)
    marks = pd.DataFrame({"A": [10.0, 12.0], "B": [np.nan, 20.0]}, index=dates)
    equity = pd.Series([1000.0, 1000.0], index=dates)

    exp = exposures(quantities, marks, equity)
    assert exp.loc[dates[1], "long"] == pytest.approx(0.12)
    assert exp.loc[dates[1], "short"] == pytest.approx(-0.10)
    assert exp.loc[dates[1], "gross"] == pytest.approx(0.22)
    assert exp.loc[dates[1], "net"] == pytest.approx(0.02)
    sectors = sector_weights(weights(quantities, marks, equity), {"A": "Tech", "B": None})
    assert list(sectors.columns) == ["Tech", UNCLASSIFIED]


def test_correlations_require_enough_overlap(dataset):
    corr, overlap = return_correlations(dataset.closes(), min_overlap=450)
    assert overlap.loc["AAA", "CCC"] < 450 <= overlap.loc["AAA", "BBB"]  # CCC listed in July 2020
    assert np.isnan(corr.loc["AAA", "CCC"])
    assert np.isfinite(corr.loc["AAA", "BBB"])


# ------------------------------------------------------------------ accounting on a real backtest

def test_pnl_decomposition_reconciles_to_equity(record):
    final_q = record.quantities.iloc[-1]
    decomposition = decompose_pnl(record.executions, final_q, record.marks.iloc[-1],
                                  record.settings.initial_capital, record.equity.iloc[-1])
    assert len(record.executions) > 20
    assert decomposition.residual == pytest.approx(0.0, abs=1e-6)
    assert decomposition.net == pytest.approx(
        decomposition.frictionless - decomposition.slippage - decomposition.commissions)
    assert decomposition.slippage == pytest.approx(record.executions["slippage_cost"].sum())
    assert decomposition.slippage > 0 and decomposition.commissions > 0
    assert decomposition.financing is None
    assert decomposition.by_symbol["net"].sum() == pytest.approx(decomposition.net)


def test_round_trips_reconcile_with_net_pnl(record):
    closed, open_lots = round_trips(record.executions, record.marks.iloc[-1])
    realized = closed["net_pnl"].sum()
    unrealized = open_lots["unrealized_net"].sum() if len(open_lots) else 0.0
    assert realized + unrealized == pytest.approx(record.equity.iloc[-1] - record.settings.initial_capital, abs=1e-4)
    assert (closed["holding_bars"] >= 1).all()
    assert trade_statistics(closed)["closed_trades"] == len(closed)


def test_round_trips_match_fifo_through_a_position_flip():
    t = pd.bdate_range("2024-01-01", periods=4)
    fills = pd.DataFrame({
        "trade_id": ["trade_0", "trade_1", "trade_2", "trade_3"],
        "symbol": "A", "side": ["buy", "sell", "sell", "buy"], "quantity": [100, 60, 60, 20],
        "filled_at": t, "fill_price": [10.0, 12.0, 9.0, 8.0], "commission": [0.0, 0.0, 0.0, 0.0],
    })
    closed, open_lots = round_trips(fills, pd.Series({"A": 8.0}))
    assert list(zip(closed["direction"], closed["quantity"], closed["gross_pnl"])) == [
        ("long", 60, pytest.approx(120.0)), ("long", 40, pytest.approx(-40.0)), ("short", 20, pytest.approx(20.0))]
    assert open_lots.empty


def test_ledger_has_no_missing_marks_for_open_positions(record):
    held = record.quantities != 0
    assert not record.marks.where(held).isna().where(held, False).any().any()
    assert np.isfinite(record.equity).all()


# ------------------------------------------------------------------ uncertainty and capacity

def test_stationary_bootstrap_is_deterministic_and_resamples_observations():
    returns = np.arange(100, dtype=float) / 1000
    first = stationary_bootstrap(returns, horizon=50, mean_block=10, samples=200, seed=3)
    again = stationary_bootstrap(returns, horizon=50, mean_block=10, samples=200, seed=3)
    np.testing.assert_array_equal(first, again)
    assert first.shape == (200, 50) and np.isin(first, returns).all()
    continued = np.isclose(np.diff(first, axis=1) % 0.1, 0.001).mean()
    assert 0.8 < continued < 0.95  # about 1 - 1/mean_block of steps continue a block
    stats = path_statistics(first)
    assert (stats["max_drawdown"] <= 0).all()


def test_capacity_impact_grows_with_capital(dataset, record):
    liquidity = fill_liquidity(record.executions, dataset.closes(), dataset.volumes())
    curve = capacity_curve(liquidity, frictionless_pnl=10_000.0, base_capital=1e6,
                           capital_levels=[1e6, 1e8], years=2.0)
    small, large = curve.iloc[0], curve.iloc[1]
    assert large["impact_pa"] == pytest.approx(small["impact_pa"] * 10.0, rel=1e-9)  # k^1.5 / k = sqrt(100)
    assert large["participation_median"] == pytest.approx(small["participation_median"] * 100)
    assert large["net_return_pa"] < small["net_return_pa"]
    assert small["commission_pa"] == pytest.approx(large["commission_pa"])


# ------------------------------------------------------------------ experiments

def test_run_ids_are_deterministic_and_input_sensitive(dataset):
    a = run_backtest(dataset, FAST)
    b = run_backtest(dataset, FAST)
    c = run_backtest(dataset, MomentumParameters(lookback=30, rebalance_every=5, vol_window=20))
    assert a.run_id == b.run_id != c.run_id
    pd.testing.assert_series_equal(a.equity, b.equity)


def test_isolated_runs_match_across_processes(dataset):
    grid = parameter_grid([10, 20], [5], base=FAST)
    calendar = dataset.calendar
    tasks = [(p, ExecutionSettings(), calendar[0], calendar[-1], "t") for p in grid]
    sequential = pd.DataFrame(run_many(dataset, tasks, jobs=1))
    parallel = pd.DataFrame(run_many(dataset, tasks, jobs=2))
    pd.testing.assert_frame_equal(sequential.drop(columns="runtime_seconds"),
                                  parallel.drop(columns="runtime_seconds"))
