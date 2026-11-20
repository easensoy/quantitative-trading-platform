"""Engineering measurements: backtest scaling, memory and in-process event latency.

All timings use time.perf_counter(_ns) on the machine running the report; results are
stored with the hardware and software description from machine_info().
"""
from __future__ import annotations

import asyncio
import ctypes
import os
import platform
import statistics
import sys
import time
import tracemalloc
from dataclasses import replace
from datetime import datetime
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from src.research.datasets import DEFAULT_INSTRUMENTS, SyntheticUniverseSpec, generate_synthetic_universe
from src.research.experiments import ExecutionSettings, run_backtest
from src.research.strategies import MomentumParameters


def _total_memory_bytes() -> int:
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.ullTotalPhys)
    return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _os_name() -> str:
    if sys.platform == "win32":
        build = int(platform.version().split(".")[-1])
        # Python 3.11 reports Windows 11 as release "10"; builds >= 22000 are Windows 11.
        return f"Windows {'11' if build >= 22000 else platform.release()} (build {build})"
    return f"{platform.system()} {platform.release()}"


def machine_info() -> Dict[str, str]:
    import matplotlib
    import scipy
    return {
        "cpu": _cpu_name(),
        "logical_cpus": str(os.cpu_count()),
        "memory_gb": f"{_total_memory_bytes() / 2 ** 30:.1f}",
        "os": _os_name(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "matplotlib": matplotlib.__version__,
    }


def _scaled_spec(n_symbols: int, n_bars: int) -> SyntheticUniverseSpec:
    base = DEFAULT_INSTRUMENTS[:7]  # full-history instruments
    instruments = tuple(replace(base[i % len(base)], symbol=f"{base[i % len(base)].symbol}{i // len(base)}",
                                listed_from=None) for i in range(n_symbols))
    end = pd.bdate_range("2010-01-01", periods=n_bars)[-1]
    return SyntheticUniverseSpec(name=f"bench_{n_symbols}x{n_bars}", seed=123, start="2010-01-01",
                                 end=str(end.date()), instruments=instruments,
                                 halted_symbol=instruments[0].symbol, halted_days=0)


def backtest_scaling(symbol_counts: Sequence[int], bar_counts: Sequence[int], repeats: int = 3) -> pd.DataFrame:
    """Median wall time of full backtests (default strategy) per dataset size."""
    rows = []
    settings = ExecutionSettings()
    for n_symbols in symbol_counts:
        for n_bars in bar_counts:
            dataset = generate_synthetic_universe(_scaled_spec(n_symbols, n_bars))
            timings = []
            for _ in range(repeats):
                record = run_backtest(dataset, MomentumParameters(), settings)
                timings.append(record.runtime_seconds)
            tracemalloc.start()
            run_backtest(dataset, MomentumParameters(), settings)
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            symbol_bars = sum(len(frame) for frame in dataset.bars.values())
            median = statistics.median(timings)
            rows.append({"symbols": n_symbols, "bars": n_bars, "symbol_bars": symbol_bars,
                         "fills": len(record.executions), "median_seconds": median,
                         "min_seconds": min(timings), "max_seconds": max(timings), "repeats": repeats,
                         "symbol_bars_per_second": symbol_bars / median,
                         "peak_traced_mb": peak / 2 ** 20})
    return pd.DataFrame(rows)


def event_bus_latency(events: int = 20_000, subscribers: int = 3) -> np.ndarray:
    """Nanoseconds per InMemoryEventBus.publish with `subscribers` async handlers that
    record the payload (the dispatch cost the trading services pay per quote)."""
    from src.core.event_bus import InMemoryEventBus

    async def measure() -> np.ndarray:
        bus = InMemoryEventBus()
        sink: List[Dict] = []

        async def handler(data):
            sink.append(data)

        for _ in range(subscribers):
            await bus.subscribe("market_data", handler)
        samples = np.empty(events, dtype=np.int64)
        for i in range(events):
            start = time.perf_counter_ns()
            await bus.publish("market_data", {"symbol": "TEC_A", "i": i})
            samples[i] = time.perf_counter_ns() - start
        return samples

    return asyncio.run(measure())


def order_to_portfolio_latency(orders: int = 2_000) -> np.ndarray:
    """Nanoseconds from OrderExecutionService.submit_order to the portfolio update, through
    the risk check, the simulated engine (zero fill delay) and the event bus."""
    from src.core.container import ServiceRegistry
    from src.core.models import AssetType, Instrument, MarketData, Order, OrderSide, OrderType
    from src.services.application_service import TradingApplicationService

    async def measure() -> np.ndarray:
        ServiceRegistry.reset()
        app = TradingApplicationService({
            "initial_capital": 1_000_000.0,
            "market_data": {"provider": "simulated", "poll_interval": 1.0, "seed": 1},
            "event_bus": {"type": "memory"},
            "risk": {"max_position_size": 1_000_000, "max_portfolio_leverage": 3.0, "max_daily_loss": 0.05},
            "execution": {"commission": 0.001, "slippage": 0.0005, "fill_delay": (0.0, 0.0)},
        })
        await app.initialize()
        instrument = Instrument("TEC_A", AssetType.EQUITY, "SYNTH")
        await app.event_bus.publish("market_data", {"symbol": "TEC_A", "market_data": MarketData(
            instrument=instrument, timestamp=datetime(2024, 1, 2), bid=99.95, ask=100.05, last=100.0)})
        arrivals: List[int] = []
        app.portfolio_service.add_position_callback(lambda position, fill: arrivals.append(time.perf_counter_ns()))
        samples = np.empty(orders, dtype=np.int64)
        for i in range(orders):
            side = OrderSide.BUY if i % 2 == 0 else OrderSide.SELL
            order = Order(id="", instrument=instrument, side=side, order_type=OrderType.MARKET, quantity=10)
            seen = len(arrivals)
            start = time.perf_counter_ns()
            await app.order_execution_service.submit_order(order)
            while len(arrivals) == seen:
                await asyncio.sleep(0)
            samples[i] = arrivals[-1] - start
        ServiceRegistry.reset()
        return samples

    return asyncio.run(measure())


def latency_summary(samples_ns: np.ndarray) -> Dict[str, float]:
    us = samples_ns / 1_000.0
    return {"samples": int(len(us)), "p50_us": float(np.percentile(us, 50)), "p95_us": float(np.percentile(us, 95)),
            "p99_us": float(np.percentile(us, 99)), "max_us": float(us.max()), "mean_us": float(us.mean())}
