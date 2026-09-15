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
    if len(contents) > 5_000_000:
        raise PortfolioError("El archivo CETES debe ocupar menos de 5 MB.")
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


def merge_cetes_index(market_prices: pd.DataFrame, cetes_index: pd.Series) -> pd.DataFrame:
    """Align a prepared CETES index without hiding internal observation gaps."""
    if market_prices.empty or cetes_index.empty:
        raise PortfolioError("Las series de mercado y CETES no pueden estar vacías.")
    if not isinstance(market_prices.index, pd.DatetimeIndex) or not isinstance(
        cetes_index.index, pd.DatetimeIndex
    ):
        raise PortfolioError("Las series de mercado y CETES requieren fechas.")
    if (
        market_prices.index.has_duplicates
        or cetes_index.index.has_duplicates
        or not market_prices.index.is_monotonic_increasing
        or not cetes_index.index.is_monotonic_increasing
    ):
        raise PortfolioError("Las series mixtas requieren fechas únicas y ordenadas.")
    if cetes_index.name is None or not str(cetes_index.name).strip():
        raise PortfolioError("La serie CETES requiere un nombre.")
    if cetes_index.name in market_prices.columns:
        raise PortfolioError("El nombre de CETES coincide con otro activo del análisis.")
    start = max(market_prices.index.min(), cetes_index.index.min())
    end = min(market_prices.index.max(), cetes_index.index.max())
    if start > end:
        raise PortfolioError("La serie CETES no coincide con el periodo de los demás activos.")
    market_window = market_prices.loc[start:end]
    missing = market_window.index.difference(cetes_index.index)
    if len(missing):
        raise PortfolioError(
            f"La serie CETES omite {len(missing)} fecha(s) de mercado dentro del periodo común. "
            "Corrige el archivo; no se rellenan huecos."
        )
    combined = market_window.join(cetes_index.rename(str(cetes_index.name)), how="left")
    if len(combined) < 60:
        raise PortfolioError(
            f"Solo hay {len(combined)} observaciones mixtas; se requieren al menos 60."
        )
    if not np.isfinite(combined.to_numpy()).all() or (combined <= 0).any().any():
        raise PortfolioError("Las series mixtas deben contener valores positivos y finitos.")
    return combined
