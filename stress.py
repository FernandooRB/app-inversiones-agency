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


def parse_class_shocks(
    raw: str, asset_classes: tuple[str, ...]
) -> tuple[pd.Series, np.ndarray]:
    """Parse one percentage shock per declared class and expand it to the assets."""
    if not asset_classes or any(not str(value).strip() for value in asset_classes):
        raise PortfolioError("Cada activo requiere una clase para aplicar shocks por clase.")
    normalized = tuple(str(value).strip().lower() for value in asset_classes)
    expected = set(normalized)
    parsed: dict[str, float] = {}
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip().lower() for part in line.split(",")]
        if len(parts) != 2:
            raise PortfolioError(
                f"La línea {line_number} debe tener clase y shock porcentual."
            )
        name = parts[0]
        if name in parsed:
            raise PortfolioError(f"La clase {name} aparece más de una vez en los shocks.")
        try:
            value = float(parts[1]) / 100
        except ValueError as exc:
            raise PortfolioError(
                f"El shock de la línea {line_number} debe ser numérico."
            ) from exc
        if not np.isfinite(value) or value < -1 or value > 10:
            raise PortfolioError(
                "Cada shock de clase debe ser finito, al menos -100% y no mayor a 1,000%."
            )
        parsed[name] = value
    missing, extra = expected - parsed.keys(), parsed.keys() - expected
    if missing:
        raise PortfolioError("Faltan shocks para las clases: " + ", ".join(sorted(missing)))
    if extra:
        raise PortfolioError(
            "Hay shocks para clases no utilizadas: " + ", ".join(sorted(extra))
        )
    class_shocks = pd.Series(
        {name: parsed[name] for name in sorted(expected)}, name="Shock por clase", dtype=float
    )
    return class_shocks, np.asarray([parsed[name] for name in normalized], dtype=float)


def validate_scenario_metadata(name: str, rationale: str) -> tuple[str, str]:
    """Validate report-safe labels for a hypothetical stress scenario."""
    cleaned_name, cleaned_rationale = name.strip(), rationale.strip()
    if (
        not cleaned_name or len(cleaned_name) > 80
        or any(ord(char) < 32 for char in cleaned_name)
    ):
        raise PortfolioError("El escenario requiere un nombre de 1 a 80 caracteres.")
    if (
        not cleaned_rationale or len(cleaned_rationale) > 240
        or any(ord(char) < 32 for char in cleaned_rationale)
    ):
        raise PortfolioError("El fundamento del escenario debe tener de 1 a 240 caracteres.")
    return cleaned_name, cleaned_rationale


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
