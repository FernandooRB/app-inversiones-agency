"""Past-only blocked calibration of diagonal covariance shrinkage."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import TRADING_DAYS, PortfolioError, annualized_moments

CANDIDATES = (0.0, 0.25, 0.50, 0.75, 1.0)
VALIDATION_OBSERVATIONS = 20


@dataclass(frozen=True)
class ShrinkageCalibration:
    intensity: float
    fold_scores: pd.DataFrame
    mean_scores: pd.Series


def select_diagonal_shrinkage(returns: pd.DataFrame) -> ShrinkageCalibration:
    """Choose a candidate using only chronological inner validation blocks.

    Prefixes are fixed at 60, 126, 252 and the last available 20-observation
    block, provided blocks do not overlap. This is a small research protocol,
    not the analytic Ledoit-Wolf intensity or a portfolio-return optimizer.
    """
    if (
        not isinstance(returns.index, pd.DatetimeIndex)
        or returns.index.has_duplicates
        or not returns.index.is_monotonic_increasing
    ):
        raise PortfolioError("La calibración requiere fechas únicas y ordenadas.")
    if returns.columns.has_duplicates or returns.empty or not np.isfinite(returns.to_numpy()).all():
        raise PortfolioError("La calibración contiene retornos inválidos.")
    if len(returns) < 100:
        raise PortfolioError(
            "La calibración requiere al menos 100 retornos de entrenamiento."
        )

    prefixes = []
    for count in (60, 126, 252, len(returns) - VALIDATION_OBSERVATIONS):
        if (
            count + VALIDATION_OBSERVATIONS <= len(returns)
            and all(abs(count - prior) >= VALIDATION_OBSERVATIONS for prior in prefixes)
        ):
            prefixes.append(count)

    records = []
    for count in prefixes:
        estimation = returns.iloc[:count]
        validation = returns.iloc[count:count + VALIDATION_OBSERVATIONS]
        observed = validation.cov().to_numpy() * TRADING_DAYS
        row = {
            "Estimación hasta": estimation.index[-1],
            "Validación desde": validation.index[0],
            "Validación hasta": validation.index[-1],
            "Retornos de estimación": count,
        }
        for candidate in CANDIDATES:
            _, forecast = annualized_moments(
                estimation, covariance_shrinkage=candidate
            )
            row[f"{candidate:.0%}"] = float(
                np.square(forecast.to_numpy() - observed).sum()
            )
        records.append(row)

    scores = pd.DataFrame.from_records(records)
    mean_scores = scores[[f"{candidate:.0%}" for candidate in CANDIDATES]].mean()
    selected = min(CANDIDATES, key=lambda candidate: (mean_scores[f"{candidate:.0%}"], candidate))
    return ShrinkageCalibration(selected, scores, mean_scores)
