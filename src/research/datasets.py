"""Market datasets for research runs.

Two sources share one on-disk layout (a directory with prices.csv, instruments.csv,
an optional regimes.csv and manifest.json):

* generate_synthetic_universe() builds the documented synthetic universe used by the
  README showcase. Its prices follow a factor model with constant drift, regime-switching
  volatility and Student-t shocks. Nothing in it is predictable, so it can exercise the
  software and the accounting but cannot show that a strategy works.
* load_dataset() reads that layout, and also user-supplied historical data in the same
  format, validating it before any backtest sees it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.research.provenance import normalized_sha256

PRICE_FIELDS = ["open", "high", "low", "close", "volume"]
DATASET_FILES = ("prices.csv", "instruments.csv", "regimes.csv", "manifest.json")  # what load_dataset() reads
TRADING_DAYS_PER_YEAR = 252
CALM, TURBULENT = "calm", "turbulent"


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    sector: Optional[str]  # None: classification missing (a deliberate data-quality case)
    start_price: float
    market_beta: float
    sector_loading: float
    idio_vol: float  # annualized, calm regime
    adv_shares: int  # typical daily volume in shares
    listed_from: Optional[str] = None  # ISO date; None means listed for the whole sample


DEFAULT_INSTRUMENTS: Tuple[InstrumentSpec, ...] = (
    InstrumentSpec("TEC_A", "Technology", 180.0, 1.25, 0.8, 0.22, 4_000_000),
    InstrumentSpec("TEC_B", "Technology", 95.0, 1.15, 0.8, 0.26, 3_000_000),
    InstrumentSpec("FIN_A", "Financials", 60.0, 1.05, 0.7, 0.18, 6_000_000),
    InstrumentSpec("FIN_B", "Financials", 42.0, 1.10, 0.7, 0.21, 5_000_000),
    InstrumentSpec("NRG_A", "Energy", 75.0, 0.80, 1.0, 0.24, 3_500_000),
    InstrumentSpec("HLT_A", "Healthcare", 130.0, 0.70, 0.6, 0.17, 2_500_000),
    InstrumentSpec("UTL_A", "Utilities", 55.0, 0.45, 0.5, 0.13, 2_000_000),
    InstrumentSpec("NEW_A", None, 25.0, 1.30, 0.0, 0.35, 1_500_000, listed_from="2021-01-04"),
)


@dataclass(frozen=True)
class SyntheticUniverseSpec:
    """Data-generating process of the synthetic universe. Every value is documented in
    docs/methodology.md; none was chosen by looking at strategy results."""
    name: str = "synthetic_universe_v1"
    seed: int = 20261120
    start: str = "2019-01-01"
    end: str = "2023-12-29"
    market_drift: float = 0.06  # annualized log drift of the market factor
    market_vol: float = 0.16  # annualized, calm regime
    sector_vol: float = 0.10  # annualized, calm regime
    turbulent_vol_multiplier: float = 2.25
    p_stay_calm: float = 0.985
    p_stay_turbulent: float = 0.95
    t_dof: float = 5.0
    halted_symbol: str = "TEC_B"
    halted_days: int = 5
    instruments: Tuple[InstrumentSpec, ...] = DEFAULT_INSTRUMENTS


@dataclass
class MarketDataset:
    """Validated OHLCV bars per symbol plus metadata, ready for BacktestEngine."""
    name: str
    origin: str  # "synthetic", "historical market data", ... (from the manifest)
    bars: Dict[str, pd.DataFrame]
    instruments: pd.DataFrame  # index: symbol; columns: sector (may be NaN), listed_from
    regimes: Optional[pd.Series] = None  # index: date; values: "calm" / "turbulent"
    manifest: Dict = field(default_factory=dict)
    directory: Optional[Path] = None  # where it was loaded from or written to; None if only in memory

    @property
    def symbols(self) -> List[str]:
        return list(self.bars)

    def file_fingerprints(self) -> Dict[str, str]:
        """Normalized SHA-256 of each file load_dataset() reads, hashed from disk; for a dataset
        that only exists in memory, the file checksums its manifest records (if any)."""
        if self.directory is not None:
            return {name: normalized_sha256(self.directory / name) for name in DATASET_FILES
                    if (self.directory / name).is_file()}
        return {name: info["sha256"] for name, info in self.manifest.get("files", {}).items()}

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(set().union(*(frame.index for frame in self.bars.values()))))

    @property
    def fingerprint(self) -> str:
        return self.manifest.get("files", {}).get("prices.csv", {}).get("sha256", "unhashed")

    def closes(self) -> pd.DataFrame:
        return pd.DataFrame({s: f["close"] for s, f in self.bars.items()}).reindex(self.calendar)

    def volumes(self) -> pd.DataFrame:
        return pd.DataFrame({s: f["volume"] for s, f in self.bars.items()}).reindex(self.calendar)

    def sector_of(self, symbol: str) -> Optional[str]:
        sector = self.instruments.loc[symbol, "sector"] if symbol in self.instruments.index else None
        return sector if isinstance(sector, str) and sector else None


def _unit_t(rng: np.random.Generator, dof: float, size: int) -> np.ndarray:
    """Student-t draws rescaled to unit variance."""
    return rng.standard_t(dof, size=size) / np.sqrt(dof / (dof - 2.0))


def generate_synthetic_universe(spec: SyntheticUniverseSpec = SyntheticUniverseSpec()) -> MarketDataset:
    rng = np.random.default_rng(spec.seed)
    dates = pd.bdate_range(spec.start, spec.end)
    n = len(dates)
    dt = 1.0 / TRADING_DAYS_PER_YEAR

    # Two-state Markov chain for the volatility regime.
    switch_draws = rng.random(n)
    regime = np.zeros(n, dtype=np.int8)
    for t in range(1, n):
        stay = spec.p_stay_calm if regime[t - 1] == 0 else spec.p_stay_turbulent
        regime[t] = regime[t - 1] if switch_draws[t] <= stay else 1 - regime[t - 1]
    vol_scale = np.where(regime == 1, spec.turbulent_vol_multiplier, 1.0)

    market = spec.market_drift * dt + spec.market_vol * np.sqrt(dt) * vol_scale * _unit_t(rng, spec.t_dof, n)
    sectors = sorted({i.sector for i in spec.instruments if i.sector})
    sector_factor = {
        s: spec.sector_vol * np.sqrt(dt) * vol_scale * _unit_t(rng, spec.t_dof, n) for s in sectors
    }

    bars: Dict[str, pd.DataFrame] = {}
    for inst in spec.instruments:
        idio_scale = 1.0 + 0.5 * (vol_scale - 1.0)  # idiosyncratic risk rises less in stress
        returns = inst.market_beta * market + inst.idio_vol * np.sqrt(dt) * idio_scale * _unit_t(rng, spec.t_dof, n)
        if inst.sector:
            returns = returns + inst.sector_loading * sector_factor[inst.sector]
        calm_daily_vol = np.sqrt(
            (inst.market_beta * spec.market_vol) ** 2
            + (inst.sector_loading * spec.sector_vol) ** 2 * bool(inst.sector)
            + inst.idio_vol ** 2
        ) * np.sqrt(dt)
        daily_vol = calm_daily_vol * vol_scale

        gap_noise = rng.normal(0.0, 1.0, n)
        high_noise = np.abs(rng.normal(0.0, 1.0, n))
        low_noise = np.abs(rng.normal(0.0, 1.0, n))
        volume_noise = rng.normal(0.0, 1.0, n)

        first = 0 if inst.listed_from is None else int(np.searchsorted(dates, pd.Timestamp(inst.listed_from)))
        r = returns[first:]
        close = inst.start_price * np.exp(np.cumsum(r))
        prev_close = np.concatenate(([inst.start_price], close[:-1]))
        sigma = daily_vol[first:]
        open_ = prev_close * np.exp(0.3 * r + 0.2 * sigma * gap_noise[first:])
        high = np.maximum(open_, close) * np.exp(0.4 * sigma * high_noise[first:])
        low = np.minimum(open_, close) * np.exp(-0.4 * sigma * low_noise[first:])
        volume = inst.adv_shares * np.exp(0.25 * volume_noise[first:]) * (0.6 + 0.4 * np.abs(r) / sigma)

        frame = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=dates[first:],
        )
        frame[["open", "high", "low", "close"]] = frame[["open", "high", "low", "close"]].round(2)
        frame["high"] = frame[["high", "open", "close"]].max(axis=1)
        frame["low"] = frame[["low", "open", "close"]].min(axis=1)
        frame["volume"] = frame["volume"].round().astype(np.int64)
        bars[inst.symbol] = frame

    # Simulated trading halts: the symbol has no bar on these days; the next bar's close
    # carries the moves of the missing days.
    halted = bars[spec.halted_symbol]
    lo, hi = int(0.1 * len(halted)), int(0.9 * len(halted))
    halt_positions = np.sort(rng.choice(np.arange(lo, hi), size=spec.halted_days, replace=False))
    bars[spec.halted_symbol] = halted.drop(halted.index[halt_positions])

    instruments = pd.DataFrame(
        {
            "sector": [i.sector or "" for i in spec.instruments],
            "listed_from": [str(bars[i.symbol].index[0].date()) for i in spec.instruments],
        },
        index=pd.Index([i.symbol for i in spec.instruments], name="symbol"),
    )
    regimes = pd.Series(np.where(regime == 1, TURBULENT, CALM), index=dates, name="regime")
    manifest = {
        "name": spec.name,
        "origin": "synthetic",
        "description": "Synthetic equity-like universe: factor model, regime-switching volatility, "
                       "Student-t shocks, constant drift; no predictable returns by construction.",
        "generator": "src.research.datasets.generate_synthetic_universe",
        "spec": _spec_to_dict(spec),
        "calendar": "business days (Mon-Fri), no exchange holidays",
        "currency": "USD",
        "data_quality_cases": {
            "late_listing": [i.symbol for i in spec.instruments if i.listed_from],
            "missing_sector": [i.symbol for i in spec.instruments if not i.sector],
            "halted_days": {spec.halted_symbol: [str(d.date()) for d in halted.index[halt_positions]]},
        },
    }
    return MarketDataset(spec.name, "synthetic", bars, instruments, regimes, manifest)


def _spec_to_dict(spec: SyntheticUniverseSpec) -> Dict:
    data = asdict(spec)
    data["instruments"] = [asdict(i) for i in spec.instruments]
    return data


def _normalized_sha256(path: Path) -> str:
    """SHA-256 of a text file with line endings normalized to LF (and a byte-order mark
    removed), so the value does not depend on how Git checked the file out. The same
    normalization as the source fingerprints in src/research/provenance.py."""
    return normalized_sha256(path)


def write_dataset(dataset: MarketDataset, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    prices = pd.concat(
        [frame.assign(symbol=symbol) for symbol, frame in dataset.bars.items()]
    ).rename_axis("date").reset_index()
    prices = prices[["date", "symbol", *PRICE_FIELDS]].sort_values(["date", "symbol"])
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
    prices.to_csv(directory / "prices.csv", index=False, lineterminator="\n", float_format="%.2f")
    dataset.instruments.to_csv(directory / "instruments.csv", lineterminator="\n")
    files = ["prices.csv", "instruments.csv"]
    if dataset.regimes is not None:
        regimes = dataset.regimes.rename_axis("date").reset_index()
        regimes["date"] = regimes["date"].dt.strftime("%Y-%m-%d")
        regimes.to_csv(directory / "regimes.csv", index=False, lineterminator="\n")
        files.append("regimes.csv")

    manifest = dict(dataset.manifest)
    manifest["files"] = {
        name: {"sha256": _normalized_sha256(directory / name),
               "rows": sum(1 for _ in (directory / name).open(encoding="utf-8")) - 1}
        for name in files
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dataset.manifest = manifest
    dataset.directory = directory
    return directory


class DatasetError(ValueError):
    pass


def load_dataset(directory: Path, verify_checksums: bool = True) -> MarketDataset:
    """Load and validate a dataset directory (see module docstring for the layout).

    Without a manifest the origin is recorded as "unspecified (user-supplied)".
    """
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if verify_checksums:
        for name, info in manifest.get("files", {}).items():
            actual = _normalized_sha256(directory / name)
            if actual != info.get("sha256"):
                raise DatasetError(f"{name}: checksum {actual[:12]} does not match manifest {info.get('sha256', '')[:12]}")

    prices = pd.read_csv(directory / "prices.csv", parse_dates=["date"])
    missing = {"date", "symbol", *PRICE_FIELDS} - set(prices.columns)
    if missing:
        raise DatasetError(f"prices.csv is missing columns: {sorted(missing)}")
    bars = {}
    for symbol, frame in prices.groupby("symbol", sort=True):
        frame = frame.set_index("date")[PRICE_FIELDS].astype(float)
        frame["volume"] = frame["volume"].astype(np.int64)
        _validate_bars(symbol, frame)
        bars[symbol] = frame

    instruments_path = directory / "instruments.csv"
    if instruments_path.exists():
        instruments = pd.read_csv(instruments_path, index_col="symbol", keep_default_na=True)
    else:
        instruments = pd.DataFrame(index=pd.Index(sorted(bars), name="symbol"))
    if "sector" not in instruments.columns:
        instruments["sector"] = np.nan
    instruments = instruments.reindex(sorted(bars))

    regimes = None
    if (directory / "regimes.csv").exists():
        regimes = pd.read_csv(directory / "regimes.csv", parse_dates=["date"]).set_index("date")["regime"]

    origin = manifest.get("origin", "unspecified (user-supplied)")
    return MarketDataset(manifest.get("name", directory.name), origin, bars, instruments, regimes, manifest,
                         directory=directory)


def _validate_bars(symbol: str, frame: pd.DataFrame) -> None:
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise DatasetError(f"{symbol}: dates must be unique and increasing")
    values = frame[PRICE_FIELDS].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DatasetError(f"{symbol}: non-finite prices or volumes")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise DatasetError(f"{symbol}: prices must be positive")
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any() or (
        frame["low"] > frame[["open", "close"]].min(axis=1)
    ).any():
        raise DatasetError(f"{symbol}: high/low do not bracket open and close")
