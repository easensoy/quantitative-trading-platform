"""Drawdown episodes: peak, trough, recovery, depth and durations."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

COLUMNS = ["peak", "trough", "recovery", "depth", "peak_to_trough_bars", "recovery_bars",
           "duration_bars", "recovered"]


def drawdown_episodes(equity: pd.Series) -> pd.DataFrame:
    """One row per episode, ordered by start.

    An episode starts at the last running peak before equity falls below it and ends on
    the first bar that regains that peak. An episode still open on the last bar is
    reported with recovered=False, no recovery date and its duration measured to the
    last bar. Durations count bars (trading days).
    """
    values = equity.to_numpy(dtype=float)
    dates = equity.index
    episodes = []
    peak_pos = 0
    trough_pos = None
    for pos in range(1, len(values)):
        if values[pos] >= values[peak_pos]:
            if trough_pos is not None:
                episodes.append(_episode(dates, values, peak_pos, trough_pos, pos))
                trough_pos = None
            peak_pos = pos
        elif trough_pos is None or values[pos] < values[trough_pos]:
            trough_pos = pos
    if trough_pos is not None:
        episodes.append(_episode(dates, values, peak_pos, trough_pos, None))
    return pd.DataFrame(episodes, columns=COLUMNS)


def _episode(dates, values, peak, trough, recovery):
    end = recovery if recovery is not None else len(values) - 1
    return {
        "peak": dates[peak],
        "trough": dates[trough],
        "recovery": dates[recovery] if recovery is not None else pd.NaT,
        "depth": values[trough] / values[peak] - 1.0,
        "peak_to_trough_bars": trough - peak,
        "recovery_bars": (recovery - trough) if recovery is not None else np.nan,
        "duration_bars": end - peak,
        "recovered": recovery is not None,
    }


def deepest_episode(episodes: pd.DataFrame) -> Optional[pd.Series]:
    """The episode behind the maximum drawdown, or None if equity never fell below a peak.

    Ties: if several episodes have exactly the same depth, the earliest (by peak date) is
    returned. That is the episode in which the running drawdown first reaches its minimum,
    so its depth equals performance.summary_statistics()["max_drawdown"], and its peak,
    trough, recovery date and recovered flag all describe that same episode.
    """
    if episodes.empty:
        return None
    ordered = episodes.sort_values("peak", kind="mergesort")
    return ordered.iloc[int(np.argmin(ordered["depth"].to_numpy(dtype=float)))]


def largest_drawdowns(equity: pd.Series, n: int = 5) -> pd.DataFrame:
    """The n deepest episodes, deepest first. The sort is stable, so equal depths keep
    chronological order and row 0 is always deepest_episode()."""
    episodes = drawdown_episodes(equity)
    return episodes.sort_values("depth", kind="mergesort").head(n).reset_index(drop=True)
