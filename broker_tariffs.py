"""Strict import of broker-cost profiles with declared client applicability."""

import csv
import math
import re
from dataclasses import dataclass
from datetime import date
from io import BytesIO, StringIO

import numpy as np
import pandas as pd

from implementation_costs import ImplementationCostAssumptions, OrderCostRule
from portfolio_core import PortfolioError

TARIFF_COLUMNS = (
    "Intermediario",
    "Producto",
    "Mercado",
    "FechaConsulta",
    "ComisionOperacionPct",
    "IVAPctComision",
    "ComisionMinimaMXN",
    "CostoMercadoPbSupuesto",
    "CostoFijoAnualTotalMXN",
    "AdministracionAnualTotalPct",
    "Fuente",
)
DATED_TARIFF_COLUMNS = (
    "Intermediario", "Producto", "Mercado", "TipoTarifa", "VigenteDesde",
    "VigenteHasta", *TARIFF_COLUMNS[3:],
)
TARIFF_KINDS = {"PUBLICA", "CONTRACTUAL", "NEGOCIADA_CLIENTE"}
ORDER_TARIFF_COLUMNS = (
    "Activo", "Intermediario", "Producto", "Mercado", "Operacion", "TipoTarifa",
    "VigenteDesde", "VigenteHasta", "FechaConsulta", "ComisionOperacionPct",
    "IVAPctComision", "ComisionMinimaMXN", "CostoMercadoPbSupuesto", "Fuente",
)


@dataclass(frozen=True)
class BrokerTariffProfile:
    intermediary: str
    product: str
    market: str
    consulted_on: date
    source: str
    assumptions: ImplementationCostAssumptions
    tariff_kind: str = "SIN_ALCANCE"
    valid_from: date | None = None
    valid_until: date | None = None


def _clean_text(value, field: str, maximum: int) -> str:
    text = str(value).strip()
    if (
        not text or text.lower() == "nan" or len(text) > maximum
        or text[0] in "=+-@"
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError(f"{field} debe tener entre 1 y {maximum} caracteres válidos.")
    return text


def _parse_date(value: str, field: str, *, required: bool = True) -> date | None:
    value = value.strip()
    if not value and not required:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PortfolioError(f"{field} debe usar YYYY-MM-DD.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PortfolioError(f"{field} debe ser una fecha válida.") from exc


def read_broker_tariff_csv(contents: bytes, *, as_of: date | None = None) -> BrokerTariffProfile:
    """Read one declared profile and reject a dated rate outside its validity window.

    The legacy template is accepted for old scenarios, but has no proved applicability.
    A declaration of a negotiated rate is not verification of the client's agreement.
    """
    if not contents:
        raise PortfolioError("El archivo del tarifario está vacío.")
    if len(contents) > 100_000:
        raise PortfolioError("El archivo del tarifario debe ocupar menos de 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise PortfolioError("No se pudo leer el CSV del tarifario.") from exc
    columns = tuple(frame.columns)
    if columns not in {TARIFF_COLUMNS, DATED_TARIFF_COLUMNS}:
        raise PortfolioError(
            "El tarifario debe contener exactamente las columnas de la plantilla y en el mismo orden."
        )
    if len(frame) != 1:
        raise PortfolioError("El tarifario debe contener exactamente un perfil contractual.")
    row = frame.iloc[0]
    consulted = _parse_date(row["FechaConsulta"], "FechaConsulta")
    if consulted > date.today():
        raise PortfolioError("FechaConsulta debe ser una fecha válida que no esté en el futuro.")
    tariff_kind = "SIN_ALCANCE"
    valid_from = valid_until = None
    if columns == DATED_TARIFF_COLUMNS:
        tariff_kind = row["TipoTarifa"].strip().upper()
        if tariff_kind not in TARIFF_KINDS:
            raise PortfolioError("TipoTarifa debe ser PUBLICA, CONTRACTUAL o NEGOCIADA_CLIENTE.")
        valid_from = _parse_date(row["VigenteDesde"], "VigenteDesde")
        valid_until = _parse_date(row["VigenteHasta"], "VigenteHasta", required=False)
        if valid_until is not None and valid_until < valid_from:
            raise PortfolioError("VigenteHasta no puede ser anterior a VigenteDesde.")
        analysis_date = as_of or date.today()
        if analysis_date < valid_from or (valid_until is not None and analysis_date > valid_until):
            raise PortfolioError("La tarifa no está vigente en la fecha del análisis.")

    numeric_columns = TARIFF_COLUMNS[4:10]
    numeric = pd.to_numeric(row[list(numeric_columns)], errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise PortfolioError("Los importes y porcentajes del tarifario deben ser números finitos.")
    commission, vat, minimum, market, fixed, management = numeric.to_numpy(dtype=float)
    assumptions = ImplementationCostAssumptions(
        commission_bps=commission * 100,
        market_cost_bps=market,
        vat_rate=vat / 100,
        minimum_commission=minimum,
        annual_fixed_cost=fixed,
        annual_management_rate=management / 100,
    )
    # Reuse the estimator's range validation without manufacturing a trade.
    assumptions.annual_recurring_cost(0)
    return BrokerTariffProfile(
        _clean_text(row["Intermediario"], "Intermediario", 80),
        _clean_text(row["Producto"], "Producto", 80),
        _clean_text(row["Mercado"], "Mercado", 80),
        consulted,
        _clean_text(row["Fuente"], "Fuente", 300),
        assumptions,
        tariff_kind,
        valid_from,
        valid_until,
    )


def _nonnegative_decimal(value: str, field: str) -> float:
    value = value.strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise PortfolioError(f"{field} debe ser un número decimal no negativo.")
    number = float(value)
    if not math.isfinite(number):
        raise PortfolioError(f"{field} debe ser un número decimal finito.")
    return number


def read_order_tariffs_csv(
    contents: bytes, allowed_assets: tuple[str, ...], *, as_of: date | None = None,
) -> tuple[OrderCostRule, ...]:
    """Read dated, explicit transaction terms for a known analysis universe.

    The file identifies a rate, not proof of eligibility for a client or volume tier.
    Every executed direction must still be covered by the cost estimator.
    """
    if not isinstance(contents, bytes) or not contents:
        raise PortfolioError("El archivo de reglas por orden está vacío o no es válido.")
    if len(contents) > 100_000:
        raise PortfolioError("El archivo de reglas por orden debe ocupar menos de 100 KB.")
    if (
        not isinstance(allowed_assets, tuple) or not allowed_assets
        or any(not isinstance(asset, str) or not asset.strip() for asset in allowed_assets)
        or len(set(allowed_assets)) != len(allowed_assets)
    ):
        raise PortfolioError("Declara un universo de activos válido antes de importar reglas.")
    if as_of is not None and type(as_of) is not date:
        raise PortfolioError("La fecha del análisis de costos no es válida.")
    analysis_date = as_of or date.today()
    try:
        records = list(csv.reader(StringIO(contents.decode("utf-8-sig")), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise PortfolioError("No se pudo leer el CSV de reglas por orden.") from exc
    if not records or tuple(records[0]) != ORDER_TARIFF_COLUMNS:
        raise PortfolioError("Las columnas de reglas por orden deben coincidir con la plantilla.")
    if not 1 <= len(records) - 1 <= 200:
        raise PortfolioError("El CSV debe contener entre 1 y 200 reglas por orden.")

    rules = []
    covered_directions = set()
    for row_number, values in enumerate(records[1:], start=2):
        if len(values) != len(ORDER_TARIFF_COLUMNS):
            raise PortfolioError(f"La fila {row_number} no tiene todas las columnas requeridas.")
        row = dict(zip(ORDER_TARIFF_COLUMNS, values, strict=True))
        asset = _clean_text(row["Activo"], "Activo", 80)
        if asset not in allowed_assets:
            raise PortfolioError(f"La fila {row_number} contiene un activo ajeno al análisis.")
        operation_key = row["Operacion"].strip().upper()
        operations = {"COMPRA": "Compra", "VENTA": "Venta", "AMBAS": "Ambas"}
        if operation_key not in operations:
            raise PortfolioError(f"La fila {row_number} requiere COMPRA, VENTA o AMBAS.")
        operation = operations[operation_key]
        tariff_kind = row["TipoTarifa"].strip().upper()
        if tariff_kind not in TARIFF_KINDS:
            raise PortfolioError(f"La fila {row_number} tiene un TipoTarifa inválido.")
        valid_from = _parse_date(row["VigenteDesde"], "VigenteDesde")
        valid_until = _parse_date(row["VigenteHasta"], "VigenteHasta", required=False)
        consulted_on = _parse_date(row["FechaConsulta"], "FechaConsulta")
        if valid_until is not None and valid_until < valid_from:
            raise PortfolioError(f"La fila {row_number} tiene una vigencia invertida.")
        if analysis_date < valid_from or (valid_until is not None and analysis_date > valid_until):
            raise PortfolioError(f"La fila {row_number} no está vigente en el análisis.")
        if consulted_on > date.today() or consulted_on > analysis_date:
            raise PortfolioError(f"La fila {row_number} usa una consulta posterior al análisis.")
        commission = _nonnegative_decimal(row["ComisionOperacionPct"], "ComisionOperacionPct")
        vat = _nonnegative_decimal(row["IVAPctComision"], "IVAPctComision")
        minimum = _nonnegative_decimal(row["ComisionMinimaMXN"], "ComisionMinimaMXN")
        market_bps = _nonnegative_decimal(
            row["CostoMercadoPbSupuesto"], "CostoMercadoPbSupuesto"
        )
        assumptions = ImplementationCostAssumptions(
            commission_bps=commission * 100, vat_rate=vat / 100,
            minimum_commission=minimum, market_cost_bps=market_bps,
        )
        assumptions.annual_recurring_cost(0)
        for side in (("Compra", "Venta") if operation == "Ambas" else (operation,)):
            key = (asset, side)
            if key in covered_directions:
                raise PortfolioError("Hay reglas por orden duplicadas o superpuestas.")
            covered_directions.add(key)
        rules.append(OrderCostRule(
            asset=asset,
            operation=operation,
            intermediary=_clean_text(row["Intermediario"], "Intermediario", 80),
            product=_clean_text(row["Producto"], "Producto", 80),
            market=_clean_text(row["Mercado"], "Mercado", 80),
            valid_from=valid_from,
            valid_until=valid_until,
            consulted_on=consulted_on,
            tariff_kind=tariff_kind,
            source=_clean_text(row["Fuente"], "Fuente", 300),
            assumptions=assumptions,
        ))
    return tuple(rules)
