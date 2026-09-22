"""Non-persistent reconciliation of settled MXN cash movements."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import BytesIO

import pandas as pd

from holdings_control import HoldingsCoverageControl, parse_control_money
from portfolio_core import PortfolioError

MAX_CASH_BRIDGE_BYTES = 100_000
MAX_CASH_BRIDGE_ROWS = 1_000
CASH_BRIDGE_COLUMNS = ("Fecha", "Tipo", "ImporteMXN")
INFLOWS = frozenset({"DEPOSITO", "VENTA_LIQUIDADA", "DIVIDENDO_INTERES", "OTRA_ENTRADA"})
OUTFLOWS = frozenset({"RETIRO", "COMPRA_LIQUIDADA", "COMISION_IMPUESTO", "OTRA_SALIDA"})
MOVEMENT_TYPES = INFLOWS | OUTFLOWS


@dataclass(frozen=True)
class CashBridge:
    start_date: date
    end_date: date
    opening_cash: Decimal
    net_movements: Decimal
    closing_cash: Decimal
    movement_count: int
    other_movement_count: int
    source: str
    fingerprint: str


def _read_date(raw: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise PortfolioError("Fecha del puente de efectivo debe usar YYYY-MM-DD.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PortfolioError("Fecha del puente de efectivo no es válida.") from exc


def read_cash_bridge_csv(
    contents: bytes, coverage: HoldingsCoverageControl, source: str
) -> CashBridge:
    """Tie a settled cash ledger to the cash component of account coverage."""
    if not contents:
        raise PortfolioError("El puente de efectivo está vacío.")
    if len(contents) > MAX_CASH_BRIDGE_BYTES:
        raise PortfolioError("El puente de efectivo debe ocupar menos de 100 KB.")
    source = source.strip()
    if (
        not source or len(source) > 120 or source[0] in "=+-@"
        or any(ord(char) < 32 for char in source)
    ):
        raise PortfolioError("Declara una fuente válida del puente de efectivo, sin fórmulas.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el puente de efectivo.") from exc
    if tuple(frame.columns) != CASH_BRIDGE_COLUMNS or not 2 <= len(frame) <= MAX_CASH_BRIDGE_ROWS:
        raise PortfolioError(
            "El puente de efectivo requiere 2 a 1000 filas y exactamente Fecha,Tipo,ImporteMXN."
        )
    kinds = frame["Tipo"].str.strip().tolist()
    if kinds[0] != "SALDO_INICIAL" or kinds[-1] != "SALDO_FINAL":
        raise PortfolioError("El puente debe comenzar con SALDO_INICIAL y terminar con SALDO_FINAL.")
    if any(kind not in MOVEMENT_TYPES for kind in kinds[1:-1]):
        raise PortfolioError("El puente contiene un tipo de movimiento desconocido o un saldo duplicado.")
    dates = [_read_date(value.strip()) for value in frame["Fecha"]]
    if dates[-1] != coverage.as_of:
        raise PortfolioError("La fecha de SALDO_FINAL no coincide con la cobertura de cuenta.")
    if any(left > right for left, right in zip(dates, dates[1:], strict=False)):
        raise PortfolioError("Las fechas del puente deben estar ordenadas y dentro del periodo.")
    amounts = [
        parse_control_money(value, "ImporteMXN") for value in frame["ImporteMXN"]
    ]
    if any(amount <= 0 for amount in amounts[1:-1]):
        raise PortfolioError("Cada movimiento de efectivo debe tener un importe positivo.")
    net = sum(
        (amount if kind in INFLOWS else -amount
         for kind, amount in zip(kinds[1:-1], amounts[1:-1], strict=True)),
        Decimal("0.00"),
    )
    if amounts[0] + net != amounts[-1]:
        raise PortfolioError(
            "El saldo final de efectivo no coincide con el saldo inicial y los movimientos: "
            f"{amounts[-1]:.2f} frente a {amounts[0] + net:.2f} MXN."
        )
    if amounts[-1] != coverage.outside_cash:
        raise PortfolioError(
            "El saldo final de efectivo no coincide con EfectivoFueraAnalisisMXN: "
            f"{amounts[-1]:.2f} frente a {coverage.outside_cash:.2f} MXN."
        )
    return CashBridge(
        dates[0], dates[-1], amounts[0], net, amounts[-1], len(frame) - 2,
        sum(kind in {"OTRA_ENTRADA", "OTRA_SALIDA"} for kind in kinds[1:-1]),
        source, sha256(contents).hexdigest(),
    )
