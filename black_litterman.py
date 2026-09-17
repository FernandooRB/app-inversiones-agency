"""Auditable Black-Litterman expected-return scenarios."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import PortfolioError, validate_model, validate_weights


@dataclass(frozen=True)
class AbsoluteView:
    asset: str
    expected_return: float
    confidence: float


@dataclass(frozen=True)
class BlackLittermanResult:
    equilibrium_weights: np.ndarray
    risk_aversion: float
    tau: float
    prior_returns: pd.Series
    posterior_returns: pd.Series
    views: tuple[AbsoluteView, ...]
    detail: pd.DataFrame


def parse_absolute_views(
    raw: str,
    assets,
) -> tuple[AbsoluteView, ...]:
    """Parse `activo, rendimiento anual %, confianza %` rows."""
    valid_assets = tuple(str(asset) for asset in assets)
    if not valid_assets or len(set(valid_assets)) != len(valid_assets):
        raise PortfolioError("Los activos para Black-Litterman deben ser únicos.")
    views: list[AbsoluteView] = []
    used: set[str] = set()
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            raise PortfolioError(
                f"La línea {line_number} debe tener activo, rendimiento % y confianza %."
            )
        asset = parts[0].upper()
        if asset not in valid_assets:
            raise PortfolioError(f"El activo {asset} de la línea {line_number} no existe.")
        if asset in used:
            raise PortfolioError(f"El activo {asset} tiene más de una opinión.")
        try:
            expected_return = float(parts[1]) / 100
            confidence = float(parts[2]) / 100
        except ValueError as exc:
            raise PortfolioError(
                f"Rendimiento y confianza de la línea {line_number} deben ser numéricos."
            ) from exc
        if (
            not np.isfinite(expected_return) or not -1 <= expected_return <= 5
            or not np.isfinite(confidence) or not 0.01 <= confidence <= 0.99
        ):
            raise PortfolioError(
                "Cada rendimiento debe estar entre -100% y 500%, y la confianza entre 1% y 99%."
            )
        views.append(AbsoluteView(asset, expected_return, confidence))
        used.add(asset)
    return tuple(views)


def black_litterman_posterior(
    covariance: pd.DataFrame,
    equilibrium_weights,
    risk_free_rate: float,
    *,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
    views: tuple[AbsoluteView, ...] = (),
) -> BlackLittermanResult:
    """Combine equilibrium excess returns and independent absolute views."""
    assets = covariance.index
    dummy_means = pd.Series(np.zeros(len(assets)), index=assets)
    validate_model(dummy_means, covariance, risk_free_rate)
    weights = validate_weights(equilibrium_weights, len(assets))
    if not np.isfinite(risk_aversion) or not 0 < risk_aversion <= 100:
        raise PortfolioError("La aversión al riesgo debe ser mayor que 0 y no superar 100.")
    if not np.isfinite(tau) or not 0 < tau <= 1:
        raise PortfolioError("Tau debe ser mayor que 0 y no superar 1.")
    if not isinstance(views, tuple) or any(not isinstance(view, AbsoluteView) for view in views):
        raise PortfolioError("Las opiniones Black-Litterman tienen un formato inválido.")
    names = [view.asset for view in views]
    if (
        len(names) != len(set(names))
        or any(not isinstance(name, str) or name not in assets for name in names)
    ):
        raise PortfolioError("Las opiniones deben referirse una sola vez a activos existentes.")
    if any(
        not np.isfinite(view.expected_return) or not -1 <= view.expected_return <= 5
        or not np.isfinite(view.confidence) or not 0.01 <= view.confidence <= 0.99
        for view in views
    ):
        raise PortfolioError("Las opiniones Black-Litterman contienen valores inválidos.")

    matrix = covariance.to_numpy(dtype=float)
    prior_excess = risk_aversion * matrix @ weights
    posterior_excess = prior_excess.copy()
    if views:
        positions = {str(asset): index for index, asset in enumerate(assets)}
        pick = np.zeros((len(views), len(assets)))
        targets = np.empty(len(views))
        omega = np.empty(len(views))
        scaled_covariance = tau * matrix
        for row, view in enumerate(views):
            pick[row, positions[view.asset]] = 1.0
            targets[row] = view.expected_return - risk_free_rate
            view_variance = float(pick[row] @ scaled_covariance @ pick[row])
            if view_variance <= 1e-16:
                raise PortfolioError("Una opinión tiene varianza demasiado pequeña.")
            omega[row] = view_variance * (1 - view.confidence) / view.confidence
        system = pick @ scaled_covariance @ pick.T + np.diag(omega)
        try:
            adjustment = scaled_covariance @ pick.T @ np.linalg.solve(
                system, targets - pick @ prior_excess
            )
        except np.linalg.LinAlgError as exc:
            raise PortfolioError("No fue posible combinar las opiniones Black-Litterman.") from exc
        posterior_excess = prior_excess + adjustment

    prior = pd.Series(prior_excess + risk_free_rate, index=assets, name="Equilibrio")
    posterior = pd.Series(posterior_excess + risk_free_rate, index=assets, name="Posterior")
    view_by_asset = {view.asset: view for view in views}
    detail = pd.DataFrame({
        "Activo": assets.astype(str),
        "Peso de equilibrio": weights,
        "Retorno de equilibrio": prior.to_numpy(),
        "Opinión": [
            view_by_asset[str(asset)].expected_return if str(asset) in view_by_asset else np.nan
            for asset in assets
        ],
        "Confianza": [
            view_by_asset[str(asset)].confidence if str(asset) in view_by_asset else np.nan
            for asset in assets
        ],
        "Retorno posterior": posterior.to_numpy(),
    })
    return BlackLittermanResult(
        weights.copy(), risk_aversion, tau, prior, posterior, views, detail
    )
