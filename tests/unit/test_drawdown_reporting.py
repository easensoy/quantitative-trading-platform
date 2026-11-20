"""The maximum drawdown is described by the episode that produced it, never by the latest one."""
from types import SimpleNamespace

import pandas as pd
import pytest

from src.analytics.drawdowns import deepest_episode, drawdown_episodes, largest_drawdowns
from src.analytics.performance import summary_statistics
from src.research.showcase import max_drawdown_episode

pytest.importorskip("matplotlib")  # src.reporting renders with it (requirements_reports.txt)
from src.reporting.documents import max_drawdown_basis, metrics_table  # noqa: E402


def curve(values):
    """Equity on consecutive business days from Monday 2024-01-01."""
    return pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)


def report_stub(equity):
    """The attributes metrics_table() reads, derived from one equity curve."""
    stats = summary_statistics(equity)
    episodes = drawdown_episodes(equity)
    return SimpleNamespace(
        stats=stats, years=1.0, ppy=261.0, episodes=episodes,
        max_drawdown_episode=max_drawdown_episode(episodes, stats["max_drawdown"]),
        decomposition=SimpleNamespace(commissions=10.0, slippage=5.0),
        record=SimpleNamespace(settings=SimpleNamespace(currency="USD"), equity=equity),
        oos_stats={"total_return": -0.1, "sharpe": -0.5}, wf_table=pd.DataFrame(index=range(6)),
        bootstrap_quantiles={"p_loss": 0.4},
    )


def max_drawdown_row(equity) -> str:
    table = metrics_table(report_stub(equity))
    return next(line for line in table.splitlines() if line.startswith("| Max drawdown |"))


def test_recovered_deepest_drawdown_followed_by_a_shallower_open_one():
    equity = curve([100, 120, 90, 125, 110, 115])
    episodes = drawdown_episodes(equity)
    assert not episodes.iloc[-1]["recovered"]  # the latest episode is still open ...

    deepest = deepest_episode(episodes)  # ... but the deepest one recovered
    assert deepest["depth"] == summary_statistics(equity)["max_drawdown"] == pytest.approx(-0.25)
    assert (deepest["peak"], deepest["trough"], deepest["recovery"]) == (
        pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04"))
    assert deepest["recovered"]

    row = max_drawdown_row(equity)
    assert "Peak 2024-01-02 to trough 2024-01-03; recovered 2024-01-04" in row
    assert "not recovered" not in row and "unrecovered" not in row


def test_unrecovered_deepest_drawdown():
    equity = curve([100, 110, 105, 112, 80, 90])
    deepest = deepest_episode(drawdown_episodes(equity))

    assert deepest["depth"] == summary_statistics(equity)["max_drawdown"] == pytest.approx(80 / 112 - 1)
    assert (deepest["peak"], deepest["trough"]) == (pd.Timestamp("2024-01-04"), pd.Timestamp("2024-01-05"))
    assert not deepest["recovered"] and pd.isna(deepest["recovery"])
    assert ("Peak 2024-01-04 to trough 2024-01-05; not recovered by the end of the data (2024-01-08)"
            in max_drawdown_row(equity))


@pytest.mark.parametrize("values", [[100, 100, 100, 100], [100, 101, 102, 103]], ids=["flat", "rising"])
def test_no_drawdown_episode_for_flat_or_rising_equity(values):
    equity = curve(values)
    episodes = drawdown_episodes(equity)

    assert episodes.empty and largest_drawdowns(equity).empty
    assert deepest_episode(episodes) is None
    assert summary_statistics(equity)["max_drawdown"] == 0.0
    assert max_drawdown_episode(episodes, 0.0) is None
    assert max_drawdown_basis(None, equity.index[-1]) == "No drawdown: equity never fell below a previous peak"
    assert "No drawdown" in max_drawdown_row(equity)


def test_tied_maximum_depth_selects_the_earliest_episode():
    """Rule: among episodes of exactly equal depth, the earliest (by peak date) is the
    maximum drawdown, where the running drawdown first reaches its minimum."""
    equity = curve([100, 90, 100, 90, 95])
    episodes = drawdown_episodes(equity)
    assert len(episodes) == 2 and episodes["depth"].iloc[0] == episodes["depth"].iloc[1]  # an exact tie

    for candidates in (episodes, episodes.iloc[::-1]):  # input order does not matter
        deepest = deepest_episode(candidates)
        assert deepest["peak"] == pd.Timestamp("2024-01-01") and deepest["recovered"]
    assert list(largest_drawdowns(equity, 2)["peak"]) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]
    assert "Peak 2024-01-01 to trough 2024-01-02; recovered 2024-01-03" in max_drawdown_row(equity)


def test_an_episode_that_does_not_match_the_reported_maximum_is_refused():
    episodes = drawdown_episodes(curve([100, 120, 90, 125, 110, 115]))

    with pytest.raises(ValueError, match="does not match"):
        max_drawdown_episode(episodes, -0.12)
