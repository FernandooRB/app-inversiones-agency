"""Testable financial core for the portfolio optimizer."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import norm

TRADING_DAYS = 252
MIN_OBSERVATIONS = 60
MAX_ASSETS = 25
TICKER_PATTERN = re.compile(r"^[A-Z0-9.^=-]{1,20}$")


class PortfolioError(ValueError):
    """A safe, user-facing validation or calculation error."""


@dataclass(frozen=True)
class PortfolioMetrics:
    weights: np.ndarray
    annual_return: float
    annual_volatility: float
    sharpe_ratio: float


@dataclass(frozen=True)
class RiskMetrics:
    confidence_level: float
    horizon_days: int
    parametric_var: float
    historical_var: float
    historical_cvar: float


@dataclass(frozen=True)
class PriceDownload:
    prices: pd.DataFrame
    requested_tickers: tuple[str, ...]
    valid_tickers: tuple[str, ...]
    rejected_tickers: tuple[str, ...]


def normalize_tickers(raw_tickers: str | Iterable[str]) -> list[str]:
    values = raw_tickers.split(",") if isinstance(raw_tickers, str) else raw_tickers
    tickers = list(dict.fromkeys(str(value).strip().upper() for value in values if str(value).strip()))
    if not tickers:
        raise PortfolioError("Ingresa al menos un ticker.")
    if len(tickers) > MAX_ASSETS:
        raise PortfolioError(f"Se permiten como máximo {MAX_ASSETS} activos por análisis.")
    invalid = [ticker for ticker in tickers if not TICKER_PATTERN.fullmatch(ticker)]
    if invalid:
        raise PortfolioError(f"Ticker con formato inválido: {', '.join(invalid)}")
    return tickers


def validate_dates(start_date: date, end_date: date) -> None:
    if start_date >= end_date:
        raise PortfolioError("La fecha inicial debe ser anterior a la fecha final.")
    if end_date > date.today():
        raise PortfolioError("La fecha final no puede estar en el futuro.")


def download_adjusted_prices(tickers: Iterable[str], start_date: date, end_date: date) -> PriceDownload:
    """Download explicitly auto-adjusted closes, including the selected end date."""
    requested = tuple(normalize_tickers(tickers))
    validate_dates(start_date, end_date)
    try:
        raw = yf.download(
            list(requested),
            start=start_date.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            actions=False,
            progress=False,
            threads=True,
            group_by="column",
        )
    except Exception as exc:
        raise PortfolioError("No fue posible consultar el proveedor de precios.") from exc
    if raw.empty or "Close" not in raw:
        raise PortfolioError("El proveedor no devolvió precios para los activos solicitados.")
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=requested[0])
    close.columns = [str(column).upper() for column in close.columns]
    close = close.replace([np.inf, -np.inf], np.nan).sort_index()
    valid = tuple(ticker for ticker in requested if ticker in close and close[ticker].notna().any())
    rejected = tuple(ticker for ticker in requested if ticker not in valid)
    if not valid:
        raise PortfolioError("Ningún ticker produjo una serie de precios válida.")
    prices = close.loc[:, list(valid)].dropna(how="any")
    if len(prices) < MIN_OBSERVATIONS:
        raise PortfolioError(
            f"Solo hay {len(prices)} observaciones comunes; se requieren al menos {MIN_OBSERVATIONS}."
        )
    return PriceDownload(prices, requested, valid, rejected)


def calculate_returns(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        raise PortfolioError("La tabla de precios está vacía.")
    if (
        prices.columns.has_duplicates
        or prices.index.has_duplicates
        or not prices.index.is_monotonic_increasing
    ):
        raise PortfolioError("Los precios requieren etiquetas únicas y fechas ordenadas.")
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
        raise PortfolioError("Los precios deben ser positivos y finitos.")
    returns = prices.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < MIN_OBSERVATIONS - 1:
        raise PortfolioError("No existen suficientes retornos válidos para estimar el modelo.")
    return returns


def annualized_moments(
    returns: pd.DataFrame, *, covariance_shrinkage: float = 0.0
) -> tuple[pd.Series, pd.DataFrame]:
    if not np.isfinite(covariance_shrinkage) or not 0 <= covariance_shrinkage <= 1:
        raise PortfolioError("La contracción de covarianza debe estar entre 0% y 100%.")
    if len(returns) < 2 or not np.isfinite(returns.to_numpy()).all():
        raise PortfolioError("Retornos insuficientes o no finitos.")
    if (returns.std() <= 1e-10).any():
        raise PortfolioError("Hay activos sin variación suficiente; revisa los datos.")
    mean_returns = returns.mean() * TRADING_DAYS
    covariance = returns.cov() * TRADING_DAYS
    if covariance_shrinkage:
        matrix = covariance.to_numpy()
        covariance = pd.DataFrame(
            (1 - covariance_shrinkage) * matrix
            + covariance_shrinkage * np.diag(np.diag(matrix)),
            index=covariance.index, columns=covariance.columns,
        )
    ridge = max(float(np.trace(covariance.to_numpy())), 1.0) * 1e-10
    covariance = covariance + np.eye(len(covariance)) * ridge
    if not np.isfinite(mean_returns).all() or not np.isfinite(covariance).all().all():
        raise PortfolioError("Las estimaciones contienen valores no finitos.")
    return mean_returns, covariance


def validate_weights(weights, asset_count, max_weight=1.0):
    weights = np.asarray(weights, dtype=float)
    if (
        weights.shape != (asset_count,)
        or not np.isfinite(weights).all()
        or not np.isclose(weights.sum(), 1.0, atol=1e-7, rtol=0)
        or (weights < -1e-8).any()
        or (weights > max_weight + 1e-7).any()
    ):
        raise PortfolioError("Pesos inválidos: deben ser finitos, no negativos y sumar 100%.")
    return weights


def parse_current_weights(raw: str, asset_count: int) -> np.ndarray:
    """Parse optional current-portfolio weights entered as percentages."""
    try:
        values = [float(part.strip()) for part in raw.split(",")]
    except ValueError as exc:
        raise PortfolioError("Ingresa los pesos actuales como porcentajes separados por comas.") from exc
    if len(values) != asset_count:
        raise PortfolioError(f"Ingresa exactamente {asset_count} pesos actuales, en el orden de los activos.")
    weights = np.asarray(values, dtype=float) / 100
    if not np.isfinite(weights).all() or (weights < 0).any() or abs(weights.sum() - 1) > 0.0005:
        raise PortfolioError("Los pesos actuales deben ser no negativos y sumar 100%.")
    return validate_weights(weights / weights.sum(), asset_count)


def validate_model(mean_returns, covariance, risk_free_rate):
    if (
        len(mean_returns) == 0
        or not mean_returns.index.is_unique
        or not covariance.index.equals(mean_returns.index)
        or not covariance.columns.equals(mean_returns.index)
    ):
        raise PortfolioError("Las etiquetas de medias y covarianza no coinciden.")
    matrix = covariance.to_numpy()
    if (
        not np.isfinite(mean_returns).all()
        or not np.isfinite(matrix).all()
        or not np.isfinite(risk_free_rate)
        or not np.allclose(matrix, matrix.T)
        or np.linalg.eigvalsh(matrix).min() < -1e-10
    ):
        raise PortfolioError("Modelo no finito, asimétrico o con covarianza inválida.")


def portfolio_statistics(weights, mean_returns, covariance, risk_free_rate):
    validate_model(mean_returns, covariance, risk_free_rate)
    weights = validate_weights(weights, len(mean_returns))
    annual_return = float(weights @ mean_returns.to_numpy())
    variance = float(weights @ covariance.to_numpy() @ weights)
    annual_volatility = float(np.sqrt(max(variance, 0.0)))
    if annual_volatility <= 1e-12:
        raise PortfolioError("La volatilidad estimada es demasiado pequeña para optimizar.")
    sharpe = (annual_return - risk_free_rate) / annual_volatility
    return annual_return, annual_volatility, float(sharpe)


def _validate_weight_limit(asset_count: int, max_weight: float) -> None:
    if asset_count < 1:
        raise PortfolioError("Se requiere al menos un activo.")
    if not 0 < max_weight <= 1:
        raise PortfolioError("El peso máximo debe estar entre 0% y 100%.")
    if asset_count * max_weight < 1 - 1e-10:
        raise PortfolioError(
            f"El peso máximo debe ser al menos {1 / asset_count:.1%} para {asset_count} activos."
        )


def optimize_portfolio(mean_returns, covariance, risk_free_rate, objective="max_sharpe", max_weight=1.0):
    """Optimize a long-only portfolio with a concentration cap."""
    asset_count = len(mean_returns)
    validate_model(mean_returns, covariance, risk_free_rate)
    _validate_weight_limit(asset_count, max_weight)
    initial = np.full(asset_count, 1 / asset_count)
    bounds = tuple((0.0, max_weight) for _ in range(asset_count))
    constraints = ({"type": "eq", "fun": lambda weights: float(weights.sum() - 1)},)
    cov = covariance.to_numpy()
    means = mean_returns.to_numpy()

    def volatility(weights):
        return float(np.sqrt(max(weights @ cov @ weights, 0.0)))

    def negative_sharpe(weights):
        vol = volatility(weights)
        return 1e9 if vol <= 1e-12 else -float((weights @ means - risk_free_rate) / vol)

    if objective not in {"max_sharpe", "min_volatility"}:
        raise PortfolioError("Objetivo de optimización no reconocido.")
    objective_fn = negative_sharpe if objective == "max_sharpe" else volatility
    result = minimize(
        objective_fn,
        initial,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1_000, "ftol": 1e-10},
    )
    if not result.success or not np.isfinite(result.x).all():
        raise PortfolioError(f"La optimización no convergió: {result.message}")
    weights = np.clip(result.x, 0.0, max_weight)
    weights = weights / weights.sum()
    validate_weights(weights, asset_count, max_weight)
    annual_return, annual_volatility, sharpe = portfolio_statistics(
        weights, mean_returns, covariance, risk_free_rate
    )
    return PortfolioMetrics(weights, annual_return, annual_volatility, sharpe)


def efficient_frontier(mean_returns, covariance, max_weight=1.0, points=40):
    """Compute minimum-variance portfolios across feasible target returns."""
    asset_count = len(mean_returns)
    _validate_weight_limit(asset_count, max_weight)
    minimum = optimize_portfolio(mean_returns, covariance, 0.0, "min_volatility", max_weight)
    if (
        asset_count == 1
        or np.isclose(asset_count * max_weight, 1.0)
        or np.ptp(mean_returns.to_numpy()) < 1e-10
    ):
        return pd.DataFrame([{"Retorno": minimum.annual_return, "Volatilidad": minimum.annual_volatility}])
    bounds = tuple((0.0, max_weight) for _ in range(asset_count))
    cov, means = covariance.to_numpy(), mean_returns.to_numpy()
    # Determine the maximum feasible return under the concentration cap.
    remaining, highest = 1.0, 0.0
    for value in np.sort(means)[::-1]:
        allocation = min(max_weight, remaining)
        highest += allocation * value
        remaining -= allocation
        if remaining <= 1e-12:
            break
    if highest - minimum.annual_return <= 1e-8:
        return pd.DataFrame([{"Retorno": minimum.annual_return, "Volatilidad": minimum.annual_volatility}])
    targets = np.linspace(minimum.annual_return, highest, points)
    initial, rows = minimum.weights, []
    for target in targets:
        constraints = (
            {"type": "eq", "fun": lambda weights: float(weights.sum() - 1)},
            {"type": "eq", "fun": lambda weights, target=target: float(weights @ means - target)},
        )
        result = minimize(
            lambda weights: float(weights @ cov @ weights),
            initial,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1_000, "ftol": 1e-10},
        )
        if result.success:
            rows.append({"Retorno": float(target), "Volatilidad": float(np.sqrt(max(result.fun, 0.0)))})
            initial = result.x
    if len(rows) < 2:
        raise PortfolioError("No fue posible construir una frontera eficiente estable.")
    return pd.DataFrame(rows)


def random_portfolios(mean_returns, covariance, risk_free_rate, simulations=5_000, seed=42, max_weight=1.0):
    """Generate reproducible random allocations for visual context."""
    rng = np.random.default_rng(seed)
    weights = rng.dirichlet(np.ones(len(mean_returns)), simulations)
    _validate_weight_limit(len(mean_returns), max_weight)
    # Contract each draw towards equal weight until it obeys the same cap as the frontier.
    equal = 1 / len(mean_returns)
    excess = weights.max(axis=1) - equal
    scale = np.minimum(
        1.0, np.divide(max_weight - equal, excess, out=np.ones_like(excess), where=excess > 1e-12)
    )
    weights = equal + scale[:, None] * (weights - equal)
    means, cov = mean_returns.to_numpy(), covariance.to_numpy()
    returns = weights @ means
    volatilities = np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights))
    sharpes = np.divide(
        returns - risk_free_rate, volatilities, out=np.full(simulations, np.nan), where=volatilities > 1e-12
    )
    return pd.DataFrame({"Retorno": returns, "Volatilidad": volatilities, "Sharpe": sharpes})


def calculate_risk_metrics(returns, weights, confidence_level=0.95, horizon_days=1):
    """Return positive loss magnitudes for normal and historical VaR/ES."""
    if not 0.90 <= confidence_level <= 0.999:
        raise PortfolioError("El nivel de confianza debe estar entre 90% y 99.9%.")
    if not isinstance(horizon_days, int) or not 1 <= horizon_days <= 252:
        raise PortfolioError("El horizonte debe estar entre 1 y 252 días hábiles.")
    weights = validate_weights(weights, returns.shape[1])
    if len(returns) < 2 or not np.isfinite(returns.to_numpy()).all() or (returns < -1).any().any():
        raise PortfolioError("Retornos inválidos para calcular riesgo.")
    daily = returns.to_numpy() @ weights
    mean = float(np.mean(daily)) * horizon_days
    sigma = float(np.std(daily, ddof=1)) * np.sqrt(horizon_days)
    parametric_var = max(0.0, -(mean + norm.ppf(1 - confidence_level) * sigma))
    historical = (
        daily
        if horizon_days == 1
        else ((1 + pd.Series(daily)).rolling(horizon_days).apply(np.prod, raw=True) - 1).dropna().to_numpy()
    )
    if not len(historical):
        raise PortfolioError("No hay suficientes datos para el horizonte de riesgo elegido.")
    quantile = float(np.quantile(historical, 1 - confidence_level))
    tail = historical[historical <= quantile]
    return RiskMetrics(
        confidence_level, horizon_days, parametric_var, max(0.0, -quantile), max(0.0, -float(np.mean(tail)))
    )
