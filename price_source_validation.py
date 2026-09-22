"""Internal, source-independent comparison of two licensed adjusted-price files."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256

import numpy as np
import pandas as pd

from currencies import SUPPORTED
from data_rights import read_data_rights_csv
from portfolio_core import PortfolioError
from price_upload import read_adjusted_price_csv


@dataclass(frozen=True)
class PriceSourceComparison:
    primary_source: str
    reference_source: str
    primary_fingerprint: str
    reference_fingerprint: str
    primary_rights_fingerprint: str
    reference_rights_fingerprint: str
    primary_sessions: int
    reference_sessions: int
    common_sessions: int
    coverage_ratio: float
    missing_in_primary: tuple[str, ...]
    missing_in_reference: tuple[str, ...]
    tolerance: float
    summary: pd.DataFrame
    discrepancies: pd.DataFrame
    review_reasons: tuple[str, ...]

    @property
    def status(self) -> str:
        return "REVISAR" if self.review_reasons else "SIN_ALERTAS_AUTOMATICAS"


def compare_price_sources(
    primary_csv: bytes,
    primary_rights_csv: bytes,
    reference_csv: bytes,
    reference_rights_csv: bytes,
    tickers: tuple[str, ...],
    quote_currencies: dict[str, str],
    start_date: date,
    end_date: date,
    *,
    tolerance_pct: float,
    minimum_coverage_pct: float,
) -> PriceSourceComparison:
    """Compare like-for-like quotes; never certify their economic correctness."""
    if (
        not np.isfinite(tolerance_pct) or not 0 <= tolerance_pct <= 100
        or not np.isfinite(minimum_coverage_pct)
        or not 0 < minimum_coverage_pct <= 100
    ):
        raise PortfolioError("Los umbrales de comparación deben ser porcentajes finitos válidos.")
    primary_rights = read_data_rights_csv(primary_rights_csv)
    reference_rights = read_data_rights_csv(reference_rights_csv)
    if primary_rights.source.strip().casefold() == reference_rights.source.strip().casefold():
        raise PortfolioError("La referencia debe provenir de una fuente independiente.")

    primary = read_adjusted_price_csv(primary_csv, tickers, start_date, end_date).prices
    reference = read_adjusted_price_csv(reference_csv, tickers, start_date, end_date).prices
    if set(quote_currencies) != set(primary.columns) or any(
        quote_currencies[asset] not in SUPPORTED for asset in primary.columns
    ):
        raise PortfolioError("Declara una moneda de cotización válida para cada instrumento.")

    common = primary.index.intersection(reference.index)
    if len(common) < 60:
        raise PortfolioError("La comparación requiere al menos 60 fechas comunes entre fuentes.")
    union = primary.index.union(reference.index)
    coverage = len(common) / len(union)
    missing_in_primary = tuple(
        day.date().isoformat() for day in reference.index.difference(primary.index)
    )
    missing_in_reference = tuple(
        day.date().isoformat() for day in primary.index.difference(reference.index)
    )
    tolerance = tolerance_pct / 100
    summary_rows = []
    discrepancy_rows = []
    for asset in primary.columns:
        relative = primary.loc[common, asset] / reference.loc[common, asset] - 1
        absolute = relative.abs()
        breaches = absolute > tolerance
        summary_rows.append({
            "Instrumento": asset,
            "Moneda declarada": quote_currencies[asset],
            "Fechas comunes": len(common),
            "Diferencia mediana absoluta": float(absolute.median()),
            "Diferencia máxima absoluta": float(absolute.max()),
            "Fechas fuera de umbral": int(breaches.sum()),
        })
        discrepancy_rows.extend({
            "Fecha": day.date().isoformat(),
            "Instrumento": asset,
            "Diferencia relativa": float(relative.loc[day]),
        } for day in common[breaches])
    summary = pd.DataFrame(summary_rows)
    discrepancies = pd.DataFrame(
        discrepancy_rows, columns=["Fecha", "Instrumento", "Diferencia relativa"]
    )

    reasons = []
    if coverage < minimum_coverage_pct / 100:
        reasons.append("La cobertura de fechas comunes quedó por debajo del mínimo declarado.")
    if not discrepancies.empty:
        reasons.append("Existen diferencias de precio superiores al umbral declarado.")
    if primary_rights.markets.strip().casefold() != reference_rights.markets.strip().casefold():
        reasons.append("Los manifiestos declaran mercados diferentes; verifica el instrumento negociado.")
    if (
        primary_rights.cutoff_convention.strip().casefold()
        != reference_rights.cutoff_convention.strip().casefold()
    ):
        reasons.append("Las fuentes declaran convenciones de corte distintas; concilia horarios.")
    return PriceSourceComparison(
        primary_source=primary_rights.source,
        reference_source=reference_rights.source,
        primary_fingerprint=sha256(primary_csv).hexdigest(),
        reference_fingerprint=sha256(reference_csv).hexdigest(),
        primary_rights_fingerprint=primary_rights.fingerprint,
        reference_rights_fingerprint=reference_rights.fingerprint,
        primary_sessions=len(primary),
        reference_sessions=len(reference),
        common_sessions=len(common),
        coverage_ratio=coverage,
        missing_in_primary=missing_in_primary,
        missing_in_reference=missing_in_reference,
        tolerance=tolerance,
        summary=summary,
        discrepancies=discrepancies,
        review_reasons=tuple(reasons),
    )
