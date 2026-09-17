"""Auditable total-return indexes for exact Mexican investment-fund series."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd

from fixed_income import merge_prepared_index
from portfolio_core import PortfolioError


@dataclass(frozen=True)
class FundTotalReturn:
    index: pd.Series
    share_values: pd.Series
    distributions: pd.Series
    fund_id: str
    series_id: str
    currency: str

    @property
    def returns(self) -> pd.Series:
        return self.index.pct_change().dropna().rename(self.index.name)


def prepare_fund_total_return(
    observations: pd.DataFrame,
    *,
    share_value_column: str,
    distribution_column: str,
    fund_id: str,
    series_id: str,
    currency: str,
    name: str = "FONDO_MXN",
) -> FundTotalReturn:
    """Build total return from one exact fund series and cash distributions."""
    required = [share_value_column, distribution_column]
    if any(column not in observations for column in required):
        raise PortfolioError("El archivo del fondo requiere valor de acción y distribución.")
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise PortfolioError("El índice del fondo debe contener fechas.")
    if observations.index.isna().any() or observations.index.tz is not None:
        raise PortfolioError("Las fechas del fondo deben ser válidas y no tener zona horaria.")
    frame = observations[required].copy().sort_index()
    if frame.index.has_duplicates:
        raise PortfolioError("La serie del fondo contiene fechas duplicadas.")
    frame.columns = ["value", "distribution"]
    frame = frame.apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any() or not np.isfinite(frame.to_numpy()).all():
        raise PortfolioError("El fondo contiene valores faltantes, no numéricos o no finitos.")
    if len(frame) < 3:
        raise PortfolioError("Se requieren al menos tres observaciones válidas del fondo.")
    if (frame["value"] <= 0).any():
        raise PortfolioError("El valor de la acción del fondo debe ser positivo.")
    if (frame["distribution"] < 0).any():
        raise PortfolioError("Las distribuciones del fondo no pueden ser negativas.")
    if not np.isclose(frame["distribution"].iloc[0], 0.0):
        raise PortfolioError("La distribución de la primera observación debe ser cero.")

    fund = _identifier(fund_id, "fondo")
    series = _identifier(series_id, "serie")
    normalized_currency = str(currency).strip().upper()
    if normalized_currency != "MXN":
        raise PortfolioError("El adaptador actual sólo admite series de fondos en MXN.")

    gross = (frame["value"] + frame["distribution"]) / frame["value"].shift(1)
    gross.iloc[0] = 1.0
    if not np.isfinite(gross).all() or (gross <= 0).any():
        raise PortfolioError("No fue posible construir factores válidos para el fondo.")
    index = (100.0 * gross.cumprod()).rename(name)
    return FundTotalReturn(
        index=index,
        share_values=frame["value"].rename("Valor de acción"),
        distributions=frame["distribution"].rename("Distribución por acción"),
        fund_id=fund,
        series_id=series,
        currency=normalized_currency,
    )


def read_fund_total_return_csv(
    contents: bytes,
    *,
    date_column: str = "Fecha",
    fund_column: str = "Fondo",
    series_column: str = "Serie",
    currency_column: str = "Moneda",
    share_value_column: str = "ValorAccion",
    distribution_column: str = "Distribucion",
    name: str = "FONDO_MXN",
) -> FundTotalReturn:
    """Read one exact MXN fund series from a reviewable CSV."""
    if not contents:
        raise PortfolioError("El archivo del fondo está vacío.")
    if len(contents) > 5_000_000:
        raise PortfolioError("El archivo del fondo debe ocupar menos de 5 MB.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV del fondo.") from exc
    required = {
        date_column, fund_column, series_column, currency_column,
        share_value_column, distribution_column,
    }
    if not required.issubset(frame.columns):
        raise PortfolioError("El archivo del fondo no contiene todas las columnas requeridas.")
    raw_dates = frame.pop(date_column).astype(str).str.strip()
    iso = raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
    spanish = raw_dates.str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    if not iso and not spanish:
        raise PortfolioError("Usa fechas únicas YYYY-MM-DD o DD/MM/YYYY en el archivo del fondo.")
    dates = pd.to_datetime(
        raw_dates, format="%Y-%m-%d" if iso else "%d/%m/%Y", errors="coerce"
    )
    if dates.isna().any():
        raise PortfolioError("El archivo del fondo contiene fechas inválidas.")
    fund = _constant_text(frame.pop(fund_column), "un solo fondo")
    series = _constant_text(frame.pop(series_column), "una sola serie")
    currency = _constant_text(frame.pop(currency_column), "una sola moneda")
    frame.index = pd.DatetimeIndex(dates)
    return prepare_fund_total_return(
        frame,
        share_value_column=share_value_column,
        distribution_column=distribution_column,
        fund_id=fund,
        series_id=series,
        currency=currency,
        name=name,
    )


def merge_fund_index(market_prices: pd.DataFrame, fund_index: pd.Series) -> pd.DataFrame:
    """Align a prepared fund index without filling missing market dates."""
    return merge_prepared_index(market_prices, fund_index, "fondo")


def _identifier(value, label: str) -> str:
    if value is None or pd.isna(value):
        raise PortfolioError(f"El {label} debe tener un identificador válido.")
    normalized = str(value).strip()
    if not normalized or len(normalized) > 120 or any(ord(char) < 32 for char in normalized):
        raise PortfolioError(f"El {label} debe tener un identificador válido.")
    return normalized


def _constant_text(values: pd.Series, requirement: str) -> str:
    if values.empty or values.isna().any():
        raise PortfolioError(f"El archivo debe declarar {requirement}.")
    normalized = values.astype(str).str.strip()
    if normalized.eq("").any() or normalized.nunique() != 1:
        raise PortfolioError(f"El archivo debe declarar {requirement}.")
    return normalized.iloc[0]
