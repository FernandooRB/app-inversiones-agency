"""Decimal account ledger with separate economic and settlement dates.

Valuations require unadjusted quotes. Adjusted total-return prices would count
dividends twice when cash distributions are recorded in this book.
"""

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from portfolio_core import PortfolioError

KINDS = {
    "OPEN_CASH",
    "OPEN_POSITION",
    "DEPOSIT",
    "WITHDRAWAL",
    "BUY",
    "SELL",
    "DIVIDEND",
    "COUPON",
    "INTEREST",
    "FEE",
    "TAX",
    "SPLIT",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "ASSET_IN",
    "ASSET_OUT",
    "FX_IN",
    "FX_OUT",
}
COLUMNS = (
    "ID",
    "Fecha",
    "Liquidacion",
    "Tipo",
    "Instrumento",
    "Moneda",
    "Cantidad",
    "Precio",
    "Importe",
    "Comision",
    "Impuesto",
    "Referencia",
    "MomentoFlujo",
)
ZERO = Decimal(0)


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal("1e15"):
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError) as exc:
        raise PortfolioError("Hay un importe o una cantidad inválidos en el libro.") from exc


@dataclass(frozen=True)
class Event:
    id: str
    day: date
    settled: date
    kind: str
    asset: str = ""
    currency: str = "MXN"
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    amount: Decimal = ZERO  # positive gross cash amount, separate from fees/taxes
    fee: Decimal = ZERO
    tax: Decimal = ZERO
    reference: str = ""
    timing: str = "UNKNOWN"

    def __post_init__(self):
        for name in ("quantity", "price", "amount", "fee", "tax"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if self.kind not in KINDS or self.currency not in {"MXN", "USD"}:
            raise PortfolioError("Tipo de movimiento o moneda fuera del alcance MXN/USD.")
        if not isinstance(self.day, date) or not isinstance(self.settled, date) or self.settled < self.day:
            raise PortfolioError("Las fechas de operación y liquidación no son válidas.")
        if self.timing not in {"BOD", "EOD", "UNKNOWN"}:
            raise PortfolioError("Declara el momento del flujo: BOD, EOD o UNKNOWN.")
        for value in (self.id, self.asset, self.reference):
            if not isinstance(value, str) or len(value) > 160 or any(ord(c) < 32 for c in value):
                raise PortfolioError("Identificador de movimiento inválido.")
        if not self.id or any(
            getattr(self, key) < 0 for key in ("quantity", "price", "amount", "fee", "tax")
        ):
            raise PortfolioError("Los movimientos requieren ID e importes no negativos.")
        positions = {"BUY", "SELL", "OPEN_POSITION", "ASSET_IN", "ASSET_OUT", "SPLIT"}
        if self.kind in positions and (not self.asset or self.quantity <= 0):
            raise PortfolioError("El movimiento de títulos requiere instrumento y cantidad positivos.")
        if self.kind in {"BUY", "SELL"}:
            if self.price <= 0 or abs(self.quantity * self.price - self.amount) > Decimal("0.01"):
                raise PortfolioError("Cantidad por precio no reproduce el importe bruto de la operación.")
        elif self.kind in {"OPEN_POSITION", "SPLIT", "ASSET_IN", "ASSET_OUT"}:
            if self.amount or self.fee or self.tax:
                raise PortfolioError("Un movimiento sin efectivo no admite importe ni cargos.")
        elif self.quantity or self.price:
            raise PortfolioError("Un movimiento de efectivo no admite títulos ni precio.")
        if self.kind in {"ASSET_IN", "ASSET_OUT"} and self.price <= 0:
            raise PortfolioError(
                "Una transferencia de títulos requiere valor unitario para separar el flujo."
            )
        if self.kind in {"TRANSFER_IN", "TRANSFER_OUT", "FX_IN", "FX_OUT", "ASSET_IN", "ASSET_OUT"}:
            if not self.reference:
                raise PortfolioError("Una transferencia o conversión requiere referencia verificable.")
        if self.kind == "SELL" and self.fee + self.tax > self.amount:
            raise PortfolioError("Los cargos de una venta exceden su importe.")

    @property
    def cash(self) -> Decimal:
        if self.kind in {"OPEN_POSITION", "SPLIT", "ASSET_IN", "ASSET_OUT"}:
            return ZERO
        debit = self.kind in {"BUY", "WITHDRAWAL", "FEE", "TAX", "TRANSFER_OUT", "FX_OUT"}
        return (-self.amount if debit else self.amount) - self.fee - self.tax


def merge_events(*batches) -> tuple[Event, ...]:
    """Identical IDs are idempotent; conflicting evidence never replaces history."""
    result = {}
    for batch in batches:
        for event in batch:
            if not isinstance(event, Event):
                raise PortfolioError("El libro contiene una fila no normalizada.")
            if event.id in result and result[event.id] != event:
                raise PortfolioError("El mismo ID identifica movimientos diferentes; revisa la importación.")
            result[event.id] = event
    if len(result) > 20000:
        raise PortfolioError("El libro excede 20,000 movimientos.")
    fx_pairs = defaultdict(list)
    for event in result.values():
        if event.kind in {"FX_IN", "FX_OUT"}:
            fx_pairs[event.reference].append(event)
    for pair in fx_pairs.values():
        if (
            len(pair) != 2
            or {event.kind for event in pair} != {"FX_IN", "FX_OUT"}
            or len({event.currency for event in pair}) != 2
            or len({event.day for event in pair}) != 1
        ):
            raise PortfolioError(
                "Una conversión requiere dos patas en monedas distintas con la misma fecha y referencia."
            )
    # Same-day row order is the declared event sequence; IDs are not timestamps.
    return tuple(sorted(result.values(), key=lambda row: row.day))


def read_ledger(raw: bytes) -> tuple[Event, ...]:
    if not 0 < len(raw) <= 8_000_000:
        raise PortfolioError("El libro está vacío o excede 8 MB.")
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise PortfolioError("Los encabezados no corresponden al libro normalizado.")
        events = []
        for row in reader:
            if len(events) >= 20000 or None in row or any(value is None for value in row.values()):
                raise PortfolioError("El libro tiene filas o columnas fuera del formato.")
            events.append(
                Event(
                    row["ID"],
                    date.fromisoformat(row["Fecha"]),
                    date.fromisoformat(row["Liquidacion"]),
                    row["Tipo"],
                    row["Instrumento"],
                    row["Moneda"],
                    *(
                        decimal(row[key] or "0")
                        for key in ("Cantidad", "Precio", "Importe", "Comision", "Impuesto")
                    ),
                    row["Referencia"],
                    row["MomentoFlujo"],
                )
            )
        if not events:
            raise PortfolioError("El libro no contiene movimientos.")
        return merge_events(events)
    except (UnicodeError, csv.Error, ValueError) as exc:
        if isinstance(exc, PortfolioError):
            raise
        raise PortfolioError("No se pudo leer el libro normalizado.") from exc


def book_at(events, cutoff: date) -> dict:
    """Positions on trade date; cash on settlement date, with signed receivables/payables."""
    positions, cash, pending = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for event in merge_events(events):
        if event.day > cutoff:
            continue
        key = (event.asset, event.currency)
        if event.kind in {"BUY", "OPEN_POSITION", "ASSET_IN"}:
            positions[key] += event.quantity
        elif event.kind in {"SELL", "ASSET_OUT"}:
            positions[key] -= event.quantity
        elif event.kind == "SPLIT":
            if positions[key] <= 0:
                raise PortfolioError(
                    "Un split requiere una posición previa; Cantidad es la razón nueva/anterior."
                )
            positions[key] *= event.quantity
        if positions[key] < 0:
            raise PortfolioError("La secuencia de títulos produciría una posición corta no autorizada.")
        target = cash if event.settled <= cutoff else pending
        target[event.currency] += event.cash
    # Drop placeholder keys produced by pure cash events.
    positions = {key: value for key, value in positions.items() if key[0] and value}
    return {"positions": positions, "cash": dict(cash), "pending": dict(pending)}


def value_book(book: dict, quotes: dict, fx: dict, *, base="MXN", raw_prices_confirmed=False) -> dict:
    """Exact-cut quotes/FX must be selected and validated by the caller; no silent fill."""
    if base not in {"MXN", "USD"} or raw_prices_confirmed is not True:
        raise PortfolioError("Confirma cotizaciones sin ajuste y una moneda base MXN/USD.")
    values = []
    for (asset, currency), quantity in book["positions"].items():
        if (asset, currency) not in quotes or decimal(quotes[(asset, currency)]) <= 0:
            raise PortfolioError("Falta una cotización de cierre sin ajuste para un instrumento.")
        values.append((asset, currency, quantity * decimal(quotes[(asset, currency)])))
    for kind in ("cash", "pending"):
        values.extend((kind, currency, amount) for currency, amount in book[kind].items())
    total = ZERO
    detail = []
    for asset, currency, value in values:
        rate = Decimal(1) if currency == base else decimal(fx.get((currency, base), 0))
        if rate <= 0:
            raise PortfolioError("Falta el tipo de cambio explícito para la moneda del corte.")
        converted = value * rate
        total += converted
        detail.append(
            {
                "Instrumento": asset,
                "Moneda": currency,
                "ValorOrigen": value,
                "FX": rate,
                "ValorBase": converted,
            }
        )
    return {"nav": total, "detail": detail, "base": base}


def ledger_json(events) -> bytes:
    return json.dumps(
        [asdict(event) for event in merge_events(events)], default=str, ensure_ascii=False, sort_keys=True
    ).encode()
