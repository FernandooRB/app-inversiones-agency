import numpy as np
import pandas as pd
import pytest

import portfolio_core as core


@pytest.mark.parametrize("weights", [[0.2, 0.2], [float("nan"), 1], [-0.2, 1.2], [[0.5, 0.5]]])
def test_invalid_weights(weights):
    with pytest.raises(core.PortfolioError):
        core.validate_weights(weights, 2)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_prices(value):
    prices = pd.DataFrame({"A": np.arange(100.0, 180.0)})
    prices.iloc[20, 0] = value
    with pytest.raises(core.PortfolioError):
        core.calculate_returns(prices)


def test_compounded_historical_risk():
    returns = pd.DataFrame({"A": [-0.1] * 60})
    risk = core.calculate_risk_metrics(returns, [1], horizon_days=2)
    assert risk.historical_var == pytest.approx(0.19)
    assert risk.historical_cvar == pytest.approx(0.19)


@pytest.mark.parametrize("count,cap", [(1, 1.0), (2, 0.5), (4, 0.25)])
def test_single_feasible_allocation(count, cap):
    means = pd.Series(np.linspace(0.05, 0.15, count))
    covariance = pd.DataFrame(np.eye(count) * 0.04)
    frontier = core.efficient_frontier(means, covariance, max_weight=cap)
    assert len(frontier) == 1


def test_random_cloud_uses_concentration_cap():
    means = pd.Series([0.0, 1.0])
    covariance = pd.DataFrame(np.eye(2))
    cloud = core.random_portfolios(means, covariance, 0, max_weight=0.6)
    assert cloud.Retorno.between(0.4 - 1e-10, 0.6 + 1e-10).all()


def test_constant_prices_do_not_gain_artificial_volatility():
    with pytest.raises(core.PortfolioError):
        core.annualized_moments(pd.DataFrame({"A": [0.0] * 60}))


def test_misaligned_covariance_rejected():
    with pytest.raises(core.PortfolioError):
        core.optimize_portfolio(pd.Series([0.1], index=["A"]), pd.DataFrame([[0.1]]), 0)
