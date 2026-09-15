"""Single-split, out-of-sample research check for portfolio allocations."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import (
    PortfolioError,
    annualized_moments,
    optimize_portfolio,
    validate_weights,
)


@dataclass(frozen=True)
class HoldoutBacktest:
    training_start: pd.Timestamp
    training_end: pd.Timestamp
    evaluation_start: pd.Timestamp
    evaluation_end: pd.Timestamp
    training_observations: int
    evaluation_observations: int
    allocations: pd.DataFrame
    summary: pd.DataFrame
    equity_curves: pd.DataFrame


def _evaluate_buy_and_hold(
    evaluation: pd.DataFrame,
    weights: np.ndarray,
    *,
    entry_turnover: float,
    trading_cost_bps: float,
    risk_free_rate: float,
    initial_date: pd.Timestamp,
) -> tuple[pd.Series, dict[str, float]]:
    starting_value = 1 - entry_turnover * trading_cost_bps / 10_000
    relative_asset_values = (1 + evaluation).cumprod()
    holdings = relative_asset_values.mul(weights * starting_value, axis=1)
    curve = pd.concat(
        [pd.Series([1.0], index=pd.DatetimeIndex([initial_date])), holdings.sum(axis=1)]
    )
    daily = curve.pct_change().dropna()
    days = (evaluation.index.max() - initial_date).days
    annual_return = curve.iloc[-1] ** (365.25 / days) - 1
    volatility = float(daily.std(ddof=1) * np.sqrt(252))
    sharpe = (
        float((daily.mean() * 252 - risk_free_rate) / volatility)
        if volatility > 1e-12 else float("nan")
    )
    drawdown = float((curve / curve.cummax() - 1).min())
    return curve, {
        "Retorno total neto": float(curve.iloc[-1] - 1),
        "Retorno anualizado neto": float(annual_return),
        "Volatilidad anualizada": volatility,
        "Sharpe realizado": sharpe,
        "Máxima caída": drawdown,
        "Rotación inicial": entry_turnover,
        "Costo inicial sobre capital": entry_turnover * trading_cost_bps / 10_000,
    }


def run_holdout_backtest(
    returns: pd.DataFrame,
    *,
    training_fraction: float = 0.70,
    risk_free_rate: float = 0.0,
    max_weight: float = 1.0,
    current_weights: np.ndarray | None = None,
    trading_cost_bps: float = 0.0,
) -> HoldoutBacktest:
    """Estimate allocations once, then evaluate the untouched later sample."""
    if not isinstance(returns.index, pd.DatetimeIndex) or (
        returns.index.has_duplicates or not returns.index.is_monotonic_increasing
    ):
        raise PortfolioError("La prueba fuera de muestra requiere fechas únicas y ordenadas.")
    if not 0.50 <= training_fraction <= 0.90:
        raise PortfolioError("La proporción de estimación debe estar entre 50% y 90%.")
    if not np.isfinite(trading_cost_bps) or not 0 <= trading_cost_bps <= 500:
        raise PortfolioError("El costo inicial debe estar entre 0 y 500 puntos base.")
    if not np.isfinite(risk_free_rate):
        raise PortfolioError("La tasa libre de riesgo debe ser finita.")
    if returns.empty or returns.columns.has_duplicates or not np.isfinite(returns.to_numpy()).all():
        raise PortfolioError("La muestra de retornos contiene datos inválidos.")
    if (returns <= -1).any().any():
        raise PortfolioError("Los retornos no pueden implicar un precio negativo o cero.")
    training_count = int(len(returns) * training_fraction)
    evaluation_count = len(returns) - training_count
    if training_count < 60 or evaluation_count < 20:
        raise PortfolioError(
            "Se requieren al menos 60 retornos para estimación y 20 para evaluación."
        )
    training = returns.iloc[:training_count]
    evaluation = returns.iloc[training_count:]
    if training.index.max() >= evaluation.index.min():
        raise PortfolioError("Las ventanas de estimación y evaluación se superponen.")
    baseline = (
        validate_weights(current_weights, returns.shape[1])
        if current_weights is not None else None
    )
    mean, covariance = annualized_moments(training)
    allocations = {
        "Máximo Sharpe": optimize_portfolio(
            mean, covariance, risk_free_rate, "max_sharpe", max_weight
        ).weights,
        "Mínima volatilidad": optimize_portfolio(
            mean, covariance, risk_free_rate, "min_volatility", max_weight
        ).weights,
        "Pesos iguales": np.full(returns.shape[1], 1 / returns.shape[1]),
    }
    if baseline is not None:
        allocations["Cartera actual"] = baseline

    curves, rows = {}, {}
    for name, weights in allocations.items():
        turnover = 0.5 * float(np.abs(weights - baseline).sum()) if baseline is not None else 0.0
        curve, metrics = _evaluate_buy_and_hold(
            evaluation, weights, entry_turnover=turnover,
            trading_cost_bps=trading_cost_bps,
            risk_free_rate=risk_free_rate,
            initial_date=training.index.max(),
        )
        curves[name] = curve
        rows[name] = metrics
    return HoldoutBacktest(
        training.index.min(), training.index.max(),
        evaluation.index.min(), evaluation.index.max(),
        training_count, evaluation_count,
        pd.DataFrame(allocations, index=returns.columns),
        pd.DataFrame.from_dict(rows, orient="index").rename_axis("Escenario"),
        pd.DataFrame(curves),
    )
