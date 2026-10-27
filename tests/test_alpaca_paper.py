import json
from decimal import Decimal

import httpx
import pytest

from alpaca_paper import ORDER_LIMIT, PAPER_URL, AlpacaPaperClient, AlpacaPaperError

ACCOUNT_ID = "10000000-0000-0000-0000-000000000001"
API_KEY = "SYNTHETIC_PAPER_KEY_ONLY"
SECRET_KEY = "SYNTHETIC_PAPER_SECRET_ONLY"


def account_row():
    return {"id": ACCOUNT_ID, "account_number": "PAPER0001", "status": "ACTIVE",
            "currency": "USD", "equity": "1000.00", "cash": "900.00",
            "buying_power": "1800.00", "account_blocked": False, "trading_blocked": False}


def position_row():
    return {"symbol": "SIM", "asset_class": "us_equity", "side": "long", "qty": "1",
            "avg_entry_price": "99", "current_price": "100", "market_value": "100",
            "unrealized_pl": "1"}


def order_row():
    return {"id": "20000000-0000-0000-0000-000000000001", "symbol": "SIM",
            "side": "buy", "type": "limit", "status": "partially_filled", "qty": "2",
            "notional": None, "filled_qty": "1", "filled_avg_price": "99",
            "limit_price": "100", "created_at": "2026-10-27T20:00:00Z"}


def client_for(handler, **kwargs):
    return AlpacaPaperClient(API_KEY, SECRET_KEY,
                             client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_reads_paper_only_and_preserves_provider_values_and_recent_order_limit():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert str(request.url).startswith(PAPER_URL + "/v2/")
        assert request.headers["APCA-API-KEY-ID"] == API_KEY
        assert request.headers["APCA-API-SECRET-KEY"] == SECRET_KEY
        assert API_KEY not in str(request.url) and SECRET_KEY not in str(request.url)
        bodies = {"/v2/account": account_row(), "/v2/positions": [position_row()],
                  "/v2/orders": [order_row()]}
        return httpx.Response(200, json=bodies[request.url.path])

    snapshot = client_for(handler, expected_account_id=ACCOUNT_ID).fetch_snapshot()
    assert snapshot.account.equity == Decimal("1000.00")
    assert snapshot.account.cash == Decimal("900.00")
    assert snapshot.account.buying_power == Decimal("1800.00")
    assert snapshot.positions[0].market_value == Decimal("100")
    assert snapshot.orders[0].filled_quantity == Decimal("1")
    assert snapshot.orders[0].status == "partially_filled"
    assert snapshot.fetched_at.tzinfo is not None
    assert dict(requests[-1].url.params) == {
        "status": "all", "limit": str(ORDER_LIMIT), "direction": "desc", "nested": "false"
    }


def test_empty_account_zero_cash_and_notional_or_missing_values_are_distinct():
    row = account_row()
    row["cash"] = "0"
    order = {**order_row(), "qty": None, "notional": "10", "filled_qty": "0",
             "filled_avg_price": None, "limit_price": None}
    bodies = {"/v2/account": row, "/v2/positions": [], "/v2/orders": [order]}
    snapshot = client_for(lambda r: httpx.Response(200, json=bodies[r.url.path])).fetch_snapshot()
    assert snapshot.account.cash == Decimal(0) and snapshot.positions == ()
    assert snapshot.orders[0].quantity is None
    assert snapshot.orders[0].notional == Decimal("10")
    assert snapshot.orders[0].filled_price is None
    assert snapshot.orders[0].filled_quantity == Decimal(0)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_failures_and_redirects_never_expose_keys_or_follow_another_server(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "https://api.alpaca.markets/v2/account"},
                              json={"message": SECRET_KEY, "token": API_KEY})

    with pytest.raises(AlpacaPaperError) as error:
        client_for(handler).fetch_snapshot()
    assert len(requests) == 1
    assert SECRET_KEY not in str(error.value) and API_KEY not in str(error.value)


def test_network_failure_is_sanitized():
    def handler(request):
        raise httpx.ConnectTimeout(SECRET_KEY, request=request)

    with pytest.raises(AlpacaPaperError, match="No se pudo conectar") as error:
        client_for(handler).fetch_snapshot()
    assert SECRET_KEY not in str(error.value)


def test_account_mismatch_stops_before_positions_or_orders():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=account_row())

    with pytest.raises(AlpacaPaperError, match="no coincide"):
        client_for(handler, expected_account_id="10000000-0000-0000-0000-000000000002").fetch_snapshot()
    assert len(requests) == 1


@pytest.mark.parametrize("value", [None, "NaN", "Infinity", "garbage", True, "1e9999999"])
def test_invalid_account_amount_is_not_a_zero_or_partial_success(value):
    row = {**account_row(), "equity": value}
    with pytest.raises(AlpacaPaperError):
        client_for(lambda r: httpx.Response(200, json=row)).fetch_snapshot()


def test_partial_provider_failure_does_not_return_an_account_snapshot():
    def handler(request):
        if request.url.path == "/v2/account":
            return httpx.Response(200, json=account_row())
        return httpx.Response(503, json={"message": SECRET_KEY})

    with pytest.raises(AlpacaPaperError):
        client_for(handler).fetch_snapshot()


def test_invalid_json_and_missing_fields_are_visible():
    for response in (httpx.Response(200, text="invalid"), httpx.Response(200, json={"id": ACCOUNT_ID})):
        with pytest.raises(AlpacaPaperError):
            client_for(lambda r, response=response: response).fetch_snapshot()


@pytest.mark.parametrize("case", ["currency", "restriction", "order_date", "order_limit"])
def test_provider_units_restrictions_and_order_dates_must_be_unambiguous(case):
    account, orders = account_row(), [order_row()]
    if case == "currency":
        account["currency"] = "MXN"
    elif case == "restriction":
        account["trading_blocked"] = "false"
    elif case == "order_date":
        orders[0]["created_at"] = "2026-10-27T20:00:00"
    else:
        orders = [order_row()] * (ORDER_LIMIT + 1)
    bodies = {"/v2/account": account, "/v2/positions": [], "/v2/orders": orders}
    with pytest.raises(AlpacaPaperError):
        client_for(lambda r: httpx.Response(200, json=bodies[r.url.path])).fetch_snapshot()


def test_credentials_are_not_part_of_snapshot_or_client_repr():
    client = client_for(lambda r: httpx.Response(200, json=account_row()))
    assert API_KEY not in repr(client) and SECRET_KEY not in repr(client)
    assert API_KEY not in client.configuration_signature
    assert client.configuration_signature != client_for(lambda r: None,
        expected_account_id=ACCOUNT_ID).configuration_signature
    assert SECRET_KEY not in json.dumps(account_row())
