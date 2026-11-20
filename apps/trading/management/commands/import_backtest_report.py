"""Store the main run of a research report as a BacktestResult, so the API serves it.

    python manage.py import_backtest_report docs/reports/showcase --username demo

The report directory is written by scripts/generate_readme_assets.py (manifest.json,
metrics.csv, trade_statistics.csv). Nothing is recalculated: the row holds the numbers
the report published, and its metadata keeps the run id, dataset fingerprint, execution
model, evidence note and source provenance (commit and fingerprint), so an API client can
tell a synthetic, simulated result from anything else and trace the code behind it.
Importing the same run again updates its row instead of adding one.
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.trading.models import BacktestResult, Strategy, TradingAccount

ACCOUNT_NAME = "Research backtests"


def read_values(path: Path) -> dict:
    """A two-column (name, value) CSV as written by src.reporting.documents.write_tables."""
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return {row[0]: row[1] for row in list(csv.reader(handle))[1:] if row}
    except FileNotFoundError:
        raise CommandError(f"{path} not found; generate the report first") from None


def finite(values: dict, key: str, source: str) -> float:
    try:
        value = float(values[key])
    except KeyError:
        raise CommandError(f"{source} has no '{key}'") from None
    if not math.isfinite(value):
        raise CommandError(f"{source}: {key} is {value}; a non-finite metric is not stored")
    return value


def fixed(value: float, places: int) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(1).scaleb(-places))


class Command(BaseCommand):
    help = "Store a research report's main run as a backtest result served by /api/v1/backtests/"

    def add_arguments(self, parser):
        parser.add_argument("report_dir", type=Path, help="report data directory, e.g. docs/reports/showcase")
        parser.add_argument("--username", required=True, help="owner of the research account")

    def handle(self, *args, **options):
        report_dir: Path = options["report_dir"]
        manifest_path = report_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CommandError(f"{manifest_path} not found; generate the report first") from None
        metrics = read_values(report_dir / "metrics.csv")
        trades = read_values(report_dir / "trade_statistics.csv")
        run, evidence = manifest["main_run"], manifest["evidence"]
        provenance = manifest.get("provenance", {})
        source, versions = provenance.get("source", {}), provenance.get("versions", {})

        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist:
            raise CommandError(f"user '{options['username']}' does not exist; create it first "
                               "(manage.py createsuperuser)") from None

        def metric(key: str) -> float:
            return finite(metrics, key, "metrics.csv")

        def trade(key: str) -> float:
            return finite(trades, key, "trade_statistics.csv")

        closed = int(trade("closed_trades"))
        wins = int(trade("winning_trades")) if closed else 0
        losses = int(trade("losing_trades")) if closed else 0
        initial = fixed(metric("initial_equity"), 2)
        values = dict(
            start_date=date.fromisoformat(metrics["start"][:10]),
            end_date=date.fromisoformat(metrics["end"][:10]),
            initial_capital=initial,
            final_capital=fixed(metric("final_equity"), 2),
            total_return=fixed(metric("total_return"), 6),
            annualized_return=fixed(metric("cagr"), 6),
            volatility=fixed(metric("annualized_volatility"), 6),
            sharpe_ratio=fixed(metric("sharpe"), 6),
            max_drawdown=fixed(metric("max_drawdown"), 6),
            calmar_ratio=fixed(metric("calmar"), 6),
            total_trades=closed,
            winning_trades=wins,
            losing_trades=losses,
            win_rate=fixed(trade("win_rate") if closed else 0.0, 4),
            avg_trade_pnl=fixed(trade("total_net_pnl") / closed if closed else 0.0, 4),
            avg_winning_trade=fixed(trade("average_win") if wins else 0.0, 4),
            avg_losing_trade=fixed(trade("average_loss") if losses else 0.0, 4),
            metadata={
                "run_id": run["run_id"],
                "label": run["label"],
                "strategy_version": run["strategy_version"],
                "evidence": evidence,
                "dataset": run["dataset"],
                "execution": run["execution"],
                "periods_per_year": metric("periods_per_year"),
                "sortino": metric("sortino"),
                "beta_to_benchmark": metric("beta"),
                "information_ratio": metric("information_ratio"),
                "trades": "closed FIFO lots; break-even lots count as neither winning nor losing",
                "provenance": {
                    "source_commit": source.get("commit"),
                    "source_matches_commit": source.get("clean"),
                    "source_fingerprint": source.get("fingerprint"),
                    "methodology_version": versions.get("methodology"),
                },
                "source": "scripts/generate_readme_assets.py",
            },
        )

        with transaction.atomic():
            account, _ = TradingAccount.objects.get_or_create(
                user=user, name=ACCOUNT_NAME, account_type="backtest",
                defaults=dict(initial_capital=initial, current_capital=initial,
                              available_capital=initial, max_position_size=initial),
            )
            strategy, _ = Strategy.objects.update_or_create(
                account=account, name=run["label"][:100],
                defaults=dict(strategy_type=run["strategy_version"].rsplit("-", 1)[0],
                              parameters=run["parameters"], description=evidence["note"],
                              allocation_percentage=Decimal("100.00"), status="draft"),
            )
            result = BacktestResult.objects.filter(strategy=strategy, metadata__run_id=run["run_id"]).first()
            if result is None:
                result = BacktestResult.objects.create(strategy=strategy, **values)
                action = "Stored"
            else:
                for field, value in values.items():
                    setattr(result, field, value)
                result.save()
                action = "Updated"

        self.stdout.write(self.style.SUCCESS(
            f"{action} run {run['run_id']} ({run['label']}) as backtest {result.id} for {user.username}: "
            f"total return {float(values['total_return']):+.2%}, Sharpe {float(values['sharpe_ratio']):.2f}, "
            f"{closed} closed trades ({evidence['data']} data, {evidence['execution'].split(' ')[0]} execution)"))
