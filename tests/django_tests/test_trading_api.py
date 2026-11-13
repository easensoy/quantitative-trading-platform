from decimal import Decimal

import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.trading.models import Order, Strategy, TradingAccount

from .conftest import make_account

pytestmark = pytest.mark.django_db

LIST_ENDPOINTS = [
    "/api/v1/accounts/",
    "/api/v1/strategies/",
    "/api/v1/orders/",
    "/api/v1/positions/",
    "/api/v1/trades/",
    "/api/v1/backtests/",
    "/api/v1/market-data/instruments/",
    "/api/v1/market-data/market-data/",
    "/api/v1/market-data/risk-metrics/",
    "/api/v1/market-data/providers/",
]


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_list_endpoints_require_authentication(path):
    assert APIClient().get(path).status_code in (401, 403)


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_list_endpoints_respond_for_authenticated_users(api_client, path):
    assert api_client.get(path).status_code == 200


def test_openapi_schema_is_generated(api_client):
    response = api_client.get("/api/schema/")

    assert response.status_code == 200
    assert b"/api/v1/orders/" in response.content


def test_token_authentication(user):
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    assert client.get("/api/v1/accounts/").status_code == 200


def test_created_account_belongs_to_requesting_user(api_client, user):
    response = api_client.post("/api/v1/accounts/", {
        "name": "Paper", "account_type": "paper", "initial_capital": "50000",
        "current_capital": "50000", "available_capital": "50000", "max_position_size": "5000",
    }, format="json")

    assert response.status_code == 201
    assert TradingAccount.objects.get(id=response.data["id"]).user == user


def test_accounts_are_scoped_to_their_owner(api_client, user, other_user):
    mine = make_account(user)
    theirs = make_account(other_user)

    ids = [row["id"] for row in api_client.get("/api/v1/accounts/").data["results"]]
    assert ids == [str(mine.id)]
    assert api_client.get(f"/api/v1/accounts/{theirs.id}/").status_code == 404


def test_create_order_action(api_client, user, instrument):
    make_account(user)

    response = api_client.post("/api/v1/orders/create_order/", {
        "symbol": "AAPL", "side": "buy", "order_type": "limit", "quantity": "10", "price": "150.00",
    }, format="json")

    assert response.status_code == 201
    assert response.data["status"] == "pending"
    order = Order.objects.get(id=response.data["id"])
    assert (order.account.user, order.instrument) == (user, instrument)


def test_limit_orders_require_a_price(api_client, user, instrument):
    make_account(user)

    response = api_client.post("/api/v1/orders/create_order/", {
        "symbol": "AAPL", "side": "buy", "order_type": "limit", "quantity": "10",
    }, format="json")

    assert response.status_code == 400


def test_orders_cannot_target_another_users_account(api_client, other_user, instrument):
    foreign_account = make_account(other_user)

    response = api_client.post("/api/v1/orders/", {
        "account": str(foreign_account.id), "instrument": instrument.id,
        "side": "buy", "order_type": "market", "quantity": "5",
    }, format="json")

    assert response.status_code == 400
    assert "account" in response.data
    assert not Order.objects.exists()


def test_strategies_cannot_target_another_users_account(api_client, other_user):
    foreign_account = make_account(other_user)

    response = api_client.post("/api/v1/strategies/", {
        "name": "Momentum", "strategy_type": "momentum", "account": str(foreign_account.id),
        "allocation_percentage": "10",
    }, format="json")

    assert response.status_code == 400
    assert not Strategy.objects.exists()


def test_orders_support_partial_updates(api_client, user, instrument):
    order = Order.objects.create(
        account=make_account(user), instrument=instrument, side="buy",
        order_type="limit", quantity=Decimal("10"), price=Decimal("100"),
    )

    response = api_client.patch(f"/api/v1/orders/{order.id}/", {"quantity": "20"}, format="json")
    assert response.status_code == 200
    order.refresh_from_db()
    assert order.quantity == Decimal("20")

    # Validation still sees the stored order type: a limit order cannot lose its price.
    response = api_client.patch(f"/api/v1/orders/{order.id}/", {"price": None}, format="json")
    assert response.status_code == 400


def test_cancel_order(api_client, user, instrument):
    order = Order.objects.create(
        account=make_account(user), instrument=instrument, side="buy",
        order_type="market", quantity=Decimal("10"),
    )

    assert api_client.post(f"/api/v1/orders/{order.id}/cancel/").status_code == 200
    order.refresh_from_db()
    assert order.status == "cancelled"
    assert api_client.post(f"/api/v1/orders/{order.id}/cancel/").status_code == 400


def test_account_summary_handles_zero_initial_capital(api_client, user):
    account = make_account(user, initial_capital=Decimal("0"), current_capital=Decimal("0"),
                           available_capital=Decimal("0"))

    response = api_client.get(f"/api/v1/accounts/{account.id}/summary/")

    assert response.status_code == 200
    assert response.data["total_pnl_percentage"] == Decimal("0")
