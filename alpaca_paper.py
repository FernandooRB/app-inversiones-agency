"""Read-only Alpaca Trading API adapter, fixed to the paper server."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from uuid import UUID

import httpx

PAPER_URL = "https://paper-api.alpaca.markets"
ORDER_LIMIT = 50


class AlpacaPaperError(ValueError):
    """A configuration/provider error safe to display without credentials."""


@dataclass(frozen=True)
class PaperAccount:
    id: str
    number: str
    status: str
    currency: str
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    account_blocked: bool
    trading_blocked: bool


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    asset_class: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    current_price: Decimal | None
    market_value: Decimal | None
    unrealized_pl: Decimal | None


@dataclass(frozen=True)
class PaperOrder:
    id: str
    symbol: str
    side: str
    type: str
    status: str
    quantity: Decimal | None
    notional: Decimal | None
    filled_quantity: Decimal
    filled_price: Decimal | None
    limit_price: Decimal | None
    created_at: datetime | None


@dataclass(frozen=True)
class PaperAccountSnapshot:
    account: PaperAccount
    positions: tuple[PaperPosition, ...]
    orders: tuple[PaperOrder, ...]
    fetched_at: datetime


def _text(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", value):
        raise AlpacaPaperError("Alpaca devolvió un identificador o estado inválido.")
    return value


def _number(row: dict, name: str, *, optional: bool = False) -> Decimal | None:
    value = row.get(name)
    if value is None and optional:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AlpacaPaperError("Alpaca devolvió un importe incompleto o inválido.") from None
    if not number.is_finite() or number.copy_abs() > Decimal("1e18"):
        raise AlpacaPaperError("Alpaca devolvió un importe fuera de rango.")
    return number


def _flag(row: dict, name: str) -> bool:
    value = row.get(name)
    if type(value) is not bool:
        raise AlpacaPaperError("Alpaca no confirmó las restricciones de la cuenta.")
    return value


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        raise AlpacaPaperError("Alpaca devolvió una fecha de orden inválida.") from None


class AlpacaPaperClient:
    def __init__(self, api_key: str, secret_key: str, *, expected_account_id: str = "",
                 client: httpx.Client | None = None):
        for value in (api_key, secret_key):
            if not isinstance(value, str) or not re.fullmatch(r"[\x21-\x7e]{10,256}", value):
                raise AlpacaPaperError("Configura las dos claves de Alpaca Paper en Secrets.")
        if not isinstance(expected_account_id, str):
            raise AlpacaPaperError("El identificador esperado de Alpaca debe ser un UUID válido.")
        if expected_account_id:
            try:
                expected_account_id = str(UUID(expected_account_id))
            except (ValueError, TypeError, AttributeError):
                raise AlpacaPaperError(
                    "El identificador esperado de Alpaca debe ser un UUID válido."
                ) from None
        self._api_key = api_key
        self._secret_key = secret_key
        self._expected_account_id = expected_account_id
        self._client = client

    @property
    def configuration_signature(self) -> str:
        # Invalidate private session data when credentials or the account binding change.
        return sha256("\0".join((self._api_key, self._secret_key,
                                 self._expected_account_id)).encode()).hexdigest()

    def _get(self, client: httpx.Client, path: str, *, params: dict | None = None):
        # No configurable URL, redirects, mutation methods or credential-bearing query strings.
        response = client.get(
            PAPER_URL + path, params=params, follow_redirects=False, timeout=10,
            headers={"APCA-API-KEY-ID": self._api_key,
                     "APCA-API-SECRET-KEY": self._secret_key, "Accept": "application/json"},
        )
        if response.status_code in (401, 403):
            raise AlpacaPaperError("Alpaca rechazó el acceso. Revisa que ambas claves sean de Paper Trading.")
        if response.status_code == 429:
            raise AlpacaPaperError("Alpaca limitó las consultas. Espera un momento y vuelve a actualizar.")
        if response.status_code != 200:
            raise AlpacaPaperError("No se pudo consultar Alpaca Paper. Intenta actualizar más tarde.")
        try:
            return response.json()
        except ValueError:
            raise AlpacaPaperError("Alpaca devolvió una respuesta con formato inválido.") from None

    def fetch_snapshot(self) -> PaperAccountSnapshot:
        try:
            if self._client is not None:
                return self._fetch(self._client)
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                return self._fetch(client)
        except httpx.HTTPError:
            # Never expose a request/response repr, headers or raw provider error bodies.
            raise AlpacaPaperError(
                "No se pudo conectar con Alpaca Paper. Revisa la conexión e intenta de nuevo."
            ) from None
        except (KeyError, TypeError):
            raise AlpacaPaperError(
                "Alpaca devolvió datos incompletos; la consulta no se actualizó."
            ) from None

    def _fetch(self, client: httpx.Client) -> PaperAccountSnapshot:
        row = self._get(client, "/v2/account")
        if not isinstance(row, dict):
            raise AlpacaPaperError("Alpaca devolvió una cuenta con formato inválido.")
        try:
            account_id = str(UUID(row["id"]))
        except (ValueError, TypeError, AttributeError, KeyError):
            raise AlpacaPaperError("Alpaca no devolvió un identificador de cuenta válido.") from None
        if self._expected_account_id and account_id != self._expected_account_id:
            raise AlpacaPaperError("La cuenta Paper recibida no coincide con la cuenta configurada.")
        currency = _text(row["currency"])
        if currency != "USD":
            raise AlpacaPaperError("Esta conexión espera una cuenta de simulación en USD.")
        account = PaperAccount(
            account_id, _text(row["account_number"]), _text(row["status"]), currency,
            _number(row, "equity"), _number(row, "cash"), _number(row, "buying_power"),
            _flag(row, "account_blocked"), _flag(row, "trading_blocked"),
        )
        positions = self._get(client, "/v2/positions")
        orders = self._get(client, "/v2/orders", params={
            "status": "all", "limit": str(ORDER_LIMIT), "direction": "desc", "nested": "false",
        })
        if (not isinstance(positions, list) or not isinstance(orders, list)
                or len(orders) > ORDER_LIMIT):
            raise AlpacaPaperError("Alpaca devolvió posiciones u órdenes con formato inválido.")
        parsed_positions = tuple(PaperPosition(
            _text(p["symbol"]), _text(p["asset_class"]), _text(p["side"]),
            _number(p, "qty"), _number(p, "avg_entry_price"),
            _number(p, "current_price", optional=True), _number(p, "market_value", optional=True),
            _number(p, "unrealized_pl", optional=True),
        ) for p in positions)
        parsed_orders = tuple(PaperOrder(
            _text(o["id"]), _text(o["symbol"]), _text(o["side"]),
            _text(o["type"]), _text(o["status"]), _number(o, "qty", optional=True),
            _number(o, "notional", optional=True), _number(o, "filled_qty"),
            _number(o, "filled_avg_price", optional=True), _number(o, "limit_price", optional=True),
            _timestamp(o.get("created_at")),
        ) for o in orders)
        return PaperAccountSnapshot(account, parsed_positions, parsed_orders, datetime.now(UTC))
