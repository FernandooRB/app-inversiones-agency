"""Strict import of one dated, contractual broker-cost profile."""

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


@dataclass(frozen=True)
class BrokerTariffProfile:
    intermediary: str
    product: str
    market: str
    consulted_on: date
    source: str
    assumptions: ImplementationCostAssumptions


def _clean_text(value, field: str, maximum: int) -> str:
    text = str(value).strip()
    if (
        not text or text.lower() == "nan" or len(text) > maximum
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError(f"{field} debe tener entre 1 y {maximum} caracteres válidos.")
    return text


def read_broker_tariff_csv(contents: bytes) -> BrokerTariffProfile:
    """Read a single all-in cost profile without inferring missing contractual terms."""
    if not contents:
        raise PortfolioError("El archivo del tarifario está vacío.")
    if len(contents) > 100_000:
        raise PortfolioError("El archivo del tarifario debe ocupar menos de 100 KB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV del tarifario.") from exc
    if tuple(frame.columns) != TARIFF_COLUMNS:
        raise PortfolioError(
            "El tarifario debe contener exactamente las columnas de la plantilla y en el mismo orden."
        )
    if len(frame) != 1:
        raise PortfolioError("El tarifario debe contener exactamente un perfil contractual.")
    row = frame.iloc[0]
    raw_date = str(row["FechaConsulta"]).strip()
    if not pd.Series([raw_date]).str.fullmatch(r"\d{4}-\d{2}-\d{2}").iloc[0]:
        raise PortfolioError("FechaConsulta debe usar YYYY-MM-DD.")
    consulted = pd.to_datetime(raw_date, format="%Y-%m-%d", errors="coerce")
    if pd.isna(consulted) or consulted.date() > date.today():
        raise PortfolioError("FechaConsulta debe ser una fecha válida que no esté en el futuro.")

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
        consulted.date(),
        _clean_text(row["Fuente"], "Fuente", 300),
        assumptions,
    )
