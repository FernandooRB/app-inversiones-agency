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
    "OPEN_REPO",
    "REPO_START",
    "REPO_MATURITY",
}
LEGACY_COLUMNS = (
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
COLUMNS = (*LEGACY_COLUMNS, "Interes")
REPO_KINDS = {"OPEN_REPO", "REPO_START", "REPO_MATURITY"}
REPO_VALUE_COLUMNS = ("Fecha", "Referencia", "Moneda", "Valor", "Fuente")
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
    interest: Decimal = ZERO  # included in amount at REPO_MATURITY, never added twice

    def __post_init__(self):
        for name in ("quantity", "price", "amount", "fee", "tax", "interest"):
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
            getattr(self, key) < 0 for key in ("quantity", "price", "amount", "fee", "tax", "interest")
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
        if self.kind in REPO_KINDS:
            if not self.reference.strip() or self.amount <= self.interest:
                raise PortfolioError("Un reporto requiere referencia única y capital positivo.")
            if self.kind != "REPO_MATURITY" and self.interest:
                raise PortfolioError("El interés cobrado del reporto se declara sólo al vencimiento.")
            if self.kind == "OPEN_REPO" and (self.day != self.settled or self.fee or self.tax):
                raise PortfolioError("El reporto inicial no mueve efectivo ni admite liquidación futura.")
            if self.kind == "REPO_MATURITY" and self.fee + self.tax > self.amount:
                raise PortfolioError("Los cargos del reporto exceden su cobro bruto.")
        elif self.interest:
            raise PortfolioError("Interes se usa sólo para desglosar el cobro de REPO_MATURITY.")

    @property
    def cash(self) -> Decimal:
        if self.kind in {"OPEN_POSITION", "SPLIT", "ASSET_IN", "ASSET_OUT", "OPEN_REPO"}:
            return ZERO
        debit = self.kind in {"BUY", "WITHDRAWAL", "FEE", "TAX", "TRANSFER_OUT", "FX_OUT", "REPO_START"}
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
    ordered = tuple(sorted(result.values(), key=lambda row: row.day))
    repos, matured = {}, set()
    for event in ordered:
        if event.kind not in REPO_KINDS:
            continue
        ref = event.reference
        if event.kind in {"OPEN_REPO", "REPO_START"}:
            if ref in repos or ref in matured:
                raise PortfolioError("Cada reporto requiere una referencia única, incluso tras vencer.")
            repos[ref] = event
        else:
            origin = repos.get(ref)
            if origin is None:
                raise PortfolioError("El vencimiento de reporto requiere una apertura previa y única.")
            if event.currency != origin.currency or event.asset != origin.asset:
                raise PortfolioError("La moneda y el instrumento del reporto deben conservarse al vencer.")
            if event.day < origin.settled:
                raise PortfolioError("Un reporto no puede vencer antes de liquidar su apertura.")
            if event.amount - event.interest != origin.amount:
                raise PortfolioError("El cobro bruto menos interés no reproduce el capital del reporto.")
            del repos[ref]
            matured.add(ref)
    return ordered


def read_ledger(raw: bytes) -> tuple[Event, ...]:
    if not 0 < len(raw) <= 8_000_000:
        raise PortfolioError("El libro está vacío o excede 8 MB.")
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        headers = tuple(reader.fieldnames or ())
        if headers not in {COLUMNS, LEGACY_COLUMNS}:
            raise PortfolioError("Los encabezados no corresponden al libro normalizado.")
        if headers == LEGACY_COLUMNS:
            # Legacy books remain valid; repos require an explicit interest column.
            repo_columns = False
        else:
            repo_columns = True
        events = []
        for row in reader:
            if len(events) >= 20000 or None in row or any(value is None for value in row.values()):
                raise PortfolioError("El libro tiene filas o columnas fuera del formato.")
            if row["Tipo"] in REPO_KINDS and not repo_columns:
                raise PortfolioError("Los reportos requieren la plantilla con la columna Interes.")
            if row["Tipo"] == "REPO_MATURITY" and not row.get("Interes", "").strip():
                raise PortfolioError("Declara Interes al vencer un reporto; usa 0 si está documentado.")
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
                    decimal(row.get("Interes") or "0"),
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
    repos = {}
    for event in merge_events(events):
        if event.day > cutoff:
            continue
        key = (event.asset, event.currency)
        if event.kind in {"OPEN_REPO", "REPO_START"}:
            repos[(event.reference, event.currency)] = event.amount
        elif event.kind == "REPO_MATURITY":
            del repos[(event.reference, event.currency)]
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
    return {"positions": positions, "cash": dict(cash), "pending": dict(pending), "repos": repos}


def read_repo_values(raw: bytes, cutoff: date) -> dict:
    """Documented total values, not collateral unit prices or inferred accruals."""
    if not 0 < len(raw) <= 2_000_000:
        raise PortfolioError("La valuación de reportos está vacía o excede 2 MB.")
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        if tuple(reader.fieldnames or ()) != REPO_VALUE_COLUMNS:
            raise PortfolioError("La valuación de reportos requiere Fecha,Referencia,Moneda,Valor,Fuente.")
        values = {}
        for row in reader:
            if (
                len(values) >= 20000 or None in row or any(v is None for v in row.values())
                or row["Fecha"] != cutoff.isoformat() or row["Moneda"] not in {"MXN", "USD"}
                or not row["Referencia"].strip() or not row["Fuente"].strip()
            ):
                raise PortfolioError(
                    "Cada valuación de reporto requiere referencia, moneda, fuente y fecha del cierre."
                )
            key = (row["Referencia"], row["Moneda"])
            if key in values:
                raise PortfolioError("Hay valuaciones duplicadas para un reporto.")
            value = decimal(row["Valor"])
            if value <= 0:
                raise PortfolioError("La valuación de un reporto vigente debe ser positiva.")
            values[key] = value
        if not values:
            raise PortfolioError("La valuación de reportos no contiene filas.")
        return values
    except (UnicodeError, csv.Error, ValueError) as exc:
        if isinstance(exc, PortfolioError):
            raise
        raise PortfolioError("No se pudo leer la valuación de reportos.") from exc


def value_book(
    book: dict, quotes: dict, fx: dict, *, base="MXN", raw_prices_confirmed=False, repo_values=None,
) -> dict:
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
    repos = book.get("repos", {})
    repo_values = {} if repo_values is None else repo_values
    if set(repo_values) != set(repos):
        raise PortfolioError("Falta la valuación documentada de cada reporto vigente o sobran referencias.")
    for ref, currency in repos:
        value = decimal(repo_values[(ref, currency)])
        if value <= 0:
            raise PortfolioError("La valuación de un reporto vigente debe ser positiva.")
        # Total carrying value at the cutoff, including documented accrued interest.
        # Neither collateral prices nor principal alone establish this value.
        values.append((f"Reporto · {ref}", currency, value))
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
