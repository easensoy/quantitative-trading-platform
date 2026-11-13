from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.market_data.models import DataProvider, Instrument, MarketData
from apps.trading.models import Order, Position, Strategy, Trade

from .conftest import make_account

pytestmark = pytest.mark.django_db


def test_trading_records_belong_to_an_account_and_cascade_with_it(user, instrument):
    account = make_account(user)
    strategy = Strategy.objects.create(
        name="Momentum", strategy_type="momentum", account=account,
        allocation_percentage=Decimal("50"),
    )
    strategy.instruments.add(instrument)
    order = Order.objects.create(
        account=account, strategy=strategy, instrument=instrument,
        side="buy", order_type="market", quantity=Decimal("10"),
    )
    Trade.objects.create(order=order, quantity=Decimal("10"), price=Decimal("100"),
                         execution_timestamp=timezone.now(), trade_id="T-1")
    Position.objects.create(account=account, instrument=instrument,
                            quantity=Decimal("10"), avg_cost=Decimal("100"))

    assert user.trading_accounts.get() == account
    assert list(instrument.strategies.all()) == [strategy]
    assert list(strategy.orders.all()) == [order]
    assert order.trades.count() == 1

    account.delete()

    for model in (Strategy, Order, Trade, Position):
        assert not model.objects.exists(), model.__name__
    assert Instrument.objects.filter(pk=instrument.pk).exists()  # shared reference data


def test_one_position_per_account_and_instrument(user, instrument):
    account = make_account(user)
    Position.objects.create(account=account, instrument=instrument)

    with pytest.raises(IntegrityError), transaction.atomic():
        Position.objects.create(account=account, instrument=instrument)


def test_market_data_is_unique_per_instrument_timestamp_and_provider(instrument):
    provider = DataProvider.objects.create(name="synthetic")
    bar = dict(instrument=instrument, provider=provider, timestamp=timezone.now(),
               open_price=1, high_price=1, low_price=1, close_price=1, volume=1)
    MarketData.objects.create(**bar)

    with pytest.raises(IntegrityError), transaction.atomic():
        MarketData.objects.create(**bar)
