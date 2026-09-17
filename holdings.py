"""Strict, non-persistent import of current portfolio values in MXN."""

from dataclasses import dataclass
from io import BytesIO

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError


@dataclass(frozen=True)
class CurrentHoldings:
    weights: pd.Series
    values: pd.Series
    as_of: pd.Timestamp
    total_value: float


def read_current_holdings_csv(
    contents: bytes,
    expected_assets: tuple[str, ...],
    *,
    date_column: str = "FechaCorte",
    asset_column: str = "Instrumento",
    value_column: str = "ValorMXN",
) -> CurrentHoldings:
    """Read values for exactly the analyzed assets and derive ordered weights."""
    if not contents:
        raise PortfolioError("El archivo de cartera actual está vacío.")
    if len(contents) > 2_000_000:
        raise PortfolioError("El archivo de cartera actual debe ocupar menos de 2 MB.")
    if not expected_assets or len(set(expected_assets)) != len(expected_assets):
        raise PortfolioError("El universo esperado de la cartera actual es inválido.")
    try:
        frame = pd.read_csv(BytesIO(contents))
    except (UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise PortfolioError("No se pudo leer el CSV de cartera actual.") from exc
    required = {date_column, asset_column, value_column}
    if set(frame.columns) != required:
        raise PortfolioError(
            "El archivo de cartera actual debe contener únicamente FechaCorte, "
            "Instrumento y ValorMXN."
        )
    if frame.empty:
        raise PortfolioError("El archivo de cartera actual no contiene posiciones.")

    raw_dates = frame[date_column].astype(str).str.strip()
    if not raw_dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise PortfolioError("FechaCorte debe usar YYYY-MM-DD en todas las posiciones.")
    dates = pd.to_datetime(raw_dates, format="%Y-%m-%d", errors="coerce")
    if dates.isna().any() or dates.nunique() != 1:
        raise PortfolioError("La cartera actual debe tener una sola fecha de corte válida.")
    as_of = pd.Timestamp(dates.iloc[0]).normalize()
    if as_of > pd.Timestamp.now().normalize():
        raise PortfolioError("La fecha de corte de la cartera actual no puede estar en el futuro.")

    assets = frame[asset_column].astype(str).str.strip().str.upper()
    if assets.eq("").any() or assets.duplicated().any():
        raise PortfolioError("Cada instrumento de la cartera actual debe aparecer una sola vez.")
    expected = tuple(str(asset).strip().upper() for asset in expected_assets)
    missing = sorted(set(expected) - set(assets))
    extra = sorted(set(assets) - set(expected))
    if missing or extra:
        details = []
        if missing:
            details.append("faltan: " + ", ".join(missing))
        if extra:
            details.append("sobran: " + ", ".join(extra))
        raise PortfolioError("La cartera actual no coincide con el análisis; " + "; ".join(details) + ".")

    values = pd.to_numeric(frame[value_column], errors="coerce")
    if values.isna().any() or not np.isfinite(values).all() or (values < 0).any():
        raise PortfolioError("ValorMXN debe contener importes finitos y no negativos.")
    by_asset = pd.Series(values.to_numpy(dtype=float), index=assets, name="Valor MXN")
    ordered_values = by_asset.reindex(expected)
    total = float(ordered_values.sum())
    if not np.isfinite(total) or total <= 0:
        raise PortfolioError("El valor total de la cartera actual debe ser positivo.")
    weights = (ordered_values / total).rename("Peso actual")
    return CurrentHoldings(weights, ordered_values, as_of, total)
