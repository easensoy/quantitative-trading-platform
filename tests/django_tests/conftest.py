from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from apps.market_data.models import DataProvider, Instrument, MarketData
from apps.trading.models import TradingAccount
from src.backtesting.synthetic import generate_ohlcv


@pytest.fixture
def user(db):
    return User.objects.create_user("alice", password="test-only-password-1")


@pytest.fixture
def other_user(db):
    return User.objects.create_user("bob", password="test-only-password-2")


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def instrument(db):
    return Instrument.objects.create(symbol="AAPL", name="Apple Inc.", asset_type="equity", exchange="NASDAQ")


def make_account(user, **overrides):
    values = dict(
        name="Paper account",
        account_type="paper",
        initial_capital=Decimal("100000"),
        current_capital=Decimal("100000"),
        available_capital=Decimal("100000"),
        max_position_size=Decimal("10000"),
    )
    values.update(overrides)
    return TradingAccount.objects.create(user=user, **values)


def seed_daily_bars(symbol="AAPL", days=300, seed=1):
    """Store synthetic daily bars ending yesterday for one instrument (no network)."""
    provider, _ = DataProvider.objects.get_or_create(name="yfinance", defaults={"is_active": True})
    instrument, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_type": "equity", "exchange": "NASDAQ"}
    )
    last = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
    frame = generate_ohlcv(
        start=str((last - timedelta(days=days - 1)).date()), end=str(last.date()), seed=seed
    )
    MarketData.objects.bulk_create([
        MarketData(
            instrument=instrument,
            provider=provider,
            timestamp=last - timedelta(days=len(frame) - 1 - index),
            open_price=Decimal(f"{bar.open:.4f}"),
            high_price=Decimal(f"{bar.high:.4f}"),
            low_price=Decimal(f"{bar.low:.4f}"),
            close_price=Decimal(f"{bar.close:.4f}"),
            volume=int(bar.volume),
        )
        for index, bar in enumerate(frame.itertuples())
    ])
    return instrument
