"""Strict import of team-supplied adjusted-close price series."""

import csv
import io
from datetime import date, datetime

import numpy as np
import pandas as pd

from portfolio_core import (
    MIN_OBSERVATIONS,
    PortfolioError,
    PriceDownload,
    normalize_tickers,
    validate_dates,
)

MAX_PRICE_CSV_BYTES = 5_000_000


def read_adjusted_price_csv(
    contents: bytes, tickers: tuple[str, ...], start_date: date, end_date: date
) -> PriceDownload:
    """Read a wide Fecha/ticker CSV without filling or dropping missing prices.

    The caller is responsible for verifying the provider's adjustment convention,
    licensing and currency metadata. This parser only verifies structure and units.
    """
    requested = tuple(normalize_tickers(tickers))
    validate_dates(start_date, end_date)
    if not contents or len(contents) > MAX_PRICE_CSV_BYTES:
        raise PortfolioError("El CSV de precios debe contener datos y medir como máximo 5 MB.")
    try:
        decoded = contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PortfolioError("El CSV de precios debe estar codificado en UTF-8.") from exc

    reader = csv.reader(io.StringIO(decoded, newline=""))
    try:
        header = [value.strip().upper() for value in next(reader)]
    except StopIteration as exc:
        raise PortfolioError("El CSV de precios está vacío.") from exc
    if (
        not header or header[0] != "FECHA"
        or len(header) != len(requested) + 1
        or len(set(header)) != len(header)
        or set(header[1:]) != set(requested)
    ):
        raise PortfolioError(
            "El CSV debe tener Fecha y exactamente una columna por ticker solicitado."
        )

    dates, values = [], []
    for number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            raise PortfolioError(f"Fila {number} vacía en el CSV de precios.")
        if len(row) != len(header):
            raise PortfolioError(f"La fila {number} tiene un número distinto de columnas.")
        try:
            day = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
            if day.isoformat() != row[0].strip():
                raise ValueError("formato de fecha no canónico")
        except ValueError as exc:
            raise PortfolioError(f"Fecha inválida en fila {number}; usa YYYY-MM-DD.") from exc
        if dates and day <= dates[-1]:
            raise PortfolioError("Las fechas del CSV deben ser únicas y crecientes.")
        try:
            prices = [float(cell.strip()) for cell in row[1:]]
        except ValueError as exc:
            raise PortfolioError(f"Precio faltante o inválido en fila {number}.") from exc
        if not np.isfinite(prices).all() or any(price <= 0 for price in prices):
            raise PortfolioError(f"Los precios de la fila {number} deben ser positivos y finitos.")
        dates.append(day)
        values.append(prices)

    if not dates:
        raise PortfolioError("El CSV de precios no tiene observaciones.")
    table = pd.DataFrame(values, index=pd.DatetimeIndex(dates), columns=header[1:])
    selected = table.loc[pd.Timestamp(start_date):pd.Timestamp(end_date), list(requested)]
    if len(selected) < MIN_OBSERVATIONS:
        raise PortfolioError(
            f"Sólo hay {len(selected)} precios comunes dentro del periodo; "
            f"se requieren al menos {MIN_OBSERVATIONS}."
        )
    gaps = selected.index.to_series().diff().dt.days.dropna()
    if gaps.median() > 1 or gaps.max() > 7:
        raise PortfolioError(
            "El CSV de precios no parece tener sesiones diarias comparables; "
            "revisa fechas faltantes o frecuencia semanal."
        )
    return PriceDownload(selected, requested, requested, ())
