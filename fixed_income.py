"""Valuation and total-return preparation for Mexican government debt."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError


@dataclass(frozen=True)
class CetesTotalReturn:
    index: pd.Series
    prices: pd.Series
    days_to_maturity: pd.Series
    roll_dates: tuple[pd.Timestamp, ...]
    maturity_dates: tuple[pd.Timestamp, ...]

    @property
    def returns(self) -> pd.Series:
        return self.index.pct_change().dropna().rename(self.index.name)


def cetes_price(
    annual_yield: float | np.ndarray | pd.Series,
    days_to_maturity: float | np.ndarray | pd.Series,
    nominal_value: float = 10.0,
):
    """Value a CETE from its annual simple yield on an actual/360 basis."""
    yields = np.asarray(annual_yield, dtype=float)
    days = np.asarray(days_to_maturity, dtype=float)
    if nominal_value <= 0 or not np.isfinite(nominal_value):
        raise PortfolioError("El valor nominal del CETE debe ser positivo.")
    if np.any(~np.isfinite(yields)) or np.any(yields <= -1):
        raise PortfolioError("La tasa del CETE debe ser finita y mayor que -100%.")
    if np.any(~np.isfinite(days)) or np.any(days < 0):
        raise PortfolioError("El plazo del CETE debe ser finito y no negativo.")
    denominator = 1 + yields * days / 360
    if np.any(denominator <= 0):
        raise PortfolioError("La combinación de tasa y plazo produce un precio inválido.")
    values = nominal_value / denominator
    if np.ndim(annual_yield) == 0 and np.ndim(days_to_maturity) == 0:
        return float(values)
    if isinstance(annual_yield, pd.Series):
        return pd.Series(values, index=annual_yield.index, name="Precio CETE")
    return values


def prepare_cetes_total_return(
    observations: pd.DataFrame,
    *,
    price_column: str,
    term_column: str,
    nominal_value: float = 10.0,
    name: str = "CETES",
) -> CetesTotalReturn:
    """Create an index from Banxico price/term observations.

    A rising remaining term signals a change in the representative issue. If the
    prior issue could have matured between observations, the final factor uses
    the nominal redemption. An earlier reference change is return-neutral on the
    switch date because the two prices refer to different securities.
    """
    if price_column not in observations or term_column not in observations:
        raise PortfolioError("El archivo debe contener las columnas de precio y plazo indicadas.")
    if not isinstance(observations.index, pd.DatetimeIndex):
        raise PortfolioError("El índice de observaciones debe contener fechas.")
    frame = observations[[price_column, term_column]].copy().sort_index()
    if frame.index.has_duplicates:
        raise PortfolioError("La serie CETES contiene fechas duplicadas.")
    frame.columns = ["price", "term"]
    frame = frame.apply(pd.to_numeric, errors="coerce").dropna()
    if len(frame) < 3:
        raise PortfolioError("Se requieren al menos tres observaciones válidas de CETES.")
    if (frame["price"] <= 0).any():
        raise PortfolioError("Los precios de CETES deben ser positivos.")
    if (frame["term"] < 0).any() or not np.allclose(frame["term"], np.round(frame["term"])):
        raise PortfolioError("Los plazos de CETES deben ser días enteros no negativos.")
    if nominal_value <= 0 or not np.isfinite(nominal_value):
        raise PortfolioError("El valor nominal del CETE debe ser positivo.")

    elapsed = frame.index.to_series().diff().dt.days
    previous_term = frame["term"].shift(1)
    roll = frame["term"].gt(previous_term)
    maturity = roll & previous_term.le(elapsed)

    gross = frame["price"].div(frame["price"].shift(1))
    gross.loc[roll] = 1.0
    gross.loc[maturity] = nominal_value / frame["price"].shift(1).loc[maturity]
    gross.iloc[0] = 1.0
    if (~np.isfinite(gross)).any() or (gross <= 0).any():
        raise PortfolioError("No fue posible construir factores válidos para la serie CETES.")

    total_return_index = (100.0 * gross.cumprod()).rename(name)
    return CetesTotalReturn(
        total_return_index,
        frame["price"].rename("Precio"),
        frame["term"].astype(int).rename("Plazo"),
        tuple(frame.index[roll]),
        tuple(frame.index[maturity]),
    )


def read_banxico_cetes_csv(
    contents: bytes,
    *,
    date_column: str,
    price_column: str,
    term_column: str,
    nominal_value: float = 10.0,
    name: str = "CETES",
) -> CetesTotalReturn:
    """Read a user-supplied Banxico export without requiring an API token."""
    if not contents:
        raise PortfolioError("El archivo CETES está vacío.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de CETES.") from exc
    if date_column not in frame:
        raise PortfolioError("El archivo no contiene la columna de fecha indicada.")
    dates = pd.to_datetime(frame.pop(date_column), errors="coerce", dayfirst=True)
    if dates.isna().any():
        raise PortfolioError("El archivo CETES contiene fechas inválidas.")
    frame.index = pd.DatetimeIndex(dates)
    return prepare_cetes_total_return(
        frame,
        price_column=price_column,
        term_column=term_column,
        nominal_value=nominal_value,
        name=name,
    )
