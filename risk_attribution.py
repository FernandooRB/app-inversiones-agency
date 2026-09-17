"""Euler volatility attribution and diversification diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError, validate_model, validate_weights


@dataclass(frozen=True)
class RiskAttribution:
    alternative_name: str
    portfolio_volatility: float
    weighted_standalone_volatility: float
    diversification_ratio: float
    weight_hhi: float
    effective_positions: float
    absolute_risk_hhi: float
    effective_risk_contributors: float
    detail: pd.DataFrame


def attribute_volatility(
    covariance: pd.DataFrame,
    weights,
    *,
    alternative_name: str,
) -> RiskAttribution:
    """Decompose annualized portfolio volatility using Euler contributions."""
    name = alternative_name.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise PortfolioError("La atribución requiere un nombre de alternativa válido.")
    labels = covariance.index
    dummy_means = pd.Series(np.zeros(len(labels)), index=labels)
    validate_model(dummy_means, covariance, 0.0)
    weights = validate_weights(weights, len(labels))
    matrix = covariance.to_numpy(dtype=float)
    variance = float(weights @ matrix @ weights)
    if variance <= 1e-16:
        raise PortfolioError("La volatilidad es demasiado pequeña para atribuir riesgo.")
    portfolio_volatility = float(np.sqrt(variance))
    marginal = matrix @ weights / portfolio_volatility
    component = weights * marginal
    if not np.isclose(component.sum(), portfolio_volatility, atol=1e-10, rtol=1e-8):
        raise PortfolioError("La descomposición de volatilidad no reconcilia con el total.")
    percentage = component / portfolio_volatility
    absolute_total = float(np.abs(component).sum())
    absolute_share = np.abs(component) / absolute_total
    standalone = np.sqrt(np.clip(np.diag(matrix), 0.0, None))
    weighted_standalone = float(weights @ standalone)
    weight_hhi = float(np.square(weights).sum())
    absolute_risk_hhi = float(np.square(absolute_share).sum())
    detail = pd.DataFrame({
        "Activo": labels.astype(str),
        "Peso": weights,
        "Volatilidad individual": standalone,
        "Contribución marginal": marginal,
        "Contribución a volatilidad": component,
        "% contribución a volatilidad": percentage,
        "% absoluto del riesgo": absolute_share,
    })
    return RiskAttribution(
        alternative_name=name,
        portfolio_volatility=portfolio_volatility,
        weighted_standalone_volatility=weighted_standalone,
        diversification_ratio=weighted_standalone / portfolio_volatility,
        weight_hhi=weight_hhi,
        effective_positions=1 / weight_hhi,
        absolute_risk_hhi=absolute_risk_hhi,
        effective_risk_contributors=1 / absolute_risk_hhi,
        detail=detail,
    )
