"""Shared allocation calculation, independent of widgets and report generation."""

from dataclasses import dataclass

import pandas as pd

from model_estimation import DEFAULT_METHOD, MomentEstimate, estimate_moments
from portfolio_core import (
    PortfolioMetrics,
    calculate_returns,
    efficient_frontier,
    optimize_portfolio,
    random_portfolios,
)


@dataclass(frozen=True)
class AllocationAnalysis:
    returns: pd.DataFrame
    moments: MomentEstimate
    max_sharpe: PortfolioMetrics
    min_volatility: PortfolioMetrics
    frontier: pd.DataFrame | None
    random_set: pd.DataFrame | None


def calculate_allocation(
    prices, risk_free_rate, max_weight, allocation_groups=(), method=DEFAULT_METHOD, *, chart_data=True
):
    returns = calculate_returns(prices)
    moments = estimate_moments(returns, method)
    mean, covariance = moments.mean, moments.covariance
    return AllocationAnalysis(
        returns,
        moments,
        optimize_portfolio(mean, covariance, risk_free_rate, "max_sharpe", max_weight, allocation_groups),
        optimize_portfolio(mean, covariance, risk_free_rate, "min_volatility", max_weight, allocation_groups),
        efficient_frontier(mean, covariance, max_weight, allocation_groups=allocation_groups)
        if chart_data
        else None,
        random_portfolios(
            mean, covariance, risk_free_rate, max_weight=max_weight, allocation_groups=allocation_groups
        )
        if chart_data
        else None,
    )
