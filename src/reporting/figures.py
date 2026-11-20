"""Report figures. Each function draws one figure from ShowcaseResults; no metric is
computed here (see src.research.showcase for the calculations)."""
from __future__ import annotations

from typing import Callable, Dict, List

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize, TwoSlopeNorm
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FuncFormatter

from src.reporting.theme import (
    MINUS, Theme, bare_axes, headroom, money, money_axis, new_frame, number, pct, percent_axis, short_money,
    style_axes, text_rows, twin_axis,
)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
REGENERATE = "regenerate: python scripts/generate_readme_assets.py"


# ---------------------------------------------------------------- shared pieces

def data_label(res) -> str:
    origin = res.dataset.origin
    return "SYNTHETIC DATA" if origin.startswith("synthetic") else origin.upper()


def evidence_tag(res) -> str:
    return f"{data_label(res)} · SIMULATED EXECUTION"


def provenance(res, run_line: str = None) -> List[str]:
    ds, r, s = res.dataset, res.record, res.record.settings
    first, last = r.equity.index[0].date(), r.equity.index[-1].date()
    return [
        f"Data: {ds.origin} · {ds.name} (prices.csv sha256 {ds.fingerprint[:12]}) · "
        f"{len(ds.symbols)} instruments · {first} → {last} · daily bars, Mon–Fri calendar",
        f"Execution: simulated, fills at the next bar's close · slippage {s.slippage * 1e4:.0f} bps · "
        f"commission {s.commission * 1e4:.0f} bps · financing and borrow not modeled · "
        f"initial capital {s.currency} {s.initial_capital:,.0f}",
        run_line or (f"Run {r.run_id} · strategy {r.strategy_version} {res.config.params.label()} "
                     f"(pre-registered) · {REGENERATE}"),
    ]


def year_axis(ax) -> None:
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.tick_params(axis="x", which="minor", length=1.5)


def shade_regimes(ax, res, theme: Theme, label: bool = False) -> None:
    alpha = 0.2 if theme.name == "dark" else 0.12
    for i, (start, end) in enumerate(res.regime_spans):
        ax.axvspan(start, end, color=theme.violet, alpha=alpha, lw=0,
                   label="turbulent regime (synthetic DGP label)" if label and i == 0 else None)


def heat_text(ax, x, y, text, theme: Theme, value, cmap, norm, size=6.9, weight="normal"):
    color = theme.readable_on(cmap(norm(value))) if np.isfinite(value) else theme.muted
    ax.text(x, y, text, ha="center", va="center", fontsize=size, color=color, fontweight=weight)


def legend(ax, theme: Theme, handles=None, **kwargs):
    kwargs.setdefault("loc", "upper left")
    kwargs.setdefault("ncol", 3)
    kwargs.setdefault("fontsize", 7.2)
    kwargs.setdefault("borderaxespad", 0.3)
    if handles is not None:
        kwargs["handles"] = handles
    leg = ax.legend(handlelength=1.8, columnspacing=1.2, **kwargs)
    for text in leg.get_texts():
        text.set_color(theme.muted)
    return leg


def boxed(theme: Theme, alpha: float = 0.88) -> dict:
    return dict(boxstyle="round,pad=0.3", facecolor=theme.panel, edgecolor="none", alpha=alpha)


def signed_cell(value: float, digits: int = 1) -> str:
    if abs(value) < 0.5 * 10 ** (-digits - 2):
        return f"{0:.{digits}f}"
    return f"{value * 100:+.{digits}f}".replace("-", MINUS)


# ---------------------------------------------------------------- A. tear sheet

def tearsheet(res, theme: Theme) -> plt.Figure:
    r, s, cfg = res.record, res.stats, res.config
    subtitle = (f"{r.strategy_version} {cfg.params.label()}, parameters fixed before the first run · "
                f"{len(res.dataset.symbols)} {res.dataset.origin} instruments · "
                f"{s['observations']:,} daily returns, net of costs")
    frame = new_frame(theme, 11.4, "Performance tear sheet", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.08)
    fig = frame.fig
    outer = fig.add_gridspec(3, 1, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom,
                             height_ratios=[5.0, 1.55, 2.25], hspace=0.30)
    upper = outer[0].subgridspec(3, 1, height_ratios=[2.3, 1.75, 1.05], hspace=0.38)
    middle = outer[1].subgridspec(1, 2, wspace=0.14)
    lower = outer[2].subgridspec(1, 12, wspace=0.5)
    ax_eq = fig.add_subplot(upper[0])
    ax_cum = fig.add_subplot(upper[1], sharex=ax_eq)
    ax_dd = fig.add_subplot(upper[2], sharex=ax_eq)
    ax_vol = fig.add_subplot(middle[0], sharex=ax_eq)
    ax_sh = fig.add_subplot(middle[1], sharex=ax_eq)
    ax_heat, ax_stats = fig.add_subplot(lower[0, :8]), fig.add_subplot(lower[0, 8:])

    eq, cap, cur = r.equity, r.settings.initial_capital, r.settings.currency
    style_axes(ax_eq, theme)
    ax_eq.fill_between(eq.index, eq.values, cap, where=eq.values >= cap, interpolate=True,
                       color=theme.positive, alpha=0.16, lw=0)
    ax_eq.fill_between(eq.index, eq.values, cap, where=eq.values < cap, interpolate=True,
                       color=theme.negative, alpha=0.2, lw=0)
    ax_eq.axhline(cap, color=theme.faint, lw=0.9, ls=(0, (4, 3)))
    ax_eq.plot(eq.index, eq.values, color=theme.cyan, lw=1.5)
    ax_eq.text(eq.index[-1], cap, f"initial capital {money(cap, cur, 2, compact=True)}", ha="right", va="top",
               fontsize=7.0, color=theme.muted, bbox=boxed(theme))
    first_fill = r.executions["filled_at"].min()
    ax_eq.axvline(first_fill, color=theme.faint, lw=0.8, ls=(0, (1, 2)))
    ax_eq.text(first_fill, 0.97, f" first fill after a {res.required_history}-bar signal warm-up",
               transform=ax_eq.get_xaxis_transform(), ha="left", va="top", fontsize=6.8, color=theme.faint)
    ax_eq.text(0.995, 0.97, f"final {money(eq.iloc[-1], cur, 2, compact=True)} · "
               f"{pct(s['total_return'], 1, sign=True)} · peak {money(eq.max(), cur, 2, compact=True)}",
               transform=ax_eq.transAxes, ha="right", va="top", fontsize=7.8, fontweight="semibold",
               color=theme.cyan, bbox=boxed(theme))
    money_axis(ax_eq, cur)
    headroom(ax_eq, 0.13)  # keeps the two top labels clear of the curve
    ax_eq.set_title("Account value; shading is gain or loss against initial capital")

    style_axes(ax_cum, theme)
    cum = res.cumulative
    ax_cum.axhline(0, color=theme.spine, lw=0.8)
    ax_cum.plot(cum.index, cum["strategy"], color=theme.cyan, lw=1.4, label="strategy")
    ax_cum.plot(cum.index, cum["benchmark"], color=theme.benchmark, lw=1.15, ls=(0, (5, 2)),
                label="equal-weight benchmark (frictionless)")
    ax_cum.plot(cum.index, cum["relative"], color=theme.violet, lw=1.2, ls=(0, (1, 1.3)),
                label="relative = (1 + strategy) / (1 + benchmark) − 1")
    percent_axis(ax_cum)
    headroom(ax_cum, 0.42)
    ax_cum.set_title("Cumulative return and benchmark-relative return")
    legend(ax_cum, theme, ncol=3, fontsize=7.1)

    style_axes(ax_dd, theme)
    dd = res.drawdown_series
    ax_dd.fill_between(dd.index, dd.values, 0, color=theme.negative, alpha=0.32, lw=0)
    ax_dd.plot(dd.index, dd.values, color=theme.negative, lw=0.9)
    ep = res.max_drawdown_episode  # the episode the report text describes
    if ep is not None:
        ax_dd.annotate(f"maximum drawdown {pct(ep['depth'], 1)}", xy=(ep["trough"], ep["depth"]), xytext=(14, 4),
                       textcoords="offset points", fontsize=7.2, color=theme.negative, va="bottom",
                       bbox=boxed(theme))
    percent_axis(ax_dd)
    ax_dd.set_ylim(dd.min() * 1.3, 0.03)
    ax_dd.set_title("Underwater: drawdown from the running peak")

    style_axes(ax_vol, theme)
    shade_regimes(ax_vol, res, theme, label=True)
    ax_vol.plot(res.rolling_vol.index, res.rolling_vol.values, color=theme.violet, lw=1.2,
                label=f"strategy ({cfg.rolling_vol_window}-day)")
    ax_vol.axhline(s["annualized_volatility"], color=theme.faint, lw=0.8, ls=(0, (4, 3)))
    percent_axis(ax_vol)
    ax_vol.set_ylim(0, res.rolling_vol.max() * 1.55)
    ax_vol.set_title(f"Rolling volatility ({cfg.rolling_vol_window}-day, annualized)")
    legend(ax_vol, theme, ncol=2, fontsize=6.6)

    style_axes(ax_sh, theme)
    rs = res.rolling_sharpe
    ax_sh.axhline(0, color=theme.spine, lw=0.8)
    ax_sh.fill_between(rs.index, rs.values, 0, where=rs.values >= 0, interpolate=True, color=theme.positive,
                       alpha=0.26, lw=0)
    ax_sh.fill_between(rs.index, rs.values, 0, where=rs.values < 0, interpolate=True, color=theme.negative,
                       alpha=0.3, lw=0)
    ax_sh.plot(rs.index, rs.values, color=theme.blue, lw=1.1)
    ax_sh.set_title(f"Rolling Sharpe ratio ({cfg.rolling_sharpe_window}-day)")
    for ax in (ax_eq, ax_cum, ax_dd, ax_vol, ax_sh):
        year_axis(ax)
    for ax in (ax_eq, ax_cum):
        plt.setp(ax.get_xticklabels(), visible=False)

    _monthly_heatmap(ax_heat, res, theme)
    _stats_panel(ax_stats, res, theme)
    return fig


def _monthly_heatmap(ax, res, theme: Theme) -> None:
    table = res.monthly
    values = table[list(range(1, 13))].to_numpy(dtype=float)
    year = table["year"].to_numpy(dtype=float)
    limit = np.nanpercentile(np.abs(values), 95)
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    cmap = theme.diverging()
    bare_axes(ax, theme)
    ax.set_facecolor(theme.background)
    n_rows = len(table)
    for i, label in enumerate(table.index):
        y = n_rows - 1 - i
        for j in range(12):
            v = values[i, j]
            ax.add_patch(Rectangle((j, y), 0.94, 0.9, color=cmap(norm(v)) if np.isfinite(v) else theme.panel, lw=0))
            if np.isfinite(v):
                heat_text(ax, j + 0.47, y + 0.45, signed_cell(v), theme, v, cmap, norm, size=6.3)
        yv = np.clip(year[i], -limit, limit)
        ax.add_patch(Rectangle((12.35, y), 1.5, 0.9, color=cmap(norm(yv)), lw=0))
        heat_text(ax, 13.1, y + 0.45, signed_cell(year[i]), theme, yv, cmap, norm, size=6.6, weight="semibold")
        ax.text(-0.25, y + 0.45, str(label), ha="right", va="center", fontsize=7.2, color=theme.muted)
    for j, month in enumerate(MONTHS):
        ax.text(j + 0.47, n_rows + 0.1, month, ha="center", va="bottom", fontsize=6.6, color=theme.muted)
    ax.text(13.1, n_rows + 0.1, "Year", ha="center", va="bottom", fontsize=6.6, color=theme.muted,
            fontweight="semibold")
    ax.set_xlim(-1.4, 14.0)
    ax.set_ylim(-0.1, n_rows + 0.9)
    ax.set_title("Monthly returns (%; blue gain, orange loss)", pad=2)


def _stats_panel(ax, res, theme: Theme) -> None:
    s, d = res.stats, res.decomposition
    bare_axes(ax, theme)
    ax.set_facecolor(theme.background)
    rows = [
        ("Total return", pct(s["total_return"], 1, sign=True)),
        ("CAGR", pct(s["cagr"], 1, sign=True)),
        ("Volatility (ann.)", pct(s["annualized_volatility"], 1)),
        ("Sharpe (rf 0%)", number(s["sharpe"], 2)),
        ("Sortino", number(s["sortino"], 2)),
        ("Max drawdown", pct(s["max_drawdown"], 1)),
        ("Calmar", number(s["calmar"], 2)),
        ("Beta to benchmark", number(s["beta"], 2)),
        ("Information ratio", number(s["information_ratio"], 2)),
        ("Turnover (× equity / yr)", f"{res.annual_turnover:.1f}×"),
        ("Costs paid", money(d.commissions + d.slippage, res.record.settings.currency, 0, compact=True)),
        ("Daily observations", f"{s['observations']:,}"),
    ]
    colors = [theme.text] * len(rows)
    colors[0] = theme.positive if s["total_return"] >= 0 else theme.negative
    colors[5] = theme.negative
    ax.set_title("Statistics (simple daily returns)", pad=2)
    text_rows(ax, rows, theme, top=0.98, step=0.082, size=7.8, value_colors=colors)


# ---------------------------------------------------------------- B. drawdowns

def drawdowns(res, theme: Theme) -> plt.Figure:
    top = res.top_drawdowns
    underwater_share = float((res.drawdown_series < 0).mean())
    subtitle = (f"{len(res.episodes)} drawdown episodes · the account was below a previous peak on "
                f"{pct(underwater_share, 0)} of days · the five deepest are numbered and listed")
    frame = new_frame(theme, 8.0, "Drawdowns and recovery", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.05)
    fig = frame.fig
    gs = fig.add_gridspec(3, 1, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom,
                          height_ratios=[2.2, 1.3, 1.55], hspace=0.42)
    ax_eq, ax_dd, ax_tab = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])
    eq, dd = res.record.equity, res.drawdown_series
    end = eq.index[-1]

    for ax in (ax_eq, ax_dd):
        style_axes(ax, theme)
        for rank, ep in top.iterrows():
            stop = ep["recovery"] if ep["recovered"] else end
            ax.axvspan(ep["peak"], stop, color=theme.negative, alpha=0.11 if ep["recovered"] else 0.06, lw=0,
                       hatch=None if ep["recovered"] else "////")
    ax_eq.plot(eq.index, eq.values, color=theme.cyan, lw=1.4)
    ax_eq.axhline(res.record.settings.initial_capital, color=theme.faint, lw=0.8, ls=(0, (4, 3)))
    for rank, ep in top.iterrows():
        ax_eq.plot([ep["peak"]], [eq.loc[ep["peak"]]], marker="o", ms=3.5, color=theme.text, zorder=4)
        ax_eq.plot([ep["trough"]], [eq.loc[ep["trough"]]], marker="v", ms=5, color=theme.negative, zorder=4)
        ax_eq.annotate(str(rank + 1), xy=(ep["trough"], eq.loc[ep["trough"]]), xytext=(0, -13),
                       textcoords="offset points", ha="center", fontsize=8, fontweight="bold", color=theme.negative)
    money_axis(ax_eq, res.record.settings.currency)
    ax_eq.set_title("Account value: ● peak, ▼ trough; shaded until recovery, hatched if not recovered")
    ax_dd.fill_between(dd.index, dd.values, 0, color=theme.negative, alpha=0.3, lw=0)
    ax_dd.plot(dd.index, dd.values, color=theme.negative, lw=0.9)
    percent_axis(ax_dd)
    ax_dd.set_title("Underwater curve")
    for ax in (ax_eq, ax_dd):
        year_axis(ax)
        ax.set_xlim(eq.index[0], end)

    bare_axes(ax_tab, theme)
    ax_tab.set_facecolor(theme.background)
    headers = ["#", "Peak", "Trough", "Recovered", "Depth", "Peak→trough", "Trough→recovery", "Total"]
    xs = [0.02, 0.09, 0.23, 0.37, 0.53, 0.65, 0.80, 0.97]
    aligns = ["left", "left", "left", "left", "right", "right", "right", "right"]
    for x, h, a in zip(xs, headers, aligns):
        ax_tab.text(x, 0.95, h, transform=ax_tab.transAxes, ha=a, va="top", fontsize=7.6, color=theme.muted,
                    fontweight="semibold")
    ax_tab.add_artist(plt.Line2D([0.01, 0.99], [0.82, 0.82], color=theme.grid, lw=0.8, transform=ax_tab.transAxes))
    for i, ep in top.iterrows():
        y = 0.75 - i * 0.155
        recovery = ep["recovery"].strftime("%Y-%m-%d") if ep["recovered"] else "not recovered"
        cells = [str(i + 1), ep["peak"].strftime("%Y-%m-%d"), ep["trough"].strftime("%Y-%m-%d"), recovery,
                 pct(ep["depth"], 1), f"{ep['peak_to_trough_bars']:.0f} d",
                 f"{ep['recovery_bars']:.0f} d" if ep["recovered"] else "—",
                 f"{ep['duration_bars']:.0f} d" + ("" if ep["recovered"] else " (open)")]
        for j, (x, cell, a) in enumerate(zip(xs, cells, aligns)):
            color = theme.negative if (j == 4 or (j == 3 and not ep["recovered"])) else theme.text
            ax_tab.text(x, y, cell, transform=ax_tab.transAxes, ha=a, va="top", fontsize=7.8, color=color)
    ax_tab.set_title("Largest drawdowns (durations in trading days)", pad=2)
    return fig


# ---------------------------------------------------------------- C. distribution

def distribution(res, theme: Theme) -> plt.Figure:
    from scipy import stats as st

    q = res.return_summary
    r = res.returns.to_numpy()
    first, last = res.returns.index[0].date(), res.returns.index[-1].date()
    subtitle = (f"{q['observations']:,} daily net returns, {first} → {last} · solid lines are empirical "
                "(read from the sample); dashed and dotted lines come from fitted models")
    frame = new_frame(theme, 6.6, "Return distribution and tails", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.05)
    fig = frame.fig
    gs = fig.add_gridspec(2, 12, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom,
                          height_ratios=[3.0, 1.0], hspace=0.42, wspace=1.4)
    ax_h, ax_q, ax_t = fig.add_subplot(gs[0, :7]), fig.add_subplot(gs[0, 7:]), fig.add_subplot(gs[1, :])

    style_axes(ax_h, theme)
    bins = np.linspace(np.quantile(r, 0.001), np.quantile(r, 0.999), 70)
    ax_h.hist(r, bins=bins, density=True, color=theme.blue, alpha=0.45, edgecolor=theme.panel, linewidth=0.3)
    grid = np.linspace(bins[0], bins[-1], 400)
    ax_h.plot(grid, st.norm.pdf(grid, q["mean"], q["std"]), color=theme.text, lw=1.0, ls=(0, (4, 2.5)),
              label="normal fit (model)")
    ax_h.plot(grid, st.t.pdf(grid, q["t_dof"], q["t_loc"], q["t_scale"]), color=theme.violet, lw=1.25,
              ls=(0, (1, 1.2)), label=f"Student-t fit, ν = {q['t_dof']:.1f} (model)")
    ax_h.axvline(-q["var95_empirical"], color=theme.negative, lw=1.3, label="95% VaR, empirical")
    ax_h.axvline(-q["es95_empirical"], color=theme.negative, lw=1.2, ls=(0, (2, 1.5)), label="95% ES, empirical")
    ax_h.axvline(-q["var95_normal"], color=theme.faint, lw=1.0, ls=(0, (4, 2.5)), label="95% VaR, normal model")
    percent_axis(ax_h, "x", 1)
    ax_h.set_yticks([])
    ax_h.set_xlabel("daily return")
    ax_h.set_title("Histogram of daily returns (density)")
    legend(ax_h, theme, loc="upper right", ncol=1, fontsize=6.9)
    ax_h.text(0.015, 0.97,
              f"n = {q['observations']:,} daily returns (Mon–Fri)\nmean {pct(q['mean'], 3, sign=True)}, "
              f"sd {pct(q['std'], 2)}\nskew {number(q['skewness'], 2, sign=True)}, "
              f"excess kurtosis {number(q['excess_kurtosis'], 1)}\n"
              f"|z| > 3 on {q['tail_days_beyond_3sd']} days\n({q['expected_beyond_3sd_normal']:.1f} expected "
              "if normal)", transform=ax_h.transAxes, ha="left", va="top", fontsize=7.0, color=theme.muted,
              linespacing=1.45, bbox=boxed(theme, 0.92))

    style_axes(ax_q, theme, grid="both")
    theoretical, sample = res.qq
    tail = np.abs(theoretical) > 2
    lim = max(np.abs(sample).max(), np.abs(theoretical).max()) * 1.05
    ax_q.plot([-lim, lim], [-lim, lim], color=theme.faint, lw=0.9, ls=(0, (4, 2.5)), label="normal reference")
    ax_q.scatter(theoretical[~tail], sample[~tail], s=5, color=theme.blue, alpha=0.6, lw=0, label="sample")
    ax_q.scatter(theoretical[tail], sample[tail], s=7, color=theme.negative, alpha=0.9, lw=0,
                 label="beyond ±2 normal quantiles")
    ax_q.set_xlim(-4, 4)
    ax_q.set_ylim(-lim, lim)
    ax_q.set_xlabel("normal quantile")
    ax_q.set_ylabel("standardized sample quantile")
    ax_q.set_title("Q–Q plot against the normal")
    legend(ax_q, theme, loc="upper left", ncol=1, fontsize=6.9)

    bare_axes(ax_t, theme)
    ax_t.set_facecolor(theme.background)
    ax_t.set_title("One-day loss estimates (% of equity)", pad=2)
    headers = ["", "95% VaR", "95% ES", "99% VaR", "99% ES"]
    xs = [0.02, 0.42, 0.58, 0.74, 0.90]
    rows = [("Empirical (historical simulation)", q["var95_empirical"], q["es95_empirical"], q["var99_empirical"],
             q["es99_empirical"]),
            ("Normal model (fitted mean and sd)", q["var95_normal"], q["es95_normal"], q["var99_normal"],
             q["es99_normal"]),
            ("Student-t model (maximum likelihood)", q["var95_student_t"], np.nan, q["var99_student_t"], np.nan)]
    for x, h in zip(xs, headers):
        ax_t.text(x, 0.92, h, transform=ax_t.transAxes, ha="left" if x < 0.1 else "right", va="top",
                  fontsize=7.6, color=theme.muted, fontweight="semibold")
    for i, row in enumerate(rows):
        y = 0.66 - i * 0.26
        ax_t.text(xs[0], y, row[0], transform=ax_t.transAxes, ha="left", va="top", fontsize=7.7,
                  color=theme.text if i == 0 else theme.muted)
        for x, value in zip(xs[1:], row[1:]):
            ax_t.text(x, y, pct(value, 2) if np.isfinite(value) else "—", transform=ax_t.transAxes,
                      ha="right", va="top", fontsize=7.7, color=theme.negative if i == 0 else theme.text)
    return fig


# ---------------------------------------------------------------- D. exposure

def exposure(res, theme: Theme) -> plt.Figure:
    exp = res.exposures
    subtitle = (f"Average gross exposure {pct(exp['gross'].mean(), 0)} and net exposure "
                f"{pct(exp['net'].mean(), 0, sign=True)} of equity · hatching marks instruments that are not "
                "listed yet or lack the history the signal needs; amber labels lack sector metadata")
    frame = new_frame(theme, 9.6, "Exposure and diversification", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.32)
    fig = frame.fig
    gs = fig.add_gridspec(3, 12, left=0.125, right=0.93, top=frame.top, bottom=frame.bottom,
                          height_ratios=[1.55, 2.0, 2.45], hspace=0.42, wspace=1.6)
    ax_exp, ax_w = fig.add_subplot(gs[0, :]), fig.add_subplot(gs[1, :])
    ax_c, ax_n = fig.add_subplot(gs[2, :6]), fig.add_subplot(gs[2, 7:])

    style_axes(ax_exp, theme)
    ax_exp.fill_between(exp.index, exp["long"], 0, color=theme.positive, alpha=0.38, lw=0, label="long")
    ax_exp.fill_between(exp.index, exp["short"], 0, color=theme.negative, alpha=0.4, lw=0, label="short")
    ax_exp.plot(exp.index, exp["net"], color=theme.text, lw=0.95, label="net")
    ax_exp.plot(exp.index, exp["gross"], color=theme.violet, lw=0.9, ls=(0, (3, 2)), label="gross")
    ax_exp.axhline(0, color=theme.spine, lw=0.8)
    percent_axis(ax_exp)
    year_axis(ax_exp)
    ax_exp.set_xlim(exp.index[0], exp.index[-1])
    ax_exp.set_title("Exposure (% of equity, positions at daily marks)")
    legend(ax_exp, theme, loc="lower right", ncol=4, fontsize=6.9, bbox_to_anchor=(1.0, 1.0), borderaxespad=0.1)

    weekly, status = res.weekly_weights, res.weight_status
    symbols = res.symbol_order
    values = weekly[symbols].to_numpy(dtype=float).T
    limit = max(np.nanmax(np.abs(values)), 1e-6)
    cmap, norm = theme.diverging(), TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
    style_axes(ax_w, theme, grid=None)
    x = mdates.date2num(weekly.index.to_pydatetime())
    width = np.median(np.diff(x))
    edges = np.concatenate([x - width / 2, [x[-1] + width / 2]])
    mesh = ax_w.pcolormesh(edges, np.arange(len(symbols) + 1), np.ma.masked_invalid(
        np.where(status[symbols].to_numpy().T == 2, values, np.nan)), cmap=cmap, norm=norm, shading="flat")
    span = edges[-1] - edges[0]
    for row, symbol in enumerate(symbols):
        codes = status[symbol].to_numpy()
        for code, hatch, label in [(0, "xxxx", "not listed"), (1, "....", "warm-up")]:
            idx = np.flatnonzero(codes == code)
            if not len(idx):
                continue
            start, stop = edges[idx[0]], edges[idx[-1] + 1]
            ax_w.add_patch(Rectangle((start, row), stop - start, 1, facecolor=theme.panel, edgecolor=theme.faint,
                                     hatch=hatch, lw=0))
            if (stop - start) / span > 0.1:
                ax_w.text((start + stop) / 2, row + 0.5, label, ha="center", va="center", fontsize=6.6,
                          color=theme.muted, bbox=dict(boxstyle="round,pad=0.15", fc=theme.panel, ec="none"))
    ax_w.set_yticks(np.arange(len(symbols)) + 0.5)
    ax_w.set_yticklabels([res.symbol_labels[s] for s in symbols], fontsize=7.0)
    for tick, symbol in zip(ax_w.get_yticklabels(), symbols):
        if res.dataset.sector_of(symbol) is None:
            tick.set_color(theme.amber)
    ax_w.invert_yaxis()
    ax_w.xaxis_date()
    year_axis(ax_w)
    ax_w.set_title("Position weights by instrument (weekly)")
    legend(ax_w, theme, handles=[Patch(facecolor=theme.panel, edgecolor=theme.faint, hatch="xxxx", label="not listed"),
                                 Patch(facecolor=theme.panel, edgecolor=theme.faint, hatch="....",
                                       label=f"warm-up (< {res.required_history} bars)")],
           loc="lower right", ncol=2, fontsize=6.9, bbox_to_anchor=(1.0, 1.0), borderaxespad=0.1)
    cbar = fig.colorbar(mesh, ax=ax_w, pad=0.01, fraction=0.025, aspect=12)
    cbar.ax.tick_params(labelsize=6.6, colors=theme.spine, labelcolor=theme.muted)
    cbar.outline.set_visible(False)
    cbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: pct(v, 0)))

    corr, overlap = res.correlations.loc[symbols, symbols], res.overlap.loc[symbols, symbols]
    bare_axes(ax_c, theme)
    ax_c.set_facecolor(theme.background)
    cnorm = TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1)
    full = int(overlap.to_numpy().max())
    n_sym = len(symbols)
    for i, a in enumerate(symbols):
        for j, b in enumerate(symbols):
            if j >= i:
                continue
            v = corr.loc[a, b]
            y = n_sym - 1 - i
            ax_c.add_patch(Rectangle((j, y), 0.95, 0.92, color=cmap(cnorm(v)) if np.isfinite(v) else theme.panel, lw=0))
            n = int(overlap.loc[a, b])
            short = n < full * 0.9
            text = f"{v:.2f}".replace("-", MINUS) if np.isfinite(v) else "n/a"
            heat_text(ax_c, j + 0.47, y + (0.58 if short else 0.46), text, theme, v if np.isfinite(v) else np.nan,
                      cmap, cnorm, size=6.5)
            if short:
                heat_text(ax_c, j + 0.47, y + 0.24, f"n={n}", theme, v, cmap, cnorm, size=5.4)
    for i, symbol in enumerate(symbols[1:], start=1):
        ax_c.text(-0.1, n_sym - 1 - i + 0.46, symbol, ha="right", va="center", fontsize=6.8,
                  color=theme.amber if res.dataset.sector_of(symbol) is None else theme.muted)
    for j, symbol in enumerate(symbols[:-1]):
        ax_c.text(j + 0.47, n_sym - 0.88, symbol, ha="left", va="bottom", fontsize=6.6, rotation=40,
                  color=theme.amber if res.dataset.sector_of(symbol) is None else theme.muted)
    ax_c.set_xlim(-1.3, n_sym - 0.8)
    ax_c.set_ylim(-0.1, n_sym + 0.6)
    ax_c.set_title(f"Return correlations (n shown if < {full:,})", pad=2)

    style_axes(ax_n, theme)
    conc = res.concentration
    ax_n.plot(conc.index, conc["effective_positions"], color=theme.cyan, lw=1.1, label="effective positions")
    ax_n.axhline(n_sym, color=theme.faint, lw=0.8, ls=(0, (4, 3)))
    ax_n.text(conc.index[-1], n_sym, f"{n_sym} instruments", va="bottom", ha="right", fontsize=6.8, color=theme.faint)
    ax_n.set_ylim(0, n_sym + 1.5)
    ax_n2 = twin_axis(ax_n, theme, theme.amber)
    ax_n2.plot(conc.index, conc["max_abs_weight"], color=theme.amber, lw=0.9, ls=(0, (2, 1.5)),
               label="largest |weight| (right)")
    ax_n2.set_ylim(0, max(0.5, conc["max_abs_weight"].max() * 1.15))
    percent_axis(ax_n2)
    year_axis(ax_n)
    ax_n.set_title("Breadth: (Σ|w|)² / Σw²")
    handles = ax_n.get_legend_handles_labels()[0] + ax_n2.get_legend_handles_labels()[0]
    legend(ax_n, theme, handles=handles, loc="lower right", ncol=1, fontsize=6.8)
    return fig


# ---------------------------------------------------------------- E. attribution

def attribution(res, theme: Theme) -> plt.Figure:
    d = res.decomposition
    cur = res.record.settings.currency
    subtitle = (f"Net P&L {money(d.net, cur, 0, sign=True)} equals final equity − initial capital (residual "
                f"{money(d.residual, cur, 2)}) · slippage is already inside fill prices: it is shown as a "
                "component, never deducted twice")
    frame = new_frame(theme, 6.2, "P&L and cost attribution", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.5)
    fig = frame.fig
    gs = fig.add_gridspec(1, 12, left=0.09, right=frame.right, top=frame.top, bottom=frame.bottom, wspace=0.6)
    ax_w, ax_i = fig.add_subplot(gs[0, :5]), fig.add_subplot(gs[0, 7:])

    style_axes(ax_w, theme)
    steps = [("Frictionless\nP&L", d.frictionless, "total"), ("Slippage\n(in fills)", -d.slippage, "delta"),
             ("Commis-\nsions", -d.commissions, "delta"), ("Financing\n& borrow", 0.0, "unmodeled"),
             ("Net\nP&L", d.net, "total")]
    scale = abs(d.frictionless)
    running = 0.0
    for i, (label, value, kind) in enumerate(steps):
        if kind == "total":
            running = value
            ax_w.bar(i, value, width=0.7, color=theme.positive if value >= 0 else theme.negative, alpha=0.9, lw=0)
            ax_w.text(i, max(value, 0) + scale * 0.02, money(value, cur, 0, sign=True, compact=True), ha="center",
                      va="bottom", fontsize=7.8, fontweight="semibold", color=theme.text)
        elif kind == "delta":
            bottom, height = running + value, -value
            ax_w.bar(i, height, bottom=bottom, width=0.7, color=theme.negative, alpha=0.8, lw=0)
            ax_w.text(i, bottom + height / 2, money(value, "", 0, compact=True), ha="center", va="center",
                      fontsize=7.4, fontweight="semibold", color=theme.readable_on(theme.negative))
            running += value
        else:
            ax_w.add_patch(Rectangle((i - 0.35, running - scale * 0.012), 0.7, scale * 0.024, facecolor=theme.panel,
                                     edgecolor=theme.faint, hatch="////", lw=0.6))
            ax_w.text(i, running + scale * 0.03, "not\nmodeled", ha="center", va="bottom", fontsize=7.0,
                      color=theme.muted, linespacing=1.1)
        if i < len(steps) - 1:
            ax_w.plot([i + 0.35, i + 0.65], [running, running], color=theme.faint, lw=0.8, ls=(0, (2, 2)))
    ax_w.set_xticks(range(len(steps)))
    ax_w.set_xticklabels([s[0] for s in steps], fontsize=7.2)
    ax_w.axhline(0, color=theme.spine, lw=0.8)
    money_axis(ax_w, cur)
    ax_w.set_ylim(min(0, d.net) * 1.1, max(d.frictionless, d.net, 0) * 1.16)
    ax_w.set_title("Frictionless to net P&L")

    style_axes(ax_i, theme, grid="x")
    by = d.by_symbol.sort_values("net")
    y = np.arange(len(by))
    ax_i.barh(y, by["frictionless"], height=0.62, color="none", edgecolor=theme.faint, lw=0.9, label="frictionless")
    ax_i.barh(y, by["net"], height=0.4, color=[theme.positive if v >= 0 else theme.negative for v in by["net"]],
              lw=0, label="net of costs")
    reach = abs(by[["net", "frictionless"]]).to_numpy().max()
    for yi, (symbol, row) in zip(y, by.iterrows()):
        edge = max(row["net"], row["frictionless"], 0) if row["net"] >= 0 else min(row["net"], row["frictionless"], 0)
        ax_i.text(edge + (1 if row["net"] >= 0 else -1) * reach * 0.04, yi,
                  money(row["net"], "", 0, sign=True, compact=True), va="center",
                  ha="left" if row["net"] >= 0 else "right", fontsize=7.0, color=theme.text)
    ax_i.axvline(0, color=theme.spine, lw=0.8)
    ax_i.set_yticks(y)
    ax_i.set_yticklabels(list(by.index), fontsize=7.2)
    for tick, symbol in zip(ax_i.get_yticklabels(), by.index):
        if res.dataset.sector_of(symbol) is None:
            tick.set_color(theme.amber)
    ax_i.set_xlim(-reach * 1.45, reach * 1.45)
    money_axis(ax_i, "", axis="x")
    ax_i.set_xlabel(f"{cur}; amber label = no sector metadata")
    ax_i.set_title("Contribution by instrument")
    legend(ax_i, theme, loc="lower right", ncol=1, fontsize=6.9)
    return fig


# ---------------------------------------------------------------- F. trades and execution

def trades(res, theme: Theme) -> plt.Figure:
    ts, cur = res.trade_stats, res.record.settings.currency
    orders = res.record.orders
    subtitle = (f"{len(orders):,} orders → {len(res.record.executions):,} fills → {ts['closed_trades']:,} closed "
                f"FIFO lots (+{len(res.open_lots)} open at the end) · win rate {pct(ts['win_rate'], 0)}, "
                f"profit factor {ts['profit_factor']:.2f}")
    frame = new_frame(theme, 9.6, "Trades and execution", subtitle, provenance(res), tag=evidence_tag(res),
                      axis_space=0.3)
    fig = frame.fig
    gs = fig.add_gridspec(3, 12, left=frame.left, right=0.925, top=frame.top, bottom=frame.bottom,
                          height_ratios=[2.1, 2.0, 1.75], hspace=0.55, wspace=2.2)
    ax_p = fig.add_subplot(gs[0, :])
    ax_s, ax_h = fig.add_subplot(gs[1, :7]), fig.add_subplot(gs[1, 7:])
    ax_t, ax_f = fig.add_subplot(gs[2, :7]), fig.add_subplot(gs[2, 7:])

    sym, closes, fills = res.focus_symbol, res.focus_closes, res.focus_fills
    style_axes(ax_p, theme)
    ax_p.plot(closes.index, closes.values, color=theme.muted, lw=1.0, label=f"{sym} close")
    buys, sells = fills[fills["side"] == "buy"], fills[fills["side"] == "sell"]
    ax_p.scatter(buys["filled_at"], buys["fill_price"], marker="^", s=15, color=theme.positive, lw=0, zorder=3,
                 label="buy fill")
    ax_p.scatter(sells["filled_at"], sells["fill_price"], marker="v", s=15, color=theme.negative, lw=0, zorder=3,
                 label="sell fill")
    ax_p.set_ylabel(f"price ({cur})")
    headroom(ax_p, 0.3)
    ax_p2 = twin_axis(ax_p, theme, theme.violet)
    position = res.focus_position
    ax_p2.fill_between(position.index, position.values, 0, step="post", color=theme.violet, alpha=0.15, lw=0)
    ax_p2.plot(position.index, position.values, drawstyle="steps-post", color=theme.violet, lw=0.7, alpha=0.85,
               label="position (shares, right axis)")
    ax_p2.axhline(0, color=theme.violet, lw=0.5, alpha=0.5)
    lim = np.abs(position).max() * 2.8
    ax_p2.set_ylim(-lim, lim)
    ax_p2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: short_money(v)))
    year_axis(ax_p)
    ax_p.set_xlim(closes.index[0], closes.index[-1])
    sector = res.dataset.sector_of(sym) or "no sector metadata"
    ax_p.set_title(f"{sym} ({sector}, largest |net P&L|): fills on the price path and the resulting position")
    handles = ax_p.get_legend_handles_labels()[0] + ax_p2.get_legend_handles_labels()[0]
    legend(ax_p, theme, handles=handles, ncol=4, fontsize=6.9)

    closed = res.closed_trades
    style_axes(ax_s, theme, grid="both")
    notional = closed["quantity"] * closed["entry_price"]
    for direction, color in (("long", theme.cyan), ("short", theme.violet)):
        part = closed[closed["direction"] == direction]
        size = 4 + 30 * (part["quantity"] * part["entry_price"]) / notional.max()
        ax_s.scatter(part["holding_bars"], part["return"], s=size, color=color, alpha=0.5, lw=0,
                     label=f"{direction} lots ({len(part):,})")
    ax_s.axhline(0, color=theme.spine, lw=0.8)
    ax_s.set_xscale("log")
    ax_s.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax_s.set_xlabel("holding period (trading days, log scale)")
    percent_axis(ax_s, digits=0)
    headroom(ax_s, 0.22)
    ax_s.set_title("Closed lots: holding period vs net return (size = notional)")
    legend(ax_s, theme, ncol=2, fontsize=6.9)

    style_axes(ax_h, theme)
    returns = closed["return"]
    upper = max(1.0, float(np.ceil(returns.quantile(0.995) * 4) / 4))
    bins = np.linspace(-0.5, upper, 49)
    counts, edges = np.histogram(returns.clip(-0.5, upper), bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    ax_h.bar(centers, counts, width=np.diff(edges) * 0.92,
             color=[theme.positive if c >= 0 else theme.negative for c in centers], alpha=0.85, lw=0)
    ax_h.axvline(0, color=theme.spine, lw=0.8)
    percent_axis(ax_h, "x", 0)
    beyond = int((returns > upper).sum()) + int((returns < -0.5).sum())
    note = (f"median hold {ts['median_holding_bars']:.0f} d\navg win {money(ts['average_win'], cur, 1, compact=True)}"
            f"\navg loss {money(ts['average_loss'], cur, 1, compact=True)}")
    if beyond:
        note += f"\n{beyond} lots beyond the axis\n(counted in the end bins)"
    ax_h.text(0.98, 0.95, note, transform=ax_h.transAxes, ha="right", va="top", fontsize=6.9, color=theme.muted,
              linespacing=1.4, bbox=boxed(theme))
    ax_h.set_title("Closed-lot net returns")

    style_axes(ax_t, theme)
    t = res.turnover
    x = t.index.to_timestamp()
    ax_t.bar(x, t["turnover"], width=20, color=theme.blue, alpha=0.6, lw=0, label="turnover (× equity)")
    ax_t.set_ylabel("× equity per month")
    headroom(ax_t, 0.32)
    ax_t2 = twin_axis(ax_t, theme, theme.amber)
    ax_t2.plot(x, t["cost_bps_of_equity"], color=theme.amber, lw=1.1, marker="o", ms=1.8,
               label="costs (bps of equity, right)")
    ax_t2.set_ylim(0, t["cost_bps_of_equity"].max() * 1.32)
    year_axis(ax_t)
    ax_t.set_title("Monthly turnover and transaction costs")
    handles = ax_t.get_legend_handles_labels()[0] + ax_t2.get_legend_handles_labels()[0]
    legend(ax_t, theme, handles=handles, ncol=2, fontsize=6.8)

    bare_axes(ax_f, theme)
    ax_f.set_facecolor(theme.background)
    ex = res.record.executions
    slip_bps = ex["slippage_cost"] / (ex["quantity"] * ex["reference_price"]) * 1e4
    delays = res.fill_delays.value_counts().sort_index()
    rejected = orders[~orders["accepted"]]
    delay_text = ("next trading day for all" if len(delays) == 1 and delays.index[0] == 1
                  else ", ".join(f"{k} d: {v:,}" for k, v in delays.items()))
    rows = [
        ("Orders decided", f"{len(orders):,}"),
        ("Rejected before submission", f"{len(rejected):,}"),
        ("Fills", f"{len(ex):,}"),
        ("Decision → fill", delay_text),
        ("Slippage vs reference close", f"{slip_bps.mean():.1f} bps (model)"),
        ("Commission", f"{res.record.settings.commission * 1e4:.0f} bps of notional"),
        ("Closed / open FIFO lots", f"{ts['closed_trades']:,} / {len(res.open_lots)}"),
        ("Annual turnover", f"{res.annual_turnover:.1f}× equity"),
    ]
    ax_f.set_title("Order, fill and lot accounting", pad=2)
    text_rows(ax_f, rows, theme, top=0.97, step=0.122, size=7.2)
    return fig


# ---------------------------------------------------------------- G. walk-forward

def walk_forward(res, theme: Theme) -> plt.Figure:
    wf, table, oos = res.walk_forward, res.wf_table, res.oos_stats
    subtitle = (f"{len(wf.windows)} windows · {wf.train_bars}-bar training and {wf.test_bars}-bar evaluation "
                f"periods · {wf.trials_per_window} parameter sets tried per window, best in-sample Sharpe selected "
                f"· stitched out-of-sample return {pct(oos['total_return'], 1, sign=True)}")
    footer = provenance(res, run_line=(
        f"Runs: {wf.trials_per_window * len(wf.windows)} isolated training runs + {len(wf.windows)} evaluation runs "
        f"· strategy {res.record.strategy_version} · selection reads training bars only · {REGENERATE}"))
    frame = new_frame(theme, 8.4, "Walk-forward validation", subtitle, footer, tag=evidence_tag(res), axis_space=0.48)
    fig = frame.fig
    gs = fig.add_gridspec(3, 1, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom,
                          height_ratios=[1.55, 2.05, 1.75], hspace=0.45)
    ax_t, ax_e, ax_b = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])

    style_axes(ax_t, theme, grid="x")
    for i, row in table.iterrows():
        y = len(table) - 1 - i
        ax_t.barh(y, mdates.date2num(row["train_end"]) - mdates.date2num(row["train_start"]),
                  left=mdates.date2num(row["train_start"]), height=0.55, color=theme.blue, alpha=0.3, lw=0)
        ax_t.barh(y, mdates.date2num(row["test_end"]) - mdates.date2num(row["test_start"]),
                  left=mdates.date2num(row["test_start"]), height=0.55, color=theme.cyan, alpha=0.9, lw=0)
        ax_t.text(mdates.date2num(row["test_end"]) + 12, y, row["selected"], va="center", fontsize=7.0,
                  color=theme.text)
    ax_t.set_yticks(range(len(table)))
    ax_t.set_yticklabels([f"W{n}" for n in reversed(table["window"])], fontsize=7.2)
    ax_t.xaxis_date()
    year_axis(ax_t)
    ax_t.set_xlim(mdates.date2num(res.record.equity.index[0]), mdates.date2num(res.record.equity.index[-1]) + 120)
    ax_t.set_title("Training windows (light) select the parameters; evaluation windows (bright) use them unchanged")

    style_axes(ax_e, theme)
    stitched = res.oos_equity
    ax_e.plot(stitched.index, stitched.values, color=theme.cyan, lw=1.4,
              label="out-of-sample, stitched (selected parameters)")
    ref = res.wf_reference
    ax_e.plot(ref.index, ref.values, color=theme.benchmark, lw=1.1, ls=(0, (5, 2)),
              label=f"pre-registered {res.config.params.label()}, same dates (continuous run)")
    ax_e.axhline(res.record.settings.initial_capital, color=theme.faint, lw=0.8, ls=(0, (4, 3)))
    for _, row in table.iterrows():
        ax_e.axvline(row["test_start"], color=theme.grid, lw=0.9)
    money_axis(ax_e, res.record.settings.currency)
    year_axis(ax_e)
    ax_e.set_xlim(stitched.index[0], stitched.index[-1])
    headroom(ax_e, 0.25)
    ax_e.set_title("Out-of-sample equity (each window restarts flat with the initial capital)")
    legend(ax_e, theme, ncol=2, fontsize=6.9)

    style_axes(ax_b, theme)
    x = np.arange(len(table))
    ax_b.bar(x - 0.19, table["train_sharpe"], width=0.36, color=theme.blue, alpha=0.38, lw=0,
             label="in-sample Sharpe (selection window)")
    ax_b.bar(x + 0.19, table["test_sharpe"], width=0.36,
             color=[theme.positive if v >= 0 else theme.negative for v in table["test_sharpe"]], lw=0,
             label="out-of-sample Sharpe (evaluation window)")
    for xi, v in zip(x, table["test_sharpe"]):
        ax_b.text(xi + 0.19, v + (0.08 if v >= 0 else -0.08), number(v, 2, sign=True), ha="center",
                  va="bottom" if v >= 0 else "top", fontsize=6.8, color=theme.text)
    ax_b.axhline(0, color=theme.spine, lw=0.8)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels([f"W{n}\n{r.strftime('%b %Y')}" for n, r in zip(table["window"], table["test_start"])],
                         fontsize=7.0)
    ax_b.set_ylim(min(table["test_sharpe"].min(), 0) - 0.6, max(table["train_sharpe"].max(), 0) + 0.9)
    ax_b.set_title(f"Selection vs evaluation: mean in-sample Sharpe {table['train_sharpe'].mean():.2f}, "
                   f"mean out-of-sample {number(table['test_sharpe'].mean(), 2, sign=True)}")
    legend(ax_b, theme, loc="upper right", ncol=2, fontsize=6.8)
    return fig


# ---------------------------------------------------------------- H. robustness

def robustness(res, theme: Theme) -> plt.Figure:
    sweep = res.sweep
    sharpe, cost, status = res.sweep_sharpe, res.sweep_cost, res.sweep_status
    failed = int((sweep["status"] != "ok").sum())
    best = sweep.loc[sweep["sharpe"].idxmax()]
    pre = res.config.params
    subtitle = (f"{len(sweep)} isolated full-sample runs (fresh engine and strategy each), {failed} failed or without "
                f"trades · outlined: pre-registered {pre.label()} · ★ best in-sample {best['label']}, "
                "which is a selection, not evidence")
    footer = provenance(res, run_line=(
        f"Runs: {len(sweep)} isolated full-sample backtests over lookback × rebalance; other parameters as "
        f"pre-registered · strategy {res.record.strategy_version} · {REGENERATE}"))
    frame = new_frame(theme, 5.9, "Parameter robustness", subtitle, footer, tag=evidence_tag(res), axis_space=0.05)
    fig = frame.fig
    gs = fig.add_gridspec(1, 2, left=frame.left, right=0.965, top=frame.top, bottom=frame.bottom, wspace=0.32)
    limit = np.nanmax(np.abs(sharpe.to_numpy(dtype=float)))
    cost_cmap = LinearSegmentedColormap.from_list("cost", [theme.panel, theme.negative])
    panels = [(fig.add_subplot(gs[0]), sharpe, "Sharpe ratio (net of costs)", lambda v: number(v, 2, sign=True),
               theme.diverging(), TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)),
              (fig.add_subplot(gs[1]), cost, "Transaction costs (% of capital per year)", lambda v: pct(v, 1),
               cost_cmap, Normalize(vmin=0, vmax=np.nanmax(cost.to_numpy(dtype=float))))]
    for ax, table, title, fmt, cmap, norm in panels:
        values = table.to_numpy(dtype=float)
        bare_axes(ax, theme)
        ax.set_facecolor(theme.background)
        rows, cols = table.shape
        for i in range(rows):
            for j in range(cols):
                v = values[i, j]
                ok = status.iloc[i, j] == "ok"
                ax.add_patch(Rectangle((j, rows - 1 - i), 0.96, 0.94,
                                       facecolor=cmap(norm(v)) if (ok and np.isfinite(v)) else theme.panel,
                                       edgecolor=theme.faint if not ok else "none", hatch=None if ok else "xxx", lw=0))
                heat_text(ax, j + 0.48, rows - 1 - i + 0.47, fmt(v) if ok else status.iloc[i, j], theme,
                          v if ok else np.nan, cmap, norm, size=7.4)
                lookback, rebalance = table.index[i], table.columns[j]
                if lookback == pre.lookback and rebalance == pre.rebalance_every:
                    ax.add_patch(Rectangle((j - 0.02, rows - 1 - i - 0.02), 1.0, 0.98, fill=False,
                                           edgecolor=theme.text, lw=1.6))
                if lookback == best["lookback"] and rebalance == best["rebalance_every"]:
                    ax.text(j + 0.9, rows - 1 - i + 0.82, "★", ha="right", va="center", fontsize=8.5,
                            color=theme.amber)
        for i, lookback in enumerate(table.index):
            ax.text(-0.08, rows - 1 - i + 0.47, f"{lookback}", ha="right", va="center", fontsize=7.6, color=theme.muted)
        for j, rebalance in enumerate(table.columns):
            ax.text(j + 0.48, -0.12, f"{rebalance}", ha="center", va="top", fontsize=7.6, color=theme.muted)
        ax.text(-0.75, rows / 2, "lookback (bars)", rotation=90, ha="center", va="center", fontsize=7.6,
                color=theme.muted)
        ax.text(cols / 2, -0.62, "rebalance every N bars", ha="center", va="top", fontsize=7.6, color=theme.muted)
        ax.set_xlim(-0.95, cols)
        ax.set_ylim(-0.95, rows + 0.05)
        ax.set_title(title, pad=4)
    return fig


# ---------------------------------------------------------------- I. uncertainty

def uncertainty(res, theme: Theme) -> plt.Figure:
    cfg, boot, q = res.config, res.bootstrap, res.bootstrap_quantiles
    subtitle = (f"Conditional estimates from a stationary block bootstrap of the {len(res.returns):,} observed daily "
                f"returns (mean block {cfg.bootstrap_mean_block} days, {cfg.bootstrap_samples:,} one-year paths, seed "
                f"{cfg.bootstrap_seed}); they inherit this history's length and luck and are not forecasts")
    frame = new_frame(theme, 5.9, "Scenario and uncertainty analysis", subtitle, provenance(res),
                      tag=evidence_tag(res), axis_space=0.52)
    fig = frame.fig
    gs = fig.add_gridspec(1, 3, left=0.06, right=frame.right, top=frame.top, bottom=frame.bottom, wspace=0.32)
    ax_r, ax_d, ax_g = (fig.add_subplot(gs[i]) for i in range(3))

    for ax, column, title, color in [(ax_r, "total_return", "One-year return", theme.blue),
                                     (ax_d, "max_drawdown", "One-year maximum drawdown", theme.negative)]:
        style_axes(ax, theme)
        values = boot[column]
        counts, _, _ = ax.hist(values, bins=60, color=color, alpha=0.55, lw=0)
        ax.set_ylim(0, counts.max() * 1.32)
        for p, style in ((0.05, (0, (2, 1.5))), (0.5, "-"), (0.95, (0, (2, 1.5)))):
            v = values.quantile(p)
            ax.axvline(v, color=theme.text, lw=0.9, ls=style)
            ax.text(v, counts.max() * (1.29 if p != 0.5 else 1.15),
                    f"p{int(p * 100)}\n{pct(v, 0, sign=column == 'total_return')}", ha="center", va="top",
                    fontsize=6.6, color=theme.text, bbox=boxed(theme))
        percent_axis(ax, "x", 0)
        ax.set_yticks([])
        ax.set_title(title)
    ax_r.axvspan(boot["total_return"].min(), 0, color=theme.negative, alpha=0.08, lw=0)
    ax_r.text(0.03, 0.5, f"P(loss) = {pct(q['p_loss'], 0)}", transform=ax_r.transAxes, fontsize=7.6,
              color=theme.negative, fontweight="semibold", bbox=boxed(theme))
    ax_d.text(0.03, 0.5, f"P(drawdown worse\nthan −20%) = {pct(q['p_dd_20'], 0)}", transform=ax_d.transAxes,
              fontsize=7.2, color=theme.negative, linespacing=1.3, bbox=boxed(theme))

    style_axes(ax_g, theme)
    reg, bench = res.regimes, res.benchmark_regimes
    if reg is None:
        bare_axes(ax_g, theme)
        ax_g.text(0.5, 0.5, "No regime labels in this dataset", ha="center", va="center", fontsize=8,
                  color=theme.muted, transform=ax_g.transAxes)
        return fig
    labels = list(reg.index)
    x = np.arange(len(labels))
    for offset, frame_, name, color in ((-0.19, reg, "strategy", theme.cyan), (0.19, bench, "benchmark", theme.benchmark)):
        values = frame_.loc[labels, "annualized_return"]
        ax_g.bar(x + offset, values, width=0.36, color=color, alpha=0.85 if name == "strategy" else 0.5, lw=0, label=name)
        for xi, (v, sh) in enumerate(zip(values, frame_.loc[labels, "sharpe"])):
            ax_g.text(xi + offset, v + (0.004 if v >= 0 else -0.004),
                      f"{pct(v, 0, sign=True)}\nSR {number(sh, 2)}", ha="center",
                      va="bottom" if v >= 0 else "top", fontsize=6.4, color=theme.text, linespacing=1.2)
    ax_g.axhline(0, color=theme.spine, lw=0.8)
    ax_g.set_xticks(x)
    ax_g.set_xticklabels([f"{lab}\n{int(reg.loc[lab, 'days'])} days" for lab in labels], fontsize=7.2)
    percent_axis(ax_g)
    span = max(abs(reg["annualized_return"]).max(), abs(bench["annualized_return"]).max()) * 1.7
    ax_g.set_ylim(-span, span)
    ax_g.set_title("By volatility regime (DGP labels)")
    legend(ax_g, theme, loc="upper right", ncol=1, fontsize=6.9)
    return fig


# ---------------------------------------------------------------- J. capacity

def capacity(res, theme: Theme) -> plt.Figure:
    curves, cur = res.capacity_curves, res.record.settings.currency
    base = curves["impact_1"]
    zero = res.capacity_breakeven
    breakeven = money(zero, cur, 0, compact=True) if np.isfinite(zero) else "n/a"
    subtitle = ("Modeled, not simulated: the observed fills re-priced as if every order scaled with capital, plus "
                f"square-root impact Y·σ·√(shares / ADV) · net return reaches zero near "
                f"{breakeven} with Y = 1")
    footer = provenance(res, run_line=(
        f"Model inputs: fills of run {res.record.run_id}; σ and ADV from the 20 bars before each fill; impact on "
        f"every fill; order size scales linearly, the strategy does not adapt · {REGENERATE}"))
    frame = new_frame(theme, 5.6, "Capital and capacity sensitivity", subtitle, footer,
                      tag=f"MODELED · {data_label(res)}", axis_space=0.48)
    fig = frame.fig
    gs = fig.add_gridspec(1, 2, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom, wspace=0.26)
    ax_r, ax_p = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])
    capital = base["capital"]
    capital_ticks = FuncFormatter(lambda v, _: short_money(v))

    style_axes(ax_r, theme, grid="both")
    engine_net = base["frictionless_return_pa"] - base["commission_pa"] - base["slippage_pa"]
    floor = -0.12
    ax_r.fill_between(capital, curves["impact_2"]["net_return_pa"], curves["impact_0.5"]["net_return_pa"],
                      color=theme.cyan, alpha=0.15, lw=0, label="impact coefficient Y from 0.5 to 2")
    ax_r.plot(capital, base["frictionless_return_pa"], color=theme.faint, lw=1.0, ls=(0, (4, 2.5)),
              label="frictionless (no costs)")
    ax_r.plot(capital, engine_net, color=theme.blue, lw=1.2, label="net of simulated commission and slippage")
    ax_r.plot(capital, base["net_return_pa"], color=theme.cyan, lw=1.6, marker="o", ms=3,
              label="net incl. modeled impact, Y = 1")
    ax_r.plot(capital, curves["no_commission"]["net_return_pa"], color=theme.violet, lw=1.0, ls=(0, (1, 1.2)),
              label="same, zero commission")
    ax_r.axhline(0, color=theme.spine, lw=0.9)
    ax_r.plot([capital.iloc[0]], [engine_net.iloc[0]], marker="D", ms=5, color=theme.text, zorder=5)
    ax_r.annotate("simulated run", xy=(capital.iloc[0], engine_net.iloc[0]), xytext=(10, 6),
                  textcoords="offset points", fontsize=7.0, color=theme.text, bbox=boxed(theme))
    below = base[base["net_return_pa"] < floor]
    if len(below):
        first = below.iloc[0]
        ax_r.annotate(f"{pct(first['net_return_pa'], 0)} at {short_money(first['capital'])}",
                      xy=(first["capital"], floor), xytext=(-40, 22), textcoords="offset points", ha="right",
                      fontsize=6.8, color=theme.cyan, bbox=boxed(theme),
                      arrowprops=dict(arrowstyle="->", color=theme.cyan, lw=0.8))
    ax_r.set_xscale("log")
    ax_r.xaxis.set_major_formatter(capital_ticks)
    percent_axis(ax_r)
    ax_r.set_ylim(floor, max(base["frictionless_return_pa"].max() * 2.4, 0.08))
    ax_r.set_xlabel(f"capital ({cur}, log scale)")
    ax_r.set_title("Net return per year (simple) vs capital")
    legend(ax_r, theme, loc="upper right", ncol=1, fontsize=6.5)

    style_axes(ax_p, theme, grid="both")
    for column, label, style in (("participation_median", "median fill", "-"),
                                 ("participation_p95", "95th percentile", (0, (4, 2))),
                                 ("participation_max", "largest fill", (0, (1, 1.2)))):
        ax_p.plot(capital, base[column].clip(upper=2.0), color=theme.violet, lw=1.2, ls=style, label=label)
    ax_p.axhspan(0.10, 2.0, color=theme.negative, alpha=0.07, lw=0)
    ax_p.text(capital.iloc[0], 0.5, "above 10% of bar volume the impact model is not credible", fontsize=6.6,
              color=theme.negative, va="center")
    for level in (0.01, 0.05, 0.10):
        ax_p.axhline(level, color=theme.amber, lw=0.8, ls=(0, (3, 2)))
        ax_p.text(capital.iloc[-1], level * 1.1, f"{pct(level, 0)}", fontsize=6.6, color=theme.amber, ha="right")
    ax_p.set_xscale("log")
    ax_p.set_yscale("log")
    ax_p.set_ylim(1e-5, 2.0)
    ax_p.xaxis.set_major_formatter(capital_ticks)
    ax_p.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:g}%"))
    ax_p.set_xlabel(f"capital ({cur}, log scale)")
    ax_p.set_title("Participation: fill shares / fill-bar volume")
    legend(ax_p, theme, loc="lower right", ncol=1, fontsize=6.8)
    return fig


# ---------------------------------------------------------------- K. engineering

def engineering(res, theme: Theme) -> plt.Figure:
    eng = res.engineering
    scaling, m, lat = eng["scaling"], eng["machine"], res.latency
    subtitle = (f"Measured {eng['measured_on']} on {m['cpu']} ({m['logical_cpus']} logical CPUs, {m['memory_gb']} GB), "
                f"{m['os']}, Python {m['python']} · median of {int(scaling['repeats'].iloc[0])} runs per size")
    footer = [
        f"Workload: full backtests of {res.record.strategy_version} {res.config.params.label()} on generated synthetic "
        "universes; memory via tracemalloc in a separate run; timing via time.perf_counter",
        f"Latency: InMemoryEventBus.publish with 3 subscribers ({lat['event bus dispatch']['samples']:,} events); "
        f"submit → risk check → simulated fill → portfolio update ({lat['order to portfolio']['samples']:,} "
        "orders, zero fill delay)",
        f"Software: numpy {m['numpy']}, pandas {m['pandas']}, matplotlib {m['matplotlib']} · results vary with "
        f"machine and load · {REGENERATE}",
    ]
    frame = new_frame(theme, 5.6, "Engineering benchmarks", subtitle, footer, tag="MEASURED · THIS MACHINE",
                      axis_space=0.48)
    fig = frame.fig
    gs = fig.add_gridspec(1, 3, left=frame.left, right=frame.right, top=frame.top, bottom=frame.bottom, wspace=0.38)
    ax_t, ax_m, ax_l = (fig.add_subplot(gs[i]) for i in range(3))
    colors = [theme.cyan, theme.violet, theme.amber, theme.blue]
    count_ticks = FuncFormatter(lambda v, _: short_money(v))

    style_axes(ax_t, theme, grid="both")
    for color, (symbols, part) in zip(colors, scaling.groupby("symbols")):
        ax_t.plot(part["symbol_bars"], part["median_seconds"], marker="o", ms=3.5, lw=1.1, color=color,
                  label=f"{symbols} instrument{'s' if symbols > 1 else ''}")
    ax_t.set_xscale("log")
    ax_t.set_yscale("log")
    ax_t.xaxis.set_major_formatter(count_ticks)
    ax_t.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax_t.set_xlabel("symbol-bars processed (log)")
    ax_t.set_ylabel("seconds (log)")
    ax_t.set_title(f"Backtest runtime (log-log slope {res.scaling_slope:.2f})")
    legend(ax_t, theme, ncol=1, fontsize=6.9)
    ax_t.text(0.97, 0.05, f"{res.throughput / 1e3:.1f}k symbol-bars/s\n(median, largest runs)", transform=ax_t.transAxes,
              ha="right", va="bottom", fontsize=7.0, color=theme.muted)

    style_axes(ax_m, theme, grid="both")
    for color, (symbols, part) in zip(colors, scaling.groupby("symbols")):
        ax_m.plot(part["symbol_bars"], part["peak_traced_mb"], marker="o", ms=3.5, lw=1.1, color=color)
    ax_m.set_xscale("log")
    ax_m.set_yscale("log")
    ax_m.xaxis.set_major_formatter(count_ticks)
    ax_m.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax_m.set_xlabel("symbol-bars processed (log)")
    ax_m.set_ylabel("MB (log)")
    ax_m.set_title("Peak Python-traced memory")

    style_axes(ax_l, theme, grid="both")
    for (name, curve), color in zip(eng["latency_curves"].items(), (theme.cyan, theme.violet)):
        ax_l.plot(curve["us"], curve["probability"], color=color, lw=1.3,
                  label=f"{name}\np50 {lat[name]['p50_us']:.1f} µs · p99 {lat[name]['p99_us']:.1f} µs")
    ax_l.set_xscale("log")
    ax_l.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax_l.set_xlabel("latency (µs, log)")
    ax_l.set_ylabel("share of samples at or below")
    ax_l.set_title("In-process latency (CDF)")
    legend(ax_l, theme, loc="lower right", ncol=1, fontsize=6.5)
    return fig


FIGURES: Dict[str, Callable] = {
    "tearsheet": tearsheet,
    "drawdowns": drawdowns,
    "distribution": distribution,
    "exposure": exposure,
    "attribution": attribution,
    "trades": trades,
    "walk-forward": walk_forward,
    "robustness": robustness,
    "uncertainty": uncertainty,
    "capacity": capacity,
    "engineering": engineering,
}
