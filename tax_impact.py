"""Auditable tax-basis import and illustrative reserve for portfolio sales."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO

import numpy as np
import pandas as pd

from implementation_costs import ImplementationCostEstimate
from portfolio_core import PortfolioError

MAX_TAX_BASIS_BYTES = 2_000_000
TAX_BASIS_COLUMNS = (
    "FechaCorte",
    "Instrumento",
    "CostoFiscalActualizadoMXN",
    "TratamientoFiscal",
    "TasaEscenarioPct",
    "Fuente",
)
ARTICLE_129 = "PF_ACCIONES_BOLSA_ART129"
DECLARED_RATE = "ESCENARIO_TASA_DECLARADA"
NOT_ESTIMATED = "NO_ESTIMADO"
ALLOWED_TREATMENTS = {ARTICLE_129, DECLARED_RATE, NOT_ESTIMATED}


@dataclass(frozen=True)
class TaxBasisProfile:
    as_of: pd.Timestamp
    cost_basis: pd.Series
    treatments: pd.Series
    rates: pd.Series
    sources: pd.Series
    fingerprint: str


@dataclass(frozen=True)
class TaxReserveEstimate:
    alternative_name: str
    detail: pd.DataFrame
    sell_notional: float
    estimated_gross_gain: float
    estimated_loss: float
    estimated_tax_reserve: float
    unestimated_sell_notional: float


def _clean_text(value, field: str, maximum: int) -> str:
    text = str(value).strip()
    if (
        not text or text.lower() == "nan" or len(text) > maximum
        or any(ord(char) < 32 for char in text)
    ):
        raise PortfolioError(f"{field} debe tener entre 1 y {maximum} caracteres válidos.")
    return text


def read_tax_basis_csv(
    contents: bytes,
    expected_assets: tuple[str, ...],
    expected_date: date | pd.Timestamp,
) -> TaxBasisProfile:
    """Read updated tax bases for exactly the assets in the current portfolio."""
    if not contents:
        raise PortfolioError("El archivo de bases fiscales está vacío.")
    if len(contents) > MAX_TAX_BASIS_BYTES:
        raise PortfolioError("El archivo de bases fiscales debe ocupar menos de 2 MB.")
    if not expected_assets or len(set(expected_assets)) != len(expected_assets):
        raise PortfolioError("El universo esperado para las bases fiscales es inválido.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de bases fiscales.") from exc
    if tuple(frame.columns) != TAX_BASIS_COLUMNS:
        raise PortfolioError(
            "El archivo fiscal debe contener exactamente las columnas de la plantilla "
            "y en el mismo orden."
        )
    if frame.empty:
        raise PortfolioError("El archivo fiscal no contiene instrumentos.")

    raw_dates = frame["FechaCorte"].astype(str).str.strip()
    if not raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise PortfolioError("FechaCorte fiscal debe usar YYYY-MM-DD.")
    dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if dates.isna().any() or dates.nunique() != 1:
        raise PortfolioError("Las bases fiscales deben tener una sola fecha de corte válida.")
    as_of = pd.Timestamp(dates.iloc[0]).normalize()
    required_date = pd.Timestamp(expected_date).normalize()
    if as_of != required_date:
        raise PortfolioError("La fecha fiscal debe coincidir con la fecha de la cartera actual.")
    if as_of > pd.Timestamp.now().normalize():
        raise PortfolioError("La fecha fiscal no puede estar en el futuro.")

    assets = frame["Instrumento"].astype(str).str.strip().str.upper()
    if assets.eq("").any() or assets.duplicated().any():
        raise PortfolioError("Cada instrumento debe aparecer una sola vez en el archivo fiscal.")
    expected = tuple(str(asset).strip().upper() for asset in expected_assets)
    missing = sorted(set(expected) - set(assets))
    extra = sorted(set(assets) - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append("faltan: " + ", ".join(missing))
        if extra:
            details.append("sobran: " + ", ".join(extra))
        raise PortfolioError("Las bases fiscales no coinciden con la cartera; " + "; ".join(details) + ".")

    costs = pd.to_numeric(frame["CostoFiscalActualizadoMXN"], errors="coerce")
    if costs.isna().any() or not np.isfinite(costs).all() or (costs < 0).any():
        raise PortfolioError("CostoFiscalActualizadoMXN debe ser finito y no negativo.")
    treatments = frame["TratamientoFiscal"].astype(str).str.strip().str.upper()
    invalid = sorted(set(treatments) - ALLOWED_TREATMENTS)
    if invalid:
        raise PortfolioError("TratamientoFiscal no reconocido: " + ", ".join(invalid) + ".")
    raw_rates = frame["TasaEscenarioPct"]
    rates = pd.to_numeric(raw_rates, errors="coerce")
    estimated = treatments.ne(NOT_ESTIMATED)
    if rates[estimated].isna().any() or not np.isfinite(rates[estimated]).all():
        raise PortfolioError("Cada tratamiento estimado requiere una tasa finita.")
    if ((rates[estimated] < 0) | (rates[estimated] > 100)).any():
        raise PortfolioError("TasaEscenarioPct debe estar entre 0 y 100.")
    unexpected_unestimated_rate = raw_rates[~estimated].map(
        lambda value: not (pd.isna(value) or str(value).strip() == "")
    )
    if unexpected_unestimated_rate.any():
        raise PortfolioError("TasaEscenarioPct debe quedar vacía cuando el tratamiento es NO_ESTIMADO.")
    article_rates = rates[treatments.eq(ARTICLE_129)]
    if not np.allclose(article_rates.to_numpy(dtype=float), 10.0, atol=1e-12, rtol=0):
        raise PortfolioError("PF_ACCIONES_BOLSA_ART129 requiere la tasa vigente declarada de 10%.")

    sources = frame["Fuente"].map(lambda value: _clean_text(value, "Fuente", 300))
    index = pd.Index(assets, name="Instrumento")
    return TaxBasisProfile(
        as_of=as_of,
        cost_basis=pd.Series(costs.to_numpy(dtype=float), index=index).reindex(expected),
        treatments=pd.Series(treatments.to_numpy(), index=index).reindex(expected),
        rates=pd.Series((rates / 100).to_numpy(dtype=float), index=index).reindex(expected),
        sources=pd.Series(sources.to_numpy(), index=index).reindex(expected),
        fingerprint=sha256(contents).hexdigest(),
    )


def estimate_tax_reserve(
    implementation: ImplementationCostEstimate,
    current_values: pd.Series,
    profile: TaxBasisProfile,
) -> TaxReserveEstimate:
    """Estimate a review reserve on sales without claiming to calculate annual tax due."""
    expected = tuple(str(asset).strip().upper() for asset in current_values.index)
    if (
        not expected or len(set(expected)) != len(expected)
        or tuple(profile.cost_basis.index) != expected
    ):
        raise PortfolioError("La base fiscal no está ordenada como la cartera actual.")
    values = pd.to_numeric(current_values.reindex(expected), errors="coerce")
    if values.isna().any() or not np.isfinite(values).all() or (values < 0).any():
        raise PortfolioError("Los valores actuales para la reserva fiscal son inválidos.")

    rows = []
    sales = implementation.detail[
        implementation.detail["Operación"].eq("Venta")
    ]
    for order in sales.itertuples(index=False):
        asset = str(order.Activo).strip().upper()
        current_value = float(values.loc[asset])
        notional = float(order.Nominal)
        if current_value <= 0 or notional > current_value + max(current_value, 1.0) * 1e-8:
            raise PortfolioError("Una venta fiscal estimada excede el valor actual del instrumento.")
        proportion = min(notional / current_value, 1.0)
        allocated_basis = float(profile.cost_basis.loc[asset]) * proportion
        net_proceeds = max(notional - float(order.Comisión), 0.0)
        gain = max(net_proceeds - allocated_basis, 0.0)
        loss = max(allocated_basis - net_proceeds, 0.0)
        treatment = str(profile.treatments.loc[asset])
        rate = float(profile.rates.loc[asset])
        reserve = np.nan if treatment == NOT_ESTIMATED else gain * rate
        rows.append({
            "Activo": asset,
            "Venta bruta": notional,
            "Comisión de venta": float(order.Comisión),
            "Venta neta estimada": net_proceeds,
            "Costo fiscal asignado": allocated_basis,
            "Ganancia bruta estimada": gain,
            "Pérdida estimada": loss,
            "Tratamiento fiscal": treatment,
            "Tasa escenario": rate,
            "Reserva fiscal estimada": reserve,
            "Fuente": str(profile.sources.loc[asset]),
        })
    detail = pd.DataFrame(rows, columns=[
        "Activo", "Venta bruta", "Comisión de venta", "Venta neta estimada",
        "Costo fiscal asignado", "Ganancia bruta estimada", "Pérdida estimada",
        "Tratamiento fiscal", "Tasa escenario", "Reserva fiscal estimada", "Fuente",
    ])
    if detail.empty:
        gross_gain = loss = reserve = uncovered = 0.0
    else:
        gross_gain = float(detail["Ganancia bruta estimada"].sum())
        loss = float(detail["Pérdida estimada"].sum())
        reserve = float(detail["Reserva fiscal estimada"].sum(skipna=True))
        uncovered = float(
            detail.loc[detail["Tratamiento fiscal"].eq(NOT_ESTIMATED), "Venta bruta"].sum()
        )
    return TaxReserveEstimate(
        implementation.alternative_name,
        detail,
        implementation.sell_notional,
        gross_gain,
        loss,
        reserve,
        uncovered,
    )
