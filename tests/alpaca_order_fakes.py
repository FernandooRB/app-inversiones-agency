"""Synthetic Paper server responses; no real credentials or external requests."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from alpaca_paper import AlpacaPaperClient

ACCOUNT_ID = "10000000-0000-0000-0000-000000000001"
ORDER_ID = "20000000-0000-0000-0000-000000000001"
NOW = datetime(2026, 10, 27, 22, tzinfo=UTC)


class FakePaper:
    def __init__(self, now=NOW):
        self.now = now
        self.requests = []
        self.mode = "accepted"
        self.orders = {}
        self.positions = []
        self.asset = {"symbol": "SIM", "class": "us_equity", "tradable": True, "status": "active"}
        self.account = {"id": ACCOUNT_ID, "account_number": "SYNTHETIC0001", "status": "ACTIVE",
                        "currency": "USD", "equity": "1000", "cash": "1000", "buying_power": "4000",
                        "non_marginable_buying_power": "1000",
                        "account_blocked": False, "trading_blocked": False,
                        "trade_suspended_by_user": False}
        self.clock = {"timestamp": now.isoformat(), "is_open": False,
                      "next_open": (now + timedelta(days=1)).isoformat()}
        self.client = AlpacaPaperClient("SYNTHETIC_PAPER_ID", "SYNTHETIC_PAPER_SECRET",
            client=httpx.Client(transport=httpx.MockTransport(self.handle), follow_redirects=True))

    @property
    def posts(self):
        return [request for request in self.requests if request.method == "POST"]

    def handle(self, request):
        self.requests.append(request)
        assert request.url.host == "paper-api.alpaca.markets" and request.url.scheme == "https"
        assert request.headers["APCA-API-KEY-ID"] == "SYNTHETIC_PAPER_ID"
        path = request.url.path
        if request.method == "GET":
            bodies = {"/v2/account": self.account, "/v2/positions": self.positions,
                      "/v2/orders": list(self.orders.values()), "/v2/assets/SIM": self.asset,
                      "/v2/clock": self.clock}
            if path == "/v2/orders:by_client_order_id":
                row = self.orders.get(request.url.params["client_order_id"])
                return httpx.Response(200, json=row) if row else httpx.Response(404)
            return httpx.Response(200, json=bodies[path])
        assert request.method == "POST" and path == "/v2/orders"
        data = json.loads(request.content)
        assert data["type"] == "limit" and data["time_in_force"] == "day"
        assert data["extended_hours"] is False and data["order_class"] == "simple"
        if self.mode == "rejected":
            return httpx.Response(422, json={"message": "SYNTHETIC_PAPER_SECRET"})
        if self.mode == "redirect":
            return httpx.Response(302, headers={"Location": "https://api.alpaca.markets/v2/orders"})
        row = {**data, "id": ORDER_ID, "status": "new", "filled_qty": "0", "filled_avg_price": None,
               "created_at": self.now.isoformat()}
        if self.mode == "wrong_receipt":
            row["symbol"] = "OTHER"
        if self.mode != "timeout_no_accept":
            self.orders[data["client_order_id"]] = row
        if self.mode == "duplicate":
            return httpx.Response(422, json={"message": "client_order_id must be unique"})
        if self.mode.startswith("timeout"):
            raise httpx.ReadTimeout("SYNTHETIC_PAPER_SECRET", request=request)
        return httpx.Response(200, json=row)
