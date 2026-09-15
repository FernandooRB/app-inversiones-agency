"""Predefined chronological cut sensitivity for out-of-sample allocations."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtesting import HoldoutBacktest, run_holdout_backtest
from portfolio_core import PortfolioError

TRAINING_FRACTIONS = (0.50, 0.60, 0.70, 0.80)


@dataclass(frozen=True)
class MultiCutBacktest:
    results: dict[str, HoldoutBacktest]
    summary: pd.DataFrame
    allocations: pd.DataFrame


def run_multi_cut_backtest(
    returns: pd.DataFrame,
    *,
    risk_free_rate: float = 0.0,
    max_weight: float = 1.0,
    current_weights: np.ndarray | None = None,
    trading_cost_bps: float = 0.0,
    covariance_shrinkage: float | str = 0.0,
) -> MultiCutBacktest:
    """Run four fixed cuts, reporting each overlapping evaluation separately."""
    if len(returns) < 120:
        raise PortfolioError(
            "Los cuatro cortes requieren al menos 120 retornos diarios comparables."
        )
    if covariance_shrinkage == "cv" and int(len(returns) * TRAINING_FRACTIONS[0]) < 100:
        raise PortfolioError(
            "La covarianza calibrada requiere al menos 200 retornos para cuatro cortes."
        )

    results, rows = {}, []
    for fraction in TRAINING_FRACTIONS:
        label = f"{fraction:.0%}"
        result = run_holdout_backtest(
            returns, training_fraction=fraction,
            risk_free_rate=risk_free_rate, max_weight=max_weight,
            current_weights=current_weights, trading_cost_bps=trading_cost_bps,
            covariance_shrinkage=covariance_shrinkage,
        )
        results[label] = result
        equal_total = result.summary.loc["Pesos iguales", "Retorno total neto"]
        equal_annual = result.summary.loc["Pesos iguales", "Retorno anualizado neto"]
        for scenario, metrics in result.summary.iterrows():
            rows.append({
                "Corte inicial": label, "Escenario": scenario,
                "Estimación desde": result.training_start,
                "Estimación hasta": result.training_end,
                "Retornos de estimación": result.training_observations,
                "Evaluación desde": result.evaluation_start,
                "Evaluación hasta": result.evaluation_end,
                "Retornos de evaluación": result.evaluation_observations,
                "Contracción de covarianza": result.covariance_shrinkage,
                **metrics.to_dict(),
                "Diferencia total neta vs pesos iguales":
                    metrics["Retorno total neto"] - equal_total,
                "Diferencia anualizada neta vs pesos iguales":
                    metrics["Retorno anualizado neto"] - equal_annual,
            })

    return MultiCutBacktest(
        results,
        pd.DataFrame(rows).set_index(["Corte inicial", "Escenario"]),
        pd.concat(
            {label: result.allocations for label, result in results.items()},
            names=["Corte inicial", "Activo"],
        ),
    )
