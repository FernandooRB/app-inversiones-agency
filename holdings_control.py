"""Non-persistent control total for an imported MXN holdings snapshot."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO

import pandas as pd

from holdings import CurrentHoldings, read_current_holdings_csv
from portfolio_core import PortfolioError

MAX_CONTROL_CSV_BYTES = 100_000
CONTROL_COLUMNS = ("FechaCorte", "TotalMXN", "Fuente")
MONEY_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,2})?$")
SIGNED_MONEY_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,2})?$")
COVERAGE_COLUMNS = (
    "FechaCorte",
    "ValorCarteraAnalizadaMXN",
    "EfectivoFueraAnalisisMXN",
    "PendienteLiquidacionMXN",
    "OtrosFueraAnalisisMXN",
    "TotalCuentaMXN",
    "Fuente",
)
CENT = Decimal("0.01")


@dataclass(frozen=True)
class HoldingsTotalControl:
    as_of: date
    statement_total: Decimal
    calculated_total: Decimal
    source: str
    fingerprint: str


@dataclass(frozen=True)
class HoldingsDetailControl:
    as_of: date
    asset_count: int
    fingerprint: str


@dataclass(frozen=True)
class HoldingsCoverageControl:
    as_of: date
    analyzed_value: Decimal
    outside_cash: Decimal
    pending_settlement: Decimal
    other_outside: Decimal
    account_total: Decimal
    source: str
    fingerprint: str

    @property
    def outside_analysis_total(self) -> Decimal:
        return self.outside_cash + self.pending_settlement + self.other_outside


def _parse_money(value: str, field: str, *, signed: bool = False) -> Decimal:
    raw = value.strip()
    pattern = SIGNED_MONEY_PATTERN if signed else MONEY_PATTERN
    if not pattern.fullmatch(raw):
        qualifier = "con signo opcional, " if signed else ""
        raise PortfolioError(
            f"{field} debe usar un importe {qualifier}sin separadores y con hasta dos decimales."
        )
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation as exc:
        raise PortfolioError(f"{field} no es un importe válido.") from exc


def read_holdings_coverage_csv(
    contents: bytes, holdings: CurrentHoldings
) -> HoldingsCoverageControl:
    """Reconcile analyzed holdings and excluded account components to the account total."""
    if not contents:
        raise PortfolioError("El resumen de cobertura de la cuenta está vacío.")
    if len(contents) > MAX_CONTROL_CSV_BYTES:
        raise PortfolioError("El resumen de cobertura debe ocupar menos de 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el resumen de cobertura de la cuenta.") from exc
    if tuple(frame.columns) != COVERAGE_COLUMNS or len(frame) != 1:
        raise PortfolioError(
            "El resumen de cobertura requiere una fila y las columnas exactas de la plantilla."
        )
    row = frame.iloc[0]
    raw_date = row["FechaCorte"].strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        raise PortfolioError("FechaCorte del resumen debe usar YYYY-MM-DD.")
    try:
        as_of = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise PortfolioError("FechaCorte del resumen debe usar una fecha YYYY-MM-DD válida.") from exc
    if as_of != holdings.as_of.date():
        raise PortfolioError("La fecha del resumen de cobertura no coincide con la cartera actual.")
    analyzed = _parse_money(row["ValorCarteraAnalizadaMXN"], "ValorCarteraAnalizadaMXN")
    cash = _parse_money(row["EfectivoFueraAnalisisMXN"], "EfectivoFueraAnalisisMXN")
    pending = _parse_money(
        row["PendienteLiquidacionMXN"], "PendienteLiquidacionMXN", signed=True
    )
    other = _parse_money(row["OtrosFueraAnalisisMXN"], "OtrosFueraAnalisisMXN", signed=True)
    account_total = _parse_money(row["TotalCuentaMXN"], "TotalCuentaMXN")
    if account_total <= 0:
        raise PortfolioError("TotalCuentaMXN debe ser positivo.")
    try:
        imported_total = sum(
            (Decimal(str(value)) for value in holdings.values), Decimal(0)
        ).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise PortfolioError("La cartera importada no se puede conciliar al centavo.") from exc
    if analyzed != imported_total:
        raise PortfolioError(
            "ValorCarteraAnalizadaMXN no coincide con la suma de posiciones importadas: "
            f"{analyzed:.2f} frente a {imported_total:.2f} MXN."
        )
    calculated_total = analyzed + cash + pending + other
    if account_total != calculated_total:
        raise PortfolioError(
            "TotalCuentaMXN no coincide con cartera, efectivo y otras partidas: "
            f"{account_total:.2f} frente a {calculated_total:.2f} MXN."
        )
    source = row["Fuente"].strip()
    if (
        not source or len(source) > 120 or source[0] in "=+-@"
        or any(ord(char) < 32 for char in source)
    ):
        raise PortfolioError("Fuente del resumen debe ser texto válido sin fórmulas CSV.")
    return HoldingsCoverageControl(
        as_of, analyzed, cash, pending, other, account_total, source,
        sha256(contents).hexdigest(),
    )


def compare_holdings_detail_csv(
    contents: bytes,
    primary: CurrentHoldings,
    primary_contents: bytes,
) -> HoldingsDetailControl:
    """Check every position against a separately prepared statement transcription."""
    if contents == primary_contents:
        raise PortfolioError(
            "El detalle de referencia es idéntico al archivo principal; "
            "prepara el control por separado desde el estado de cuenta."
        )
    reference = read_current_holdings_csv(contents, tuple(primary.values.index))
    if reference.as_of != primary.as_of:
        raise PortfolioError("La fecha del detalle de referencia no coincide con la cartera actual.")
    try:
        mismatched = [
            asset
            for asset in primary.values.index
            if Decimal(str(primary.values[asset])).quantize(CENT, rounding=ROUND_HALF_UP)
            != Decimal(str(reference.values[asset])).quantize(CENT, rounding=ROUND_HALF_UP)
        ]
    except InvalidOperation as exc:
        raise PortfolioError("El detalle de posiciones no se puede conciliar al centavo.") from exc
    if mismatched:
        assets = ", ".join(mismatched[:8]) + ("…" if len(mismatched) > 8 else "")
        raise PortfolioError(
            "El detalle del estado de cuenta difiere por instrumento: " + assets + "."
        )
    return HoldingsDetailControl(
        primary.as_of.date(), len(primary.values), sha256(contents).hexdigest()
    )


def read_holdings_control_csv(contents: bytes, holdings: CurrentHoldings) -> HoldingsTotalControl:
    """Compare a separately entered analyzed subtotal with the imported position sum."""
    if not contents:
        raise PortfolioError("El control de subtotal de posiciones está vacío.")
    if len(contents) > MAX_CONTROL_CSV_BYTES:
        raise PortfolioError("El control de subtotal debe ocupar menos de 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el control de subtotal de posiciones.") from exc
    if tuple(frame.columns) != CONTROL_COLUMNS or len(frame) != 1:
        raise PortfolioError("El control de subtotal requiere una fila con FechaCorte,TotalMXN,Fuente.")
    row = frame.iloc[0]
    raw_date = row["FechaCorte"].strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        raise PortfolioError("FechaCorte del control debe usar YYYY-MM-DD.")
    try:
        as_of = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise PortfolioError("FechaCorte del control no es válida.") from exc
    if as_of != holdings.as_of.date():
        raise PortfolioError("La fecha del control no coincide con la cartera actual.")

    raw_total = row["TotalMXN"].strip()
    if not MONEY_PATTERN.fullmatch(raw_total):
        raise PortfolioError("TotalMXN debe ser positivo y usar hasta dos decimales, sin separadores.")
    try:
        statement_total = Decimal(raw_total)
    except InvalidOperation as exc:
        raise PortfolioError("TotalMXN no es válido.") from exc
    if statement_total <= 0:
        raise PortfolioError("TotalMXN debe ser positivo.")
    try:
        calculated_total = sum(
            (Decimal(str(value)) for value in holdings.values), Decimal(0)
        ).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise PortfolioError("La suma de posiciones no se puede conciliar al centavo.") from exc
    if statement_total != calculated_total:
        raise PortfolioError(
            "El subtotal declarado no coincide con la suma de posiciones: "
            f"{statement_total:.2f} frente a {calculated_total:.2f} MXN."
        )
    source = row["Fuente"].strip()
    if (
        not source or len(source) > 120 or source[0] in "=+-@"
        or any(ord(char) < 32 for char in source)
    ):
        raise PortfolioError("Fuente del control debe ser texto válido sin fórmulas CSV.")
    return HoldingsTotalControl(
        as_of, statement_total, calculated_total, source, sha256(contents).hexdigest()
    )
