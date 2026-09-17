"""Historical portfolio comparison against an independent benchmark series."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import MIN_OBSERVATIONS, TRADING_DAYS, PortfolioError, validate_weights


@dataclass(frozen=True)
class BenchmarkAnalysis:
    portfolio_name: str
    name: str
    observations: int
    start: pd.Timestamp
    end: pd.Timestamp
    portfolio_total_return: float
    benchmark_total_return: float
    portfolio_annualized_return: float
    benchmark_annualized_return: float
    annualized_active_return: float
    tracking_error: float
    information_ratio: float
    beta: float
    annualized_alpha: float
    correlation: float
    portfolio_max_drawdown: float
    benchmark_max_drawdown: float
    curves: pd.DataFrame


def analyze_benchmark(
    asset_returns: pd.DataFrame,
    weights,
    benchmark_prices: pd.Series,
    *,
    benchmark_name: str,
    portfolio_name: str = "Cartera",
    risk_free_rate: float = 0.0,
) -> BenchmarkAnalysis:
    """Compare daily-rebalanced portfolio returns with a price benchmark on common dates."""
    name = benchmark_name.strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise PortfolioError("El benchmark requiere un nombre de 1 a 80 caracteres.")
    portfolio_label = portfolio_name.strip()
    if not portfolio_label or len(portfolio_label) > 80 or any(
        ord(char) < 32 for char in portfolio_label
    ):
        raise PortfolioError("La alternativa requiere un nombre de 1 a 80 caracteres.")
    if not np.isfinite(risk_free_rate) or risk_free_rate <= -1:
        raise PortfolioError("La tasa libre de riesgo del benchmark debe ser mayor a -100%.")
    if (
        asset_returns.empty
        or not isinstance(asset_returns.index, pd.DatetimeIndex)
        or asset_returns.index.has_duplicates
        or not asset_returns.index.is_monotonic_increasing
        or asset_returns.columns.has_duplicates
        or not np.isfinite(asset_returns.to_numpy()).all()
        or (asset_returns <= -1).any().any()
    ):
        raise PortfolioError("Los retornos de la cartera no son válidos para el benchmark.")
    weights = validate_weights(weights, asset_returns.shape[1])
    if (
        not isinstance(benchmark_prices, pd.Series)
        or not isinstance(benchmark_prices.index, pd.DatetimeIndex)
        or benchmark_prices.index.has_duplicates
        or not benchmark_prices.index.is_monotonic_increasing
        or not np.isfinite(benchmark_prices.to_numpy(dtype=float)).all()
        or (benchmark_prices <= 0).any()
    ):
        raise PortfolioError("La serie de precios del benchmark debe ser positiva, finita y ordenada.")

    portfolio = pd.Series(
        asset_returns.to_numpy() @ weights,
        index=asset_returns.index,
        name="Cartera",
    )
    benchmark = benchmark_prices.astype(float).pct_change(fill_method=None).dropna()
    benchmark.name = "Benchmark"
    aligned = pd.concat([portfolio, benchmark], axis=1, join="inner").dropna()
    if len(aligned) < MIN_OBSERVATIONS:
        raise PortfolioError(
            f"Sólo hay {len(aligned)} retornos comunes con el benchmark; "
            f"se requieren al menos {MIN_OBSERVATIONS}."
        )
    if (aligned <= -1).any().any() or not np.isfinite(aligned.to_numpy()).all():
        raise PortfolioError("El benchmark contiene retornos incompatibles con un índice de valor.")

    benchmark_variance = float(aligned["Benchmark"].var(ddof=1))
    if benchmark_variance <= 1e-16:
        raise PortfolioError("El benchmark no tiene variación suficiente para estimar beta.")
    active = aligned["Cartera"] - aligned["Benchmark"]
    tracking_error = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS))
    annualized_active = float(active.mean() * TRADING_DAYS)
    information_ratio = (
        annualized_active / tracking_error if tracking_error > 1e-12 else float("nan")
    )
    beta = float(aligned["Cartera"].cov(aligned["Benchmark"]) / benchmark_variance)
    daily_risk_free = (1 + risk_free_rate) ** (1 / TRADING_DAYS) - 1
    alpha = float(
        (
            aligned["Cartera"].mean()
            - daily_risk_free
            - beta * (aligned["Benchmark"].mean() - daily_risk_free)
        )
        * TRADING_DAYS
    )
    correlation = float(aligned["Cartera"].corr(aligned["Benchmark"]))
    curves = (1 + aligned).cumprod()
    curves = pd.concat([
        pd.DataFrame(
            [[1.0, 1.0]],
            index=pd.DatetimeIndex([aligned.index[0] - pd.Timedelta(days=1)]),
            columns=curves.columns,
        ),
        curves,
    ])
    total = curves.iloc[-1] - 1
    years = len(aligned) / TRADING_DAYS
    annualized = (1 + total) ** (1 / years) - 1
    drawdowns = curves / curves.cummax() - 1
    return BenchmarkAnalysis(
        portfolio_name=portfolio_label, name=name,
        observations=len(aligned),
        start=aligned.index[0],
        end=aligned.index[-1],
        portfolio_total_return=float(total["Cartera"]),
        benchmark_total_return=float(total["Benchmark"]),
        portfolio_annualized_return=float(annualized["Cartera"]),
        benchmark_annualized_return=float(annualized["Benchmark"]),
        annualized_active_return=annualized_active,
        tracking_error=tracking_error,
        information_ratio=float(information_ratio),
        beta=beta,
        annualized_alpha=alpha,
        correlation=correlation,
        portfolio_max_drawdown=float(drawdowns["Cartera"].min()),
        benchmark_max_drawdown=float(drawdowns["Benchmark"].min()),
        curves=curves,
    )
