"""Transparent historical and deterministic portfolio stress calculations."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError, validate_weights


@dataclass(frozen=True)
class ShockResult:
    portfolio_return: float
    stressed_value: float
    loss_amount: float
    contributions: pd.Series


def historical_worst_windows(
    returns: pd.DataFrame, weights, horizons: tuple[int, ...] = (1, 5, 21)
) -> pd.DataFrame:
    """Worst compounded rolling outcomes for a daily-rebalanced portfolio."""
    if (
        not isinstance(returns, pd.DataFrame) or returns.empty
        or not isinstance(returns.index, pd.DatetimeIndex)
        or returns.index.has_duplicates or not returns.index.is_monotonic_increasing
        or not np.isfinite(returns.to_numpy()).all() or (returns <= -1).any().any()
    ):
        raise PortfolioError("Retornos inválidos para el estrés histórico.")
    weights = validate_weights(weights, returns.shape[1])
    if not horizons or any(not isinstance(item, int) or item < 1 for item in horizons):
        raise PortfolioError("Los horizontes de estrés deben ser enteros positivos.")
    daily = pd.Series(returns.to_numpy() @ weights, index=returns.index)
    rows = []
    for horizon in horizons:
        if horizon > len(daily):
            raise PortfolioError("No hay suficientes retornos para un horizonte de estrés.")
        compounded = (1 + daily).rolling(horizon).apply(np.prod, raw=True) - 1
        end = compounded.idxmin()
        end_position = daily.index.get_loc(end)
        start = daily.index[end_position - horizon + 1]
        rows.append({
            "Horizonte": horizon,
            "Inicio": pd.Timestamp(start),
            "Fin": pd.Timestamp(end),
            "Peor retorno": float(compounded.loc[end]),
        })
    return pd.DataFrame(rows)


def parse_asset_shocks(raw: str, asset_count: int) -> np.ndarray:
    """Parse one percentage price shock for each asset, preserving order."""
    try:
        values = np.asarray([float(part.strip()) for part in raw.split(",")], dtype=float)
    except ValueError as exc:
        raise PortfolioError("Ingresa los shocks como porcentajes separados por comas.") from exc
    if values.shape != (asset_count,):
        raise PortfolioError(f"Ingresa exactamente {asset_count} shocks, en el orden de los activos.")
    shocks = values / 100
    if not np.isfinite(shocks).all() or (shocks < -1).any() or (shocks > 10).any():
        raise PortfolioError("Cada shock debe ser finito, al menos -100% y no mayor a 1,000%.")
    return shocks


def deterministic_shock(weights, shocks, portfolio_value: float, labels=None) -> ShockResult:
    """Apply simultaneous one-step relative price changes to current weights."""
    shocks = np.asarray(shocks, dtype=float)
    weights = validate_weights(weights, len(shocks))
    if not np.isfinite(shocks).all() or (shocks < -1).any():
        raise PortfolioError("Los shocks deben ser finitos y al menos -100%.")
    if not np.isfinite(portfolio_value) or portfolio_value < 0:
        raise PortfolioError("El valor del portafolio debe ser finito y no negativo.")
    portfolio_return = float(weights @ shocks)
    stressed_value = portfolio_value * (1 + portfolio_return)
    index = labels if labels is not None else range(len(shocks))
    contributions = pd.Series(weights * shocks, index=index, name="Contribución al retorno")
    return ShockResult(
        portfolio_return=portfolio_return,
        stressed_value=float(stressed_value),
        loss_amount=float(max(0, portfolio_value - stressed_value)),
        contributions=contributions,
    )
