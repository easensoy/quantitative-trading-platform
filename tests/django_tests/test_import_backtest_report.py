"""import_backtest_report stores a research report's numbers unchanged and the API serves them."""
import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.trading.models import BacktestResult, TradingAccount

pytestmark = pytest.mark.django_db

PUBLISHED_REPORT = Path(__file__).resolve().parents[2] / "docs" / "reports" / "showcase"


def write_report(directory: Path, run_id="abc123", total_return=0.25, closed=10):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "evidence": {"data": "synthetic", "execution": "simulated (BacktestEngine + SimulatedBroker)",
                     "note": "Synthetic data, simulated execution."},
        "provenance": {
            "source": {"commit": "f" * 40, "clean": True, "uncommitted_files": [], "fingerprint": "e" * 64,
                       "scope": ["src/research/**/*.py"], "files": {}},
            "versions": {"strategy": "tsmom-1.0", "methodology": "1.0"},
        },
        "main_run": {
            "run_id": run_id, "label": "tsmom-1.0 L60-R5 (pre-registered)", "strategy_version": "tsmom-1.0",
            "parameters": {"lookback": 60, "rebalance_every": 5},
            "dataset": {"name": "fixture", "origin": "synthetic", "prices_sha256": "0" * 64},
            "execution": {"initial_capital": 1e6, "commission": 0.001, "slippage": 0.0005, "currency": "USD"},
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    metrics = {"start": "2019-01-01 00:00:00", "end": "2023-12-29 00:00:00", "periods_per_year": 261.06,
               "initial_equity": 1e6, "final_equity": 1e6 * (1 + total_return), "total_return": total_return,
               "cagr": 0.046, "annualized_volatility": 0.15, "sharpe": 0.35, "sortino": 0.5,
               "max_drawdown": -0.2, "calmar": 0.23, "beta": 0.1, "information_ratio": 0.05}
    trades = {"closed_trades": closed, "winning_trades": 6, "losing_trades": 4, "win_rate": 0.6,
              "average_win": 3000.0, "average_loss": -2000.0, "total_net_pnl": 10000.0}
    for name, values in (("metrics.csv", metrics), ("trade_statistics.csv", trades)):
        with (directory / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["", "value"])
            writer.writerows(values.items())
    return directory


def run_import(report_dir: Path, username: str) -> str:
    out = io.StringIO()
    call_command("import_backtest_report", str(report_dir), username=username, stdout=out)
    return out.getvalue()


def test_import_stores_the_report_numbers_and_the_api_serves_them(tmp_path, user, api_client):
    output = run_import(write_report(tmp_path / "report"), user.username)

    assert "Stored run abc123" in output
    rows = api_client.get("/api/v1/backtests/").data["results"]
    assert len(rows) == 1
    row = rows[0]
    assert Decimal(row["total_return"]) == Decimal("0.250000")
    assert Decimal(row["final_capital"]) == Decimal("1250000.00")
    assert (row["total_trades"], row["winning_trades"], row["losing_trades"]) == (10, 6, 4)
    assert Decimal(row["avg_trade_pnl"]) == Decimal("1000.0000")
    assert row["metadata"]["run_id"] == "abc123"
    assert row["metadata"]["evidence"]["data"] == "synthetic"
    assert row["metadata"]["provenance"] == {"source_commit": "f" * 40, "source_matches_commit": True,
                                             "source_fingerprint": "e" * 64, "methodology_version": "1.0"}
    assert TradingAccount.objects.get(user=user).account_type == "backtest"


def test_reimporting_a_run_updates_its_row(tmp_path, user):
    run_import(write_report(tmp_path / "first", total_return=0.25), user.username)
    output = run_import(write_report(tmp_path / "second", total_return=-0.10), user.username)

    assert "Updated run abc123" in output
    result = BacktestResult.objects.get()
    assert result.total_return == Decimal("-0.100000")


def test_import_requires_an_existing_user(tmp_path):
    with pytest.raises(CommandError, match="does not exist"):
        run_import(write_report(tmp_path / "report"), "nobody")


def test_non_finite_metrics_are_rejected(tmp_path, user):
    with pytest.raises(CommandError, match="non-finite"):
        run_import(write_report(tmp_path / "report", total_return=float("nan")), user.username)
    assert not BacktestResult.objects.exists()


@pytest.mark.skipif(not (PUBLISHED_REPORT / "manifest.json").exists(), reason="showcase report not generated")
def test_published_showcase_report_imports_unchanged(user):
    run_import(PUBLISHED_REPORT, user.username)

    manifest = json.loads((PUBLISHED_REPORT / "manifest.json").read_text(encoding="utf-8"))
    with (PUBLISHED_REPORT / "metrics.csv").open(newline="", encoding="utf-8") as handle:
        metrics = {row[0]: row[1] for row in list(csv.reader(handle))[1:]}
    result = BacktestResult.objects.get()
    assert result.metadata["run_id"] == manifest["main_run"]["run_id"]
    assert result.metadata["provenance"]["source_fingerprint"] == manifest["provenance"]["source"]["fingerprint"]
    assert abs(float(result.total_return) - float(metrics["total_return"])) < 1e-6
    assert abs(float(result.sharpe_ratio) - float(metrics["sharpe"])) < 1e-6
    assert abs(float(result.max_drawdown) - float(metrics["max_drawdown"])) < 1e-6
