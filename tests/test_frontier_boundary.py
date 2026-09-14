import numpy as np
import pandas as pd
import pytest

from portfolio_core import efficient_frontier, optimize_portfolio


def test_highest_return_is_also_minimum_risk_at_cap():
    means = pd.Series([0.47, 0.59], index=["A", "B"])
    covariance = pd.DataFrame([[0.09, 0.025], [0.025, 0.01]], index=means.index, columns=means.index)
    frontier = efficient_frontier(means, covariance, max_weight=0.7)
    minimum = optimize_portfolio(means, covariance, 0.03, "min_volatility", 0.7)
    assert np.allclose(minimum.weights, [0.3, 0.7], atol=1e-6)
    assert len(frontier) == 1
    assert frontier.iloc[0]["Retorno"] == pytest.approx(0.3 * 0.47 + 0.7 * 0.59)
    assert frontier.iloc[0]["Volatilidad"] == pytest.approx(minimum.annual_volatility)


def test_frontier_retains_tradeoff_when_higher_return_requires_more_risk():
    means = pd.Series([0.05, 0.20], index=["A", "B"])
    covariance = pd.DataFrame([[0.01, 0.0], [0.0, 0.09]], index=means.index, columns=means.index)
    frontier = efficient_frontier(means, covariance, max_weight=0.7, points=10)
    assert len(frontier) > 1
    assert frontier["Retorno"].is_monotonic_increasing
    assert frontier.iloc[-1]["Volatilidad"] > frontier.iloc[0]["Volatilidad"]
