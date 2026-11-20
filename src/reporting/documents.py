"""Written outputs of a report run: manifest, metric tables, the full Markdown report and
the generated blocks inside README.md."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd

from src.reporting.theme import money, number, pct

SHOWCASE_NOTE = ("Synthetic data, simulated execution. The universe has no predictable returns by construction, "
                 "so these results demonstrate the software and its accounting, not a profitable strategy.")


def evidence_note(res) -> str:
    if res.dataset.origin.startswith("synthetic"):
        return SHOWCASE_NOTE
    return (f"{res.dataset.origin} with simulated execution (next-bar fills, modeled costs); a backtest, "
            "not paper or live trading results.")


def _jsonable(value):
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (pd.Timestamp,)):
        return str(value.date())
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def cell(text) -> str:
    """Table cell text: a literal | would end the cell in GitHub Markdown."""
    return str(text).replace("|", r"\|")


def picture(stem: str, alt: str, assets_prefix: str, width: str = "100%") -> str:
    """GitHub <picture> element: dark image under prefers-color-scheme: dark, light otherwise."""
    return (f'<picture>\n'
            f'  <source media="(prefers-color-scheme: dark)" srcset="{assets_prefix}/{stem}-dark.png">\n'
            f'  <source media="(prefers-color-scheme: light)" srcset="{assets_prefix}/{stem}-light.png">\n'
            f'  <img alt="{alt}" src="{assets_prefix}/{stem}-light.png" width="{width}">\n'
            f'</picture>')


# ---------------------------------------------------------------- engineering results

def engineering_to_json(eng: Dict, path: Path) -> None:
    payload = {**eng, "scaling": eng["scaling"].to_dict(orient="records")}
    path.write_text(json.dumps(_jsonable(payload), indent=1) + "\n", encoding="utf-8")


def engineering_from_json(path: Path) -> Dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scaling"] = pd.DataFrame(payload["scaling"])
    return payload


# ---------------------------------------------------------------- manifest and tables

def manifest(res, figures: Iterable[str]) -> Dict:
    cfg = res.config
    return _jsonable({
        "report": "README showcase",
        "evidence": {"data": res.dataset.origin, "execution": "simulated (BacktestEngine + SimulatedBroker)",
                     "note": evidence_note(res)},
        "provenance": res.provenance,
        "dataset": {k: v for k, v in res.dataset.manifest.items() if k != "spec"} | {
            "spec": res.dataset.manifest.get("spec")},
        "configuration": {
            "strategy": res.record.strategy_version, "parameters": cfg.params.as_dict(),
            "execution": asdict(cfg.settings), "rolling_windows": [cfg.rolling_vol_window, cfg.rolling_sharpe_window],
            "periods_per_year": res.ppy,
            "parameter_grid": {"lookback": list(cfg.sweep_lookbacks), "rebalance_every": list(cfg.sweep_rebalances)},
            "walk_forward": {"train_bars": cfg.train_bars, "test_bars": cfg.test_bars,
                             "selection": res.walk_forward.selection_metric},
            "bootstrap": {"method": "stationary bootstrap (Politis-Romano)", "mean_block": cfg.bootstrap_mean_block,
                          "samples": cfg.bootstrap_samples, "seed": cfg.bootstrap_seed,
                          "horizon_bars": int(round(res.ppy)) if cfg.bootstrap_horizon is None else cfg.bootstrap_horizon},
            "capacity": {"capital_levels": list(cfg.capital_levels), "impact_coefficients": list(cfg.impact_coefficients),
                         "model": "Y * sigma * sqrt(shares / ADV) * notional, sigma/ADV from 20 prior bars"},
        },
        "main_run": res.record.manifest(),
        "walk_forward_runs": [w.test.manifest() for w in res.walk_forward.windows],
        "parameter_sweep": res.sweep.reindex(columns=["label", "status", "error", "run_id", "sharpe", "cost_pa"])
        .to_dict(orient="records"),
        "checks": [asdict(c) for c in res.checks],
        "environment": res.environment,
        "figures": sorted(figures),
    })


def write_tables(res, directory: Path) -> List[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "metrics.csv": pd.Series({k: v for k, v in res.stats.items()}, name="value").to_frame(),
        "monthly_returns.csv": res.monthly,
        "drawdowns.csv": res.episodes,
        "pnl_by_instrument.csv": res.decomposition.by_symbol,
        # runtime_seconds is wall-clock time; dropping it keeps reruns byte-identical
        "parameter_sweep.csv": res.sweep.drop(columns=["tag", "runtime_seconds"], errors="ignore"),
        "walk_forward.csv": res.wf_table,
        "bootstrap_quantiles.csv": pd.Series(res.bootstrap_quantiles, name="value").to_frame(),
        "regimes.csv": pd.concat({"strategy": res.regimes, "benchmark": res.benchmark_regimes})
        if res.regimes is not None else pd.DataFrame(),
        "capacity.csv": pd.concat(res.capacity_curves, names=["scenario"]).reset_index(level=0),
        "trade_statistics.csv": pd.Series(res.trade_stats, name="value").to_frame(),
    }
    paths = []
    for name, frame in tables.items():
        path = directory / name
        frame.to_csv(path, lineterminator="\n", float_format="%.10g")
        paths.append(path)
    return paths


def write_manifest(res, path: Path, figures: Iterable[str]) -> None:
    path.write_text(json.dumps(manifest(res, figures), indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- Markdown

def max_drawdown_basis(episode, last_date) -> str:
    """Peak, trough and recovery of the maximum drawdown, all from the one episode that
    produced it (drawdowns.deepest_episode), never from the latest episode."""
    if episode is None:
        return "No drawdown: equity never fell below a previous peak"
    span = f"Peak {episode['peak']:%Y-%m-%d} to trough {episode['trough']:%Y-%m-%d}"
    if episode["recovered"]:
        return f"{span}; recovered {episode['recovery']:%Y-%m-%d}"
    return f"{span}; not recovered by the end of the data ({last_date:%Y-%m-%d})"


def source_line(prov: Dict) -> str:
    """The source commit and fingerprint behind a report, in one table cell."""
    src = prov["source"]
    if src.get("commit") is None:
        where = "Git metadata unavailable"
    elif src.get("clean"):
        where = f"commit `{src['commit']}`"
    else:
        n = len(src.get("uncommitted_files", []))
        where = f"commit `{src['commit']}` plus uncommitted changes to {n} file{'' if n == 1 else 's'}"
    return (f"{where}; source fingerprint `{src['fingerprint'][:16]}` over {len(src['files'])} files "
            "(scope and per-file hashes in manifest.json)")


def dependency_line(prov: Dict) -> str:
    installed = prov["dependencies"]["installed"]
    names = ["python", "numpy", "pandas", "scipy", "matplotlib", "pillow"]
    return ", ".join(f"{'Python' if n == 'python' else n} {installed[n].split()[-1]}" for n in names if n in installed)


def metrics_table(res) -> str:
    s, d, cur = res.stats, res.decomposition, res.record.settings.currency
    q = res.bootstrap_quantiles
    rows = [
        (f"Total return ({res.years:.1f} years)", pct(s["total_return"], 1, sign=True),
         "Final equity / initial capital − 1"),
        ("CAGR", pct(s["cagr"], 1, sign=True), f"Annualized over {res.years:.2f} calendar years"),
        ("Volatility", pct(s["annualized_volatility"], 1), f"Daily sd × √{res.ppy:.1f}"),
        ("Sharpe ratio", number(s["sharpe"], 2), "rf = 0%: the simulation pays no interest on cash"),
        ("Max drawdown", pct(s["max_drawdown"], 1),
         max_drawdown_basis(res.max_drawdown_episode, res.record.equity.index[-1])),
        ("Costs paid", money(d.commissions + d.slippage, cur, 0, compact=True),
         f"{money(d.commissions, cur, 0, compact=True)} commission + {money(d.slippage, cur, 0, compact=True)} slippage"),
        ("Walk-forward, out of sample", pct(res.oos_stats["total_return"], 1, sign=True),
         f"Sharpe {number(res.oos_stats['sharpe'], 2, sign=True)} across {len(res.wf_table)} evaluation windows"),
        ("Bootstrap P(1-year loss)", pct(q["p_loss"], 0), "Conditional on this history; not a forecast"),
    ]
    lines = ["| Measure | Value | Basis |", "| --- | ---: | --- |"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(lines)


def benchmark_table(res) -> str:
    if not res.engineering:
        return "_Engineering benchmarks were not run._"
    eng, lat = res.engineering, res.latency
    scaling = eng["scaling"]
    largest = scaling.sort_values("symbol_bars").iloc[-1]
    m = eng["machine"]
    lines = [
        "| Measurement | Result | Method |",
        "| --- | ---: | --- |",
        f"| Backtest throughput | {res.throughput / 1e3:.1f}k symbol-bars/s | "
        "Median of the largest runs, momentum strategy |",
        f"| Largest run | {int(largest['symbols'])} instruments × {int(largest['bars']):,} bars in "
        f"{largest['median_seconds']:.2f} s | Median of {int(largest['repeats'])} runs |",
        f"| Runtime scaling | exponent {res.scaling_slope:.2f} | Log-log fit of runtime vs symbol-bars (1.0 = linear) |",
        f"| Peak traced memory | {largest['peak_traced_mb']:.1f} MB | tracemalloc, largest run |",
        f"| Event-bus dispatch | p50 {lat['event bus dispatch']['p50_us']:.1f} µs, p99 "
        f"{lat['event bus dispatch']['p99_us']:.1f} µs | {lat['event bus dispatch']['samples']:,} publishes, "
        "3 subscribers |",
        f"| Order → portfolio | p50 {lat['order to portfolio']['p50_us']:.1f} µs, p99 "
        f"{lat['order to portfolio']['p99_us']:.1f} µs | Risk check, simulated fill, portfolio update, in process |",
    ]
    return "\n".join(lines) + (f"\n\nMeasured {eng['measured_on']} on {m['cpu']} ({m['logical_cpus']} logical CPUs, "
                               f"{m['memory_gb']} GB), {m['os']}, Python {m['python']}.")


def checks_table(res) -> str:
    lines = ["| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {cell(c.name)} | {'pass' if c.passed else '**FAIL**'} | {cell(c.detail)} |" for c in res.checks]
    return "\n".join(lines)


def _drawdown_table(res) -> str:
    lines = ["| # | Peak | Trough | Recovered | Depth | Peak→trough | Trough→recovery | Total |",
             "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for i, ep in res.top_drawdowns.iterrows():
        rec = ep["recovery"].strftime("%Y-%m-%d") if ep["recovered"] else "not recovered"
        recovery_days = f"{int(ep['recovery_bars'])} d" if ep["recovered"] else "—"
        lines.append(f"| {i + 1} | {ep['peak']:%Y-%m-%d} | {ep['trough']:%Y-%m-%d} | {rec} | {pct(ep['depth'], 1)} | "
                     f"{ep['peak_to_trough_bars']:.0f} d | {recovery_days} | {ep['duration_bars']:.0f} d |")
    return "\n".join(lines)


def _walk_forward_table(res) -> str:
    lines = ["| Window | Training | Evaluation | Selected | In-sample Sharpe | Out-of-sample Sharpe "
             "| Out-of-sample return |",
             "| ---: | --- | --- | --- | ---: | ---: | ---: |"]
    for _, r in res.wf_table.iterrows():
        lines.append(f"| {r['window']} | {r['train_start']:%Y-%m-%d} → {r['train_end']:%Y-%m-%d} | "
                     f"{r['test_start']:%Y-%m-%d} → {r['test_end']:%Y-%m-%d} | {r['selected']} | "
                     f"{number(r['train_sharpe'], 2)} | {number(r['test_sharpe'], 2, sign=True)} | "
                     f"{pct(r['test_return'], 1, sign=True)} |")
    return "\n".join(lines)


def _capacity_table(res) -> str:
    curve = res.capacity_curves["impact_1"]
    lines = ["| Capital | Frictionless | Commission | Slippage | Modeled impact | Net (modeled) | Median participation |",
             "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for _, r in curve.iterrows():
        lines.append(f"| {money(r['capital'], 'USD', 0, compact=True)} | {pct(r['frictionless_return_pa'], 1, sign=True)} | "
                     f"{pct(-r['commission_pa'], 1)} | {pct(-r['slippage_pa'], 1)} | {pct(-r['impact_pa'], 1)} | "
                     f"{pct(r['net_return_pa'], 1, sign=True)} | {pct(r['participation_median'], 3)} |")
    return "\n".join(lines)


GALLERY = [
    ("tearsheet", "Performance tear sheet",
     "Account value, cumulative and benchmark-relative return, drawdown, rolling risk, monthly returns and summary "
     "statistics of the pre-registered run."),
    ("attribution", "P&L and cost attribution",
     "How frictionless trading P&L becomes net P&L after slippage (inside fill prices) and commissions; financing is "
     "not modeled. Per-instrument contributions sum to the portfolio result."),
    ("trades", "Trades and execution",
     "Fills on the price path, FIFO-matched closed lots, turnover and costs, and the order → fill → lot "
     "accounting."),
    ("drawdowns", "Drawdowns and recovery", "Depth, duration and recovery of the five deepest drawdowns."),
    ("distribution", "Return distribution and tails",
     "Empirical tail estimates next to fitted normal and Student-t models, and a normal Q–Q plot."),
    ("exposure", "Exposure and diversification",
     "Long/short exposure, instrument weights with listing and warm-up gaps, correlations and effective breadth."),
    ("walk-forward", "Walk-forward validation",
     "Parameters chosen on two-year training windows, then evaluated unchanged on the following six months."),
    ("robustness", "Parameter robustness", "Every configuration of the lookback × rebalance grid, including the poor ones."),
    ("uncertainty", "Scenario and uncertainty analysis",
     "Block-bootstrap distributions of one-year outcomes and performance by volatility regime."),
    ("capacity", "Capital and capacity sensitivity",
     "A cost model, not a simulation: modeled net return and participation as capital grows."),
    ("engineering", "Engineering benchmarks", "Measured runtime, memory and in-process latency."),
]


def interpretation(res) -> str:
    s, q, oos = res.stats, res.bootstrap_quantiles, res.oos_stats
    context = (" on data that contains no predictable returns" if res.dataset.origin.startswith("synthetic") else "")
    return (f"The pre-registered run returned {pct(s['total_return'], 1, sign=True)} over {res.years:.1f} years"
            f"{context}, with a Sharpe ratio of {number(s['sharpe'], 2)}. The walk-forward evaluation returned "
            f"{pct(oos['total_return'], 1, sign=True)} out of sample, the parameter grid spans Sharpe ratios from "
            f"{number(res.sweep['sharpe'].min(), 2, sign=True)} to {number(res.sweep['sharpe'].max(), 2, sign=True)}, "
            f"and the bootstrap puts the chance of a losing year at {pct(q['p_loss'], 0)}.")


def attribution_line(res) -> str:
    d, cur = res.decomposition, res.record.settings.currency
    return (f"Frictionless P&L {money(d.frictionless, cur, 0, sign=True)} − slippage {money(d.slippage, cur, 0)} − "
            f"commissions {money(d.commissions, cur, 0)} = net {money(d.net, cur, 0, sign=True)}; final equity − "
            f"initial capital = {money(d.equity_change, cur, 0, sign=True)} (residual {money(d.residual, cur, 2)}).")


def walk_forward_summary(res) -> str:
    wf, oos = res.wf_table, res.oos_stats
    profitable = int((wf["test_return"] > 0).sum())
    switches = int((wf["selected"] != wf["selected"].shift()).sum()) - 1
    return (f"Every training window found a configuration with an in-sample Sharpe ratio of at least "
            f"{number(wf['train_sharpe'].min(), 2)}. Out of sample, {profitable} of {len(wf)} evaluation windows made "
            f"money and the stitched result was {pct(oos['total_return'], 1, sign=True)} (Sharpe "
            f"{number(oos['sharpe'], 2, sign=True)}); the selected configuration changed {switches} times in "
            f"{len(wf)} windows.")


def robustness_summary(res) -> str:
    sweep = res.sweep
    ok = sweep[sweep["status"] == "ok"]
    best, worst = ok.loc[ok["sharpe"].idxmax()], ok.loc[ok["sharpe"].idxmin()]
    label = res.config.params.label()
    own = ok.loc[ok["label"] == label, "sharpe"]
    sharpe = float(own.iloc[0]) if len(own) else float(res.stats["sharpe"])
    failed = len(sweep) - len(ok)
    rank = int((ok["sharpe"] > sharpe).sum()) + 1
    return (f"{len(sweep)} configurations ({failed} failed to run): {int((ok['sharpe'] < 0).sum())} lost money "
            f"(negative Sharpe ratio), the best was {best['label']} at {number(best['sharpe'], 2, sign=True)} and "
            f"the worst {worst['label']} at {number(worst['sharpe'], 2, sign=True)}. The pre-registered {label} "
            f"ranks {ordinal(rank)} of {len(ok)}.")


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _sentence_case(name: str) -> str:
    """Lower-case the first letter unless the first word is an acronym (P&L, FIFO)."""
    first = name.split()[0]
    return name if any(ch.isupper() for ch in first[1:]) else name[0].lower() + name[1:]


def console_summary(res) -> str:
    """The closing lines scripts/generate_readme_assets.py prints."""
    s, oos, q = res.stats, res.oos_stats, res.bootstrap_quantiles
    return "\n".join([
        f"Run {res.record.run_id} ({res.record.label}) on {res.dataset.origin} data '{res.dataset.name}'",
        f"  total return {s['total_return']:+.1%}  CAGR {s['cagr']:+.1%}  volatility "
        f"{s['annualized_volatility']:.1%}  Sharpe {s['sharpe']:.2f}  max drawdown {s['max_drawdown']:.1%}",
        f"  walk-forward out-of-sample return {oos['total_return']:+.1%}  bootstrap P(1-year loss) {q['p_loss']:.0%}",
        f"  {sum(c.passed for c in res.checks)}/{len(res.checks)} consistency checks passed",
    ])


def checks_summary(res, report_href: str) -> str:
    passed = sum(c.passed for c in res.checks)
    names = ", ".join(_sentence_case(c.name) for c in res.checks)
    return (f"**{passed} of {len(res.checks)} consistency checks passed** in this run: {names}. The generator writes "
            f"nothing if one fails; details are in [the report]({report_href}#consistency-checks).")


def full_report(res, assets_prefix: str, dataset_href: str = "", methodology_href: str = "") -> str:
    cur = res.record.settings.currency
    ts = res.trade_stats
    r = res.record
    parts = [
        "<!-- Generated by scripts/generate_readme_assets.py; edits are overwritten. -->",
        "# Showcase report: time-series momentum on "
        + ("a synthetic universe" if res.dataset.origin.startswith("synthetic") else f"`{res.dataset.name}`"),
        "",
        f"> **Evidence category:** {evidence_note(res)}",
        "",
        "| | |",
        "| --- | --- |",
        f"| Data | {res.dataset.origin}: `{res.dataset.name}` ({len(res.dataset.symbols)} instruments, "
        f"{r.equity.index[0]:%Y-%m-%d} → {r.equity.index[-1]:%Y-%m-%d}, daily, Mon–Fri calendar), "
        f"prices.csv sha256 `{res.dataset.fingerprint[:16]}`"
        + (f"; see [the dataset]({dataset_href})" if dataset_href else "") + " |",
        f"| Strategy | `{r.strategy_version}` {res.config.params.label()}, parameters fixed before the first run |",
        f"| Execution | {r.settings.describe()}; initial capital {cur} {r.settings.initial_capital:,.0f} |",
        f"| Main run | `{r.run_id}`: {len(r.executions):,} fills, {len(r.orders):,} orders, "
        f"{int((~r.orders['accepted']).sum()) if len(r.orders) else 0} rejected |",
        f"| Source | {source_line(res.provenance)} |",
        f"| Software | {dependency_line(res.provenance)}; requirement files fingerprinted in manifest.json |",
        "| Method | " + (f"[methodology]({methodology_href})" if methodology_href else "docs/methodology.md")
        + f", version {res.provenance['versions']['methodology']} |",
        "",
        "## Headline results",
        "",
        metrics_table(res),
        "",
        interpretation(res),
        "",
    ]
    for stem, title, text in GALLERY:
        parts += [f"## {title}", "", text, "", picture(stem, title, assets_prefix), ""]
        if stem == "drawdowns":
            parts += [_drawdown_table(res), ""]
        if stem == "attribution":
            parts += [attribution_line(res), ""]
        if stem == "trades":
            parts += [f"{ts['closed_trades']:,} closed FIFO lots, win rate {pct(ts['win_rate'], 1)}, profit factor "
                      f"{ts['profit_factor']:.2f}, median holding period {ts['median_holding_bars']:.0f} trading days, "
                      f"annual turnover {res.annual_turnover:.1f}× equity.", ""]
        if stem == "walk-forward":
            parts += [_walk_forward_table(res), "", walk_forward_summary(res), ""]
        if stem == "robustness":
            parts += [robustness_summary(res), ""]
        if stem == "capacity":
            parts += [_capacity_table(res), ""]
        if stem == "engineering":
            parts += [benchmark_table(res), ""]
    parts += ["## Consistency checks", "", "The generator stops with an error if any of these fail.", "",
              checks_table(res), "",
              "## Files", "",
              "In [showcase/](showcase/):", "",
              "- `manifest.json`: configuration, provenance (source commit, source, dependency and dataset "
              "fingerprints, versions), run ids, checks and environment",
              "- CSV tables: metrics, monthly returns, drawdowns, P&L by instrument, parameter sweep, walk-forward, "
              "bootstrap quantiles, regimes, capacity, trade statistics",
              "- `engineering.json`: benchmark results, reused with `--reuse-engineering`", ""]
    return "\n".join(parts)


def update_readme_blocks(readme: Path, blocks: Dict[str, str]) -> List[str]:
    """Replace the text between <!-- showcase:NAME:start --> and <!-- showcase:NAME:end -->."""
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8")
    updated = []
    for name, body in blocks.items():
        pattern = re.compile(rf"(<!-- showcase:{name}:start -->\n).*?(\n<!-- showcase:{name}:end -->)", re.S)
        if pattern.search(text):
            text = pattern.sub(lambda m: m.group(1) + body + m.group(2), text)
            updated.append(name)
    readme.write_text(text, encoding="utf-8")
    return updated
