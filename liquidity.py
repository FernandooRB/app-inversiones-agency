"""Auditable accrual indexes for identified MXN liquidity vehicles."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd

from fixed_income import merge_prepared_index
from portfolio_core import PortfolioError

SUPPORTED_CONVENTIONS = {"nominal_360", "efectiva_365"}
SUPPORTED_TREATMENTS = {"BRUTA", "NETA"}


@dataclass(frozen=True)
class LiquidityAccrual:
    index: pd.Series
    annual_rates: pd.Series
    calendar_days: pd.Series
    vehicle: str
    convention: str
    treatment: str

    @property
    def returns(self) -> pd.Series:
        return self.index.pct_change().dropna().rename(self.index.name)


def prepare_liquidity_accrual(
    observations: pd.DataFrame,
    *,
    rate_column: str,
    vehicle: str,
    convention: str,
    treatment: str,
    name: str = "LIQUIDEZ",
) -> LiquidityAccrual:
    """Accrue a declared annual rate over calendar days without using future rates.

    The rate observed at t-1 applies until t. ``nominal_360`` uses simple
    prorating and ``efectiva_365`` uses exponential compounding.
    """
    if rate_column not in observations:
        raise PortfolioError("El archivo de liquidez no contiene la tasa anual requerida.")
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise PortfolioError("El índice de liquidez debe contener fechas.")
    if observations.index.isna().any() or observations.index.tz is not None:
        raise PortfolioError("Las fechas de liquidez deben ser válidas y no tener zona horaria.")
    frame = observations[[rate_column]].copy().sort_index()
    if frame.index.has_duplicates:
        raise PortfolioError("La serie de liquidez contiene fechas duplicadas.")
    rates_percent = pd.to_numeric(frame[rate_column], errors="coerce")
    if rates_percent.isna().any() or not np.isfinite(rates_percent).all():
        raise PortfolioError("La serie de liquidez contiene tasas faltantes o no numéricas.")
    if len(frame) < 3:
        raise PortfolioError("Se requieren al menos tres observaciones válidas de liquidez.")
    if (rates_percent <= -100).any() or (rates_percent > 500).any():
        raise PortfolioError("La tasa anual de liquidez debe ser mayor a -100% y no exceder 500%.")

    if vehicle is None or pd.isna(vehicle):
        raise PortfolioError("El vehículo de liquidez debe tener un identificador válido.")
    vehicle_name = str(vehicle).strip()
    if (
        not vehicle_name or len(vehicle_name) > 120
        or any(ord(char) < 32 for char in vehicle_name)
    ):
        raise PortfolioError("El vehículo de liquidez debe tener un identificador válido.")
    normalized_convention = str(convention).strip().lower()
    if normalized_convention not in SUPPORTED_CONVENTIONS:
        raise PortfolioError("La convención debe ser nominal_360 o efectiva_365.")
    normalized_treatment = str(treatment).strip().upper()
    if normalized_treatment not in SUPPORTED_TREATMENTS:
        raise PortfolioError("El tratamiento de la tasa debe ser BRUTA o NETA.")

    rates = (rates_percent / 100).rename("Tasa anual")
    days = frame.index.to_series().diff().dt.days.fillna(0).astype(int).rename("Días calendario")
    previous_rate = rates.shift(1)
    if normalized_convention == "nominal_360":
        gross = 1 + previous_rate * days / 360
    else:
        gross = (1 + previous_rate) ** (days / 365)
    gross.iloc[0] = 1.0
    if not np.isfinite(gross).all() or (gross <= 0).any():
        raise PortfolioError("La tasa y los intervalos no producen factores de liquidez válidos.")
    index = (100.0 * gross.cumprod()).rename(name)
    return LiquidityAccrual(
        index=index,
        annual_rates=rates,
        calendar_days=days,
        vehicle=vehicle_name,
        convention=normalized_convention,
        treatment=normalized_treatment,
    )


def read_liquidity_rate_csv(
    contents: bytes,
    *,
    date_column: str = "Fecha",
    vehicle_column: str = "Vehiculo",
    rate_column: str = "TasaAnualPct",
    convention_column: str = "Convencion",
    treatment_column: str = "Tratamiento",
    name: str = "LIQUIDEZ",
) -> LiquidityAccrual:
    """Read one identified MXN liquidity vehicle and its declared annual rates."""
    if not contents:
        raise PortfolioError("El archivo de liquidez está vacío.")
    if len(contents) > 5_000_000:
        raise PortfolioError("El archivo de liquidez debe ocupar menos de 5 MB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de liquidez.") from exc
    required = {
        date_column, vehicle_column, rate_column, convention_column, treatment_column,
    }
    if not required.issubset(frame.columns):
        raise PortfolioError("El archivo de liquidez no contiene todas las columnas requeridas.")

    raw_dates = frame.pop(date_column).astype(str).str.strip()
    iso = raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    spanish = raw_dates.str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    if not iso and not spanish:
        raise PortfolioError("Usa fechas únicas YYYY-MM-DD o DD/MM/YYYY en el archivo de liquidez.")
    dates = pd.to_datetime(
        raw_dates, format="%Y-%m-%d" if iso else "%d/%m/%Y", errors="coerce"
    )
    if dates.isna().any():
        raise PortfolioError("El archivo de liquidez contiene fechas inválidas.")

    vehicle = _constant_text(frame.pop(vehicle_column), "un solo vehículo de liquidez")
    convention = _constant_text(frame.pop(convention_column), "una sola convención")
    treatment = _constant_text(frame.pop(treatment_column), "un solo tratamiento de tasa")
    frame.index = pd.DatetimeIndex(dates)
    return prepare_liquidity_accrual(
        frame,
        rate_column=rate_column,
        vehicle=vehicle,
        convention=convention,
        treatment=treatment,
        name=name,
    )


def merge_liquidity_index(market_prices: pd.DataFrame, liquidity_index: pd.Series) -> pd.DataFrame:
    """Align a prepared liquidity index without filling missing market dates."""
    return merge_prepared_index(market_prices, liquidity_index, "liquidez")


def _constant_text(values: pd.Series, requirement: str) -> str:
    if values.empty or values.isna().any():
        raise PortfolioError(f"El archivo debe declarar {requirement}.")
    normalized = values.astype(str).str.strip()
    if normalized.eq("").any() or normalized.nunique() != 1:
        raise PortfolioError(f"El archivo debe declarar {requirement}.")
    return normalized.iloc[0]
