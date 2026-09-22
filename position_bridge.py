"""Non-persistent reconciliation of instrument quantities to a closing statement."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO

import pandas as pd

from holdings import CurrentHoldings
from holdings_control import parse_control_money
from portfolio_core import PortfolioError

MAX_POSITION_BRIDGE_BYTES = 100_000
MAX_POSITION_BRIDGE_ROWS = 1_000
LEDGER_COLUMNS = ("Fecha", "Instrumento", "Unidad", "Tipo", "Cantidad")
CLOSING_COLUMNS = ("FechaCorte", "Instrumento", "Unidad", "CantidadFinal", "ValorMXN")
QUANTITY_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12})?$")
UNIT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,23}$")
INFLOWS = frozenset({"COMPRA", "ENTRADA", "AJUSTE_POSITIVO"})
OUTFLOWS = frozenset({"VENTA", "SALIDA", "AJUSTE_NEGATIVO"})
MOVEMENTS = INFLOWS | OUTFLOWS
CENT = Decimal("0.01")


@dataclass(frozen=True)
class PositionBridgeLine:
    asset: str
    unit: str
    opening: Decimal
    net_movements: Decimal
    closing: Decimal
    closing_value: Decimal


@dataclass(frozen=True)
class PositionBridge:
    start_date: date
    end_date: date
    lines: tuple[PositionBridgeLine, ...]
    movement_count: int
    adjustment_count: int
    ledger_source: str
    ledger_fingerprint: str
    closing_source: str
    closing_fingerprint: str


def _source(value: str, label: str) -> str:
    source = value.strip()
    if (not source or len(source) > 120 or source[0] in "=+-@"
            or any(ord(char) < 32 for char in source)):
        raise PortfolioError(f"Declara una fuente válida de {label}, sin fórmulas CSV.")
    return source


def _csv(contents: bytes, columns: tuple[str, ...], label: str) -> pd.DataFrame:
    if not contents or len(contents) > MAX_POSITION_BRIDGE_BYTES:
        raise PortfolioError(f"El {label} debe ocupar entre 1 byte y 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError(f"No se pudo leer el {label}.") from exc
    if tuple(frame.columns) != columns or not 1 <= len(frame) <= MAX_POSITION_BRIDGE_ROWS:
        raise PortfolioError(f"El {label} requiere 1 a 1000 filas y las columnas exactas de la plantilla.")
    return frame


def _date(value: str, label: str) -> date:
    raw = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise PortfolioError(f"{label} debe usar YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PortfolioError(f"{label} no es una fecha válida.") from exc


def _quantity(value: str, label: str) -> Decimal:
    raw = value.strip()
    if not QUANTITY_PATTERN.fullmatch(raw):
        raise PortfolioError(f"{label} requiere cantidad no negativa con hasta 12 decimales.")
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise PortfolioError(f"{label} no es una cantidad válida.") from exc


def _unit(value: str) -> str:
    unit = value.strip()
    if not UNIT_PATTERN.fullmatch(unit):
        raise PortfolioError("Unidad debe ser una clave en mayúsculas de 2 a 24 caracteres.")
    return unit


def read_position_bridge_csv(
    ledger_contents: bytes,
    closing_contents: bytes,
    holdings: CurrentHoldings,
    ledger_source: str,
    closing_source: str,
) -> PositionBridge:
    """Check opening quantities plus movements against an independent closing snapshot.

    The closing snapshot also ties each instrument's MXN value to imported holdings.
    This checks declared files, not transaction completeness or corporate actions.
    """
    ledger_source = _source(ledger_source, "los movimientos de títulos")
    closing_source = _source(closing_source, "las posiciones finales")
    ledger = _csv(ledger_contents, LEDGER_COLUMNS, "registro de movimientos de títulos")
    closing = _csv(closing_contents, CLOSING_COLUMNS, "resumen de posiciones finales")
    assets = tuple(str(asset) for asset in holdings.values.index)
    expected = set(assets)
    if len(closing) != len(assets) or set(closing["Instrumento"].str.strip().str.upper()) != expected:
        raise PortfolioError("Las posiciones finales deben incluir exactamente una fila por instrumento.")
    if closing["Instrumento"].str.strip().str.upper().duplicated().any():
        raise PortfolioError("Las posiciones finales contienen instrumentos duplicados.")
    cutoff = holdings.as_of.date()
    if any(_date(value, "FechaCorte") != cutoff for value in closing["FechaCorte"]):
        raise PortfolioError("FechaCorte de las posiciones finales no coincide con la cartera actual.")
    if len(ledger) < len(assets):
        raise PortfolioError("Falta el saldo inicial de algún instrumento.")
    kinds = ledger["Tipo"].str.strip().tolist()
    if kinds[:len(assets)] != ["SALDO_INICIAL"] * len(assets):
        raise PortfolioError("Las primeras filas deben ser los saldos iniciales de todos los instrumentos.")
    if any(kind not in MOVEMENTS for kind in kinds[len(assets):]):
        raise PortfolioError("El registro contiene un movimiento desconocido o un saldo inicial duplicado.")
    ledger_assets = ledger["Instrumento"].str.strip().str.upper().tolist()
    if set(ledger_assets[:len(assets)]) != expected or len(set(ledger_assets[:len(assets)])) != len(assets):
        raise PortfolioError("Los saldos iniciales deben incluir exactamente una fila por instrumento.")
    if any(asset not in expected for asset in ledger_assets):
        raise PortfolioError("El registro contiene instrumentos fuera de la cartera actual.")
    dates = [_date(value, "Fecha") for value in ledger["Fecha"]]
    start_date = dates[0]
    if any(value != start_date for value in dates[:len(assets)]):
        raise PortfolioError("Todos los saldos iniciales deben tener la misma fecha.")
    if start_date > cutoff or any(left > right for left, right in zip(dates, dates[1:], strict=False)):
        raise PortfolioError("Las fechas de movimientos deben estar ordenadas y dentro del periodo.")
    if any(value > cutoff for value in dates):
        raise PortfolioError("Hay movimientos posteriores a la fecha de corte.")
    quantities = [_quantity(value, "Cantidad") for value in ledger["Cantidad"]]
    if any(value <= 0 for value in quantities[len(assets):]):
        raise PortfolioError("Cada movimiento de títulos debe tener cantidad positiva.")
    ledger_units = [_unit(value) for value in ledger["Unidad"]]
    balances = dict(zip(ledger_assets[:len(assets)], quantities[:len(assets)], strict=True))
    openings = balances.copy()
    units = dict(zip(ledger_assets[:len(assets)], ledger_units[:len(assets)], strict=True))
    for asset, unit, kind, quantity in zip(
        ledger_assets[len(assets):], ledger_units[len(assets):], kinds[len(assets):],
        quantities[len(assets):], strict=True,
    ):
        if unit != units[asset]:
            raise PortfolioError(f"Unidad inconsistente en movimientos de {asset}.")
        balances[asset] += quantity if kind in INFLOWS else -quantity
        if balances[asset] < 0:
            raise PortfolioError(f"Los movimientos de {asset} producen cantidad negativa.")
    closing_rows = {
        row["Instrumento"].strip().upper(): row for _, row in closing.iterrows()
    }
    lines = []
    for asset in assets:
        row = closing_rows[asset]
        if _unit(row["Unidad"]) != units[asset]:
            raise PortfolioError(f"Unidad de {asset} no coincide entre movimientos y cierre.")
        final = _quantity(row["CantidadFinal"], "CantidadFinal")
        if final != balances[asset]:
            raise PortfolioError(
                f"CantidadFinal de {asset} no coincide con saldo inicial y movimientos: "
                f"{final} frente a {balances[asset]}."
            )
        value = parse_control_money(row["ValorMXN"], "ValorMXN")
        try:
            imported = Decimal(str(holdings.values[asset])).quantize(CENT, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise PortfolioError("La cartera importada no se puede conciliar al centavo.") from exc
        if value != imported:
            raise PortfolioError(f"ValorMXN de {asset} no coincide con la cartera actual.")
        lines.append(PositionBridgeLine(asset, units[asset], openings[asset],
                                        final - openings[asset], final, value))
    return PositionBridge(
        start_date, cutoff, tuple(lines), len(ledger) - len(assets),
        sum(kind.startswith("AJUSTE_") for kind in kinds[len(assets):]),
        ledger_source, sha256(ledger_contents).hexdigest(),
        closing_source, sha256(closing_contents).hexdigest(),
    )
