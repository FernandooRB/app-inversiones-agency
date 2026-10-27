"""Validated manual paper-order proposals and broker receipts; no network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from alpaca_paper import AlpacaPaperError

CLIENT_ID = re.compile(r"sig-paper-[0-9a-f]{32}")


def decimal_value(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AlpacaPaperError("Indica un precio o cantidad válido.") from None
    if not number.is_finite() or number.copy_abs() > Decimal("1e12"):
        raise AlpacaPaperError("El precio o cantidad está fuera de rango.")
    return number


def limit_inputs(symbol: str, side: str, quantity: object, price: object):
    symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol) or side not in ("buy", "sell"):
        raise AlpacaPaperError("Indica un símbolo de acciones de EE. UU. y un lado válido.")
    qty, price = decimal_value(quantity), decimal_value(price)
    if qty < 1 or qty != qty.to_integral_value() or qty > 10000:
        raise AlpacaPaperError("La prueba admite entre 1 y 10,000 títulos enteros.")
    if price <= 0 or price > 1000000:
        raise AlpacaPaperError("El precio límite debe ser positivo y no superar 1,000,000 USD.")
    places = Decimal("0.01") if price >= 1 else Decimal("0.0001")
    if price != price.quantize(places):
        raise AlpacaPaperError("Usa hasta 2 decimales desde 1 USD, o 4 decimales por debajo de 1 USD.")
    return symbol, side, int(qty), price


@dataclass(frozen=True)
class LimitDraft:
    account_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    limit_price: Decimal
    prepared_at: datetime
    market_open: bool
    next_open: datetime

    def payload(self) -> dict:
        symbol, side, qty, price = limit_inputs(self.symbol, self.side, self.quantity, self.limit_price)
        if not CLIENT_ID.fullmatch(self.client_order_id):
            raise AlpacaPaperError("El identificador de la propuesta no es válido.")
        return {"symbol": symbol, "side": side, "qty": str(qty), "limit_price": str(price),
                "type": "limit", "time_in_force": "day", "extended_hours": False,
                "order_class": "simple", "client_order_id": self.client_order_id}

    def to_json(self):
        return {"version": 1, **self.payload(), "prepared_at": self.prepared_at.isoformat(),
                "market_open": self.market_open, "next_open": self.next_open.isoformat(),
                "purpose": "manual_paper_execution_test"}

    @classmethod
    def from_json(cls, account_id: str, row: dict):
        try:
            symbol, side, qty, price = limit_inputs(row["symbol"], row["side"], row["qty"],
                                                    row["limit_price"])
            draft = cls(str(UUID(account_id)), row["client_order_id"], symbol, side, qty, price,
                        datetime.fromisoformat(row["prepared_at"]), row["market_open"],
                        datetime.fromisoformat(row["next_open"]))
            if (row["version"] != 1 or row["purpose"] != "manual_paper_execution_test"
                    or type(draft.market_open) is not bool or draft.prepared_at.tzinfo is None
                    or draft.next_open.tzinfo is None or any(
                        row.get(key) != value for key, value in draft.payload().items())):
                raise ValueError
            return draft
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AlpacaPaperError("La propuesta guardada contiene datos inválidos.") from None


def new_draft(account_id: str, symbol: str, side: str, qty: object, price: object,
              clock: dict, now: datetime | None = None) -> LimitDraft:
    symbol, side, qty, price = limit_inputs(symbol, side, qty, price)
    try:
        now = now or datetime.now(UTC)
        next_open = datetime.fromisoformat(clock["next_open"])
        timestamp = datetime.fromisoformat(clock["timestamp"])
        if (now.tzinfo is None or next_open.tzinfo is None or timestamp.tzinfo is None
                or type(clock["is_open"]) is not bool or abs((now - timestamp).total_seconds()) > 120
                or (not clock["is_open"] and next_open <= timestamp)):
            raise ValueError
        return LimitDraft(str(UUID(account_id)), "sig-paper-" + uuid4().hex, symbol, side, qty,
                          price, now, clock["is_open"], next_open)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AlpacaPaperError("Alpaca no confirmó un horario de mercado reciente y válido.") from None


def validate_receipt(draft: LimitDraft, row: dict) -> dict:
    try:
        expected = draft.payload()
        if (not isinstance(row, dict) or any(row.get(key) != expected[key] for key in
                ("symbol", "side", "type", "time_in_force", "extended_hours", "client_order_id"))
                or decimal_value(row["qty"]) != draft.quantity
                or decimal_value(row["limit_price"]) != draft.limit_price
                or row.get("order_class", "") not in ("", "simple") or row.get("legs") not in (None, [])):
            raise ValueError
        order_id = str(UUID(row["id"]))
        status = row["status"]
        filled = decimal_value(row["filled_qty"])
        price = None if row.get("filled_avg_price") is None else decimal_value(row["filled_avg_price"])
        if (not re.fullmatch(r"[a-z_]{1,40}", status) or not 0 <= filled <= draft.quantity
                or (filled > 0 and (price is None or price <= 0))
                or (status == "filled" and filled != draft.quantity)):
            raise ValueError
        return {**expected, "id": order_id, "status": status, "filled_qty": str(filled),
                "filled_avg_price": str(price) if price is not None else None}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AlpacaPaperError(
            "La respuesta de Alpaca no confirma la orden revisada; requiere conciliación."
        ) from None
