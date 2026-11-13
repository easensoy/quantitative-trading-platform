from datetime import datetime

import pytest

from src.core.models import AssetType, Fill, Instrument, OrderSide, Portfolio, Venue

AAPL = Instrument("AAPL", AssetType.EQUITY, "NASDAQ")


def fill(side, quantity, price, commission=0.0):
    return Fill(
        order_id="order",
        instrument=AAPL,
        side=side,
        quantity=quantity,
        price=price,
        timestamp=datetime(2024, 1, 2),
        venue=Venue.NYSE,
        trade_id="trade",
        commission=commission,
    )


def portfolio(cash=10_000.0):
    return Portfolio(id="test", name="Test", cash=cash)


def test_buy_spends_notional_plus_commission():
    book = portfolio()
    book.apply_fill(fill(OrderSide.BUY, 100, 50.0, commission=5.0))

    assert book.cash == pytest.approx(10_000 - 5_000 - 5)
    position = book.get_position("AAPL")
    assert (position.quantity, position.avg_price) == (100, 50.0)


def test_sell_receives_notional_less_commission_and_keeps_cost_basis():
    book = portfolio()
    book.apply_fill(fill(OrderSide.BUY, 100, 50.0, commission=5.0))
    book.apply_fill(fill(OrderSide.SELL, 40, 60.0, commission=2.4))

    assert book.cash == pytest.approx(4_995 + 2_400 - 2.4)
    position = book.get_position("AAPL")
    assert position.quantity == 60
    assert position.avg_price == 50.0  # a partial sale does not change the cost basis


def test_adding_to_a_position_uses_weighted_average_cost():
    book = portfolio(cash=100_000)
    book.apply_fill(fill(OrderSide.BUY, 100, 50.0))
    book.apply_fill(fill(OrderSide.BUY, 100, 60.0))

    assert book.get_position("AAPL").avg_price == pytest.approx(55.0)
    assert book.cash == pytest.approx(100_000 - 11_000)


def test_selling_through_zero_opens_a_short_at_the_fill_price():
    book = portfolio()
    book.apply_fill(fill(OrderSide.BUY, 100, 50.0))
    book.apply_fill(fill(OrderSide.SELL, 150, 60.0))

    position = book.get_position("AAPL")
    assert (position.quantity, position.avg_price) == (-50, 60.0)
    assert book.cash == pytest.approx(10_000 - 5_000 + 9_000)


def test_closing_a_position_removes_it():
    book = portfolio()
    book.apply_fill(fill(OrderSide.BUY, 100, 50.0))
    book.apply_fill(fill(OrderSide.SELL, 100, 55.0))

    assert book.get_position("AAPL") is None
    assert book.cash == pytest.approx(10_000 + 500)


def test_update_position_alone_leaves_cash_unchanged():
    book = portfolio()
    book.update_position(fill(OrderSide.BUY, 10, 50.0))

    assert book.cash == 10_000
    assert book.get_position("AAPL").quantity == 10
