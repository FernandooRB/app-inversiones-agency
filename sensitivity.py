"""Historical sample-length sensitivity of Markowitz allocations."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError, annualized_moments, optimize_portfolio


@dataclass(frozen=True)
class AllocationSensitivity:
    summary: pd.DataFrame
    weights: pd.DataFrame


def analyze_allocation_sensitivity(
    returns: pd.DataFrame,
    *,
    risk_free_rate: float = 0.0,
    max_weight: float = 1.0,
    windows: tuple[int, ...] = (60, 126, 252),
) -> AllocationSensitivity:
    """Compare trailing estimates with the full sample at the same ending date.

    The full sample is a reference, not an independent test set. The returned
    allocation difference is one-way turnover of target weights, not trade cost.
    """
    if (
        not isinstance(returns.index, pd.DatetimeIndex)
        or returns.index.has_duplicates
        or not returns.index.is_monotonic_increasing
    ):
        raise PortfolioError("La sensibilidad requiere fechas únicas y ordenadas.")
    if returns.columns.has_duplicates or returns.empty or not np.isfinite(returns.to_numpy()).all():
        raise PortfolioError("La muestra de sensibilidad contiene retornos inválidos.")
    if len(returns) < 60:
        raise PortfolioError("La sensibilidad requiere al menos 60 retornos diarios.")
    if any(not isinstance(count, int) or count < 60 for count in windows):
        raise PortfolioError("Cada ventana de sensibilidad requiere al menos 60 retornos.")

    sizes = [("Muestra completa", len(returns))]
    sizes.extend(
        (f"Últimos {count}", count)
        for count in sorted(set(windows), reverse=True)
        if count < len(returns)
    )
    estimates = {}
    for name, count in sizes:
        sample = returns.iloc[-count:]
        mean, covariance = annualized_moments(sample)
        estimates[name] = {
            "Máximo Sharpe": optimize_portfolio(
                mean, covariance, risk_free_rate, "max_sharpe", max_weight
            ).weights,
            "Mínima volatilidad": optimize_portfolio(
                mean, covariance, risk_free_rate, "min_volatility", max_weight
            ).weights,
        }

    summary_rows, weight_rows = [], []
    for name, count in sizes:
        sample = returns.iloc[-count:]
        for model, weights in estimates[name].items():
            reference = estimates["Muestra completa"][model]
            summary_rows.append({
                "Muestra": name, "Modelo": model,
                "Retornos usados": count,
                "Desde": sample.index[0], "Hasta": sample.index[-1],
                "Activo con mayor peso": returns.columns[int(np.argmax(weights))],
                "Mayor peso": float(np.max(weights)),
                "Cambio de pesos vs. muestra completa":
                    0.5 * float(np.abs(weights - reference).sum()),
            })
            weight_rows.extend(
                {"Muestra": name, "Modelo": model, "Activo": asset, "Peso": float(weight)}
                for asset, weight in zip(returns.columns, weights, strict=True)
            )
    return AllocationSensitivity(
        pd.DataFrame(summary_rows).set_index(["Muestra", "Modelo"]),
        pd.DataFrame(weight_rows).set_index(["Muestra", "Modelo", "Activo"]),
    )
