import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError
from simulation import simulate_portfolio_paths


def test_zero_return_cash_flows_and_real_value():
    returns = pd.DataFrame(np.zeros((80, 2)), columns=["A", "B"])
    result = simulate_portfolio_paths(
        returns, [0.6, 0.4], initial_value=1000, months=3, paths=100,
        monthly_contribution=100, inflation_rate=0.12, rebalance_months=3,
    )
    np.testing.assert_allclose(result.monthly_values[:, 0], [1000, 1100, 1200, 1300])
    np.testing.assert_allclose(result.invested_capital, [1000, 1100, 1200, 1300])
    np.testing.assert_allclose(result.real_terminal_values, 1300 / 1.12**0.25)
    assert result.probability_below_contributions == 0


def test_purchase_costs_reduce_initial_and_new_contributions():
    returns = pd.DataFrame(np.zeros((80, 1)), columns=["A"])
    result = simulate_portfolio_paths(
        returns, [1], initial_value=1000, months=2, paths=100,
        monthly_contribution=100, transaction_cost_bps=100,
    )
    np.testing.assert_allclose(result.monthly_values[:, 0], [990, 1089, 1188])
    assert result.probability_below_contributions == 1


@pytest.mark.parametrize("method", ["bootstrap_blocks", "lognormal"])
def test_seed_reproduces_correlated_scenarios(method):
    base = np.sin(np.arange(90)) * 0.01
    returns = pd.DataFrame({"A": base, "B": base})
    kwargs = dict(initial_value=1000, months=3, paths=100, seed=19, method=method)
    first = simulate_portfolio_paths(returns, [1, 0], **kwargs)
    repeated = simulate_portfolio_paths(returns, [1, 0], **kwargs)
    other_asset = simulate_portfolio_paths(returns, [0, 1], **kwargs)
    np.testing.assert_array_equal(first.monthly_values, repeated.monthly_values)
    np.testing.assert_allclose(first.monthly_values, other_asset.monthly_values, atol=1e-9)


def test_rebalancing_trading_cost_reduces_path_value():
    returns = pd.DataFrame({
        "A": np.full(80, 0.01), "B": np.full(80, -0.005),
    })
    kwargs = dict(initial_value=1000, months=3, paths=100, rebalance_months=3)
    free = simulate_portfolio_paths(returns, [0.5, 0.5], **kwargs)
    charged = simulate_portfolio_paths(
        returns, [0.5, 0.5], transaction_cost_bps=100, **kwargs
    )
    assert (charged.monthly_values[-1] < free.monthly_values[-1]).all()


def test_invalid_return_and_horizon_are_rejected():
    returns = pd.DataFrame(np.zeros((80, 1)), columns=["A"])
    returns.iloc[0, 0] = -1
    with pytest.raises(PortfolioError, match="mayores a -100"):
        simulate_portfolio_paths(returns, [1], initial_value=1000, months=12)
    returns.iloc[0, 0] = 0
    with pytest.raises(PortfolioError, match="horizonte"):
        simulate_portfolio_paths(returns, [1], initial_value=1000, months=121)
