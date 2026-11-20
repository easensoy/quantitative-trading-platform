"""Daily return distribution: empirical tail estimates next to fitted (modeled) ones."""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd
from scipy import stats


def return_distribution(returns: pd.Series, levels=(0.95, 0.99)) -> Dict[str, float]:
    """Summary of a return sample.

    Empirical VaR/ES come straight from the sample (historical simulation). The
    "normal" and "student_t" entries come from distributions fitted to the sample by
    maximum likelihood; they are models, not observations. VaR and ES are reported as
    positive loss fractions.
    """
    r = returns.dropna().to_numpy(dtype=float)
    mean, std = r.mean(), r.std(ddof=1)
    t_dof, t_loc, t_scale = stats.t.fit(r)
    out = {
        "observations": len(r),
        "mean": mean,
        "std": std,
        "skewness": float(stats.skew(r, bias=False)),
        "excess_kurtosis": float(stats.kurtosis(r, bias=False)),
        "t_dof": float(t_dof),
        "t_loc": float(t_loc),
        "t_scale": float(t_scale),
    }
    for q in (0.01, 0.05, 0.5, 0.95, 0.99):
        out[f"quantile_{int(q * 100):02d}"] = float(np.quantile(r, q))
    for level in levels:
        tag = int(round(level * 100))
        cutoff = np.quantile(r, 1 - level)
        z = stats.norm.ppf(1 - level)
        out[f"var{tag}_empirical"] = float(-cutoff)
        out[f"es{tag}_empirical"] = float(-r[r <= cutoff].mean())
        out[f"var{tag}_normal"] = float(-(mean + z * std))
        out[f"es{tag}_normal"] = float(-(mean - std * stats.norm.pdf(z) / (1 - level)))
        out[f"var{tag}_student_t"] = float(-stats.t.ppf(1 - level, t_dof, t_loc, t_scale))
    out["tail_days_beyond_3sd"] = int((np.abs(r - mean) > 3 * std).sum())
    out["expected_beyond_3sd_normal"] = float(len(r) * 2 * stats.norm.sf(3))
    return out


def normal_qq(returns: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
    """Standardized sample quantiles against standard normal quantiles (Hazen positions)."""
    r = np.sort(returns.dropna().to_numpy(dtype=float))
    standardized = (r - r.mean()) / r.std(ddof=1)
    positions = (np.arange(1, len(r) + 1) - 0.5) / len(r)
    return stats.norm.ppf(positions), standardized
