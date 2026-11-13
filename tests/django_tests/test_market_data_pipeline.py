"""Management commands and Celery tasks over synthetic bars (no network, no broker).

The commands run their ORM work through asgiref's sync_to_async, which uses another
thread and so another database connection; transaction=True commits the seeded rows
so that connection can see them.
"""
import asyncio
from io import StringIO

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command
from django.db import connections

from apps.market_data.models import DataQualityCheck, RiskMetrics, TechnicalIndicator
from apps.market_data.tasks import calculate_risk_metrics_task, calculate_technical_indicators_task

from .conftest import seed_daily_bars

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def close_executor_thread_connections():
    yield
    # Close the connection the commands opened in asgiref's executor thread, so a
    # PostgreSQL test database can be dropped at the end of the run.
    asyncio.run(sync_to_async(connections.close_all)())


def test_calculate_risk_metrics_command_updates_instead_of_duplicating():
    seed_daily_bars()
    output = StringIO()

    call_command("calculate_risk_metrics", stdout=output)
    call_command("calculate_risk_metrics", "--force-recalculate", stdout=output)

    assert RiskMetrics.objects.count() == 1
    assert "Errors: 0" in output.getvalue()
    assert "Completed with" not in output.getvalue()


def test_data_quality_check_command_records_each_check_type():
    seed_daily_bars()

    call_command("data_quality_check", stdout=StringIO())

    assert set(DataQualityCheck.objects.values_list("check_type", flat=True)) == {
        "completeness", "consistency", "timeliness",
    }


def test_risk_metrics_task_runs_eagerly():
    seed_daily_bars()

    result = calculate_risk_metrics_task.delay().get()

    assert result["status"] == "success"
    assert (result["processed"], result["errors"]) == (1, 0)


def test_technical_indicators_task_runs_eagerly():
    seed_daily_bars()

    result = calculate_technical_indicators_task.delay().get()

    assert (result["status"], result["processed"], result["errors"]) == ("success", 1, 0)
    assert TechnicalIndicator.objects.exists()
