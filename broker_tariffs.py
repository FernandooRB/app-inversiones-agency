"""Strict import of one broker-cost profile with declared client applicability."""

import re
from dataclasses import dataclass
from datetime import date
from io import BytesIO

import numpy as np
import pandas as pd

from implementation_costs import ImplementationCostAssumptions
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
