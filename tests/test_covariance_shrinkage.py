import numpy as np
import pandas as pd
import pytest

from backtesting import run_holdout_backtest
from portfolio_core import PortfolioError, annualized_moments
from walk_forward import run_walk_forward_backtest


def correlated_returns() -> pd.DataFrame:
    rng = np.random.default_rng(730)
    shared = rng.normal(0, 0.01, 500)
    values = np.column_stack([
        shared + rng.normal(0, 0.003, 500) + 0.0003,
        1.5 * shared + rng.normal(0, 0.005, 500) + 0.0003,
        -0.5 * shared + rng.normal(0, 0.008, 500) + 0.0003,
    ])
    return pd.DataFrame(
        values, index=pd.date_range("2023-01-02", periods=500, freq="B"),
        columns=["A", "B", "C"],
    )


def test_diagonal_shrinkage_halves_cross_covariance_and_preserves_variances():
    returns = correlated_returns()
    mean, sample = annualized_moments(returns)
    shrunk_mean, shrunk = annualized_moments(returns, covariance_shrinkage=0.5)
    pd.testing.assert_series_equal(mean, shrunk_mean)
    np.testing.assert_allclose(np.diag(sample), np.diag(shrunk))
    np.testing.assert_allclose(shrunk.loc["A", "B"], 0.5 * sample.loc["A", "B"])
    assert np.linalg.eigvalsh(shrunk.to_numpy()).min() > 0
    with pytest.raises(PortfolioError, match="0% y 100%"):
        annualized_moments(returns, covariance_shrinkage=1.5)


def test_holdout_estimators_use_same_evaluation_and_equal_weight_benchmark():
    returns = correlated_returns()
    sample = run_holdout_backtest(returns, training_fraction=0.7, trading_cost_bps=50)
    diagonal = run_holdout_backtest(
        returns, training_fraction=0.7, trading_cost_bps=50,
        covariance_shrinkage=0.5,
    )
    assert sample.evaluation_start == diagonal.evaluation_start
    assert sample.evaluation_end == diagonal.evaluation_end
    pd.testing.assert_series_equal(
        sample.equity_curves["Pesos iguales"], diagonal.equity_curves["Pesos iguales"]
    )
    assert not np.allclose(
        sample.allocations["Mínima volatilidad"],
        diagonal.allocations["Mínima volatilidad"],
    )


def test_walk_forward_shrinkage_uses_only_returns_before_each_review():
    returns = correlated_returns()
    changed = returns.copy()
    changed.iloc[450:, 0] += 0.02
    original = run_walk_forward_backtest(
        returns, training_fraction=0.6, covariance_shrinkage=0.5
    )
    altered = run_walk_forward_backtest(
        changed, training_fraction=0.6, covariance_shrinkage=0.5
    )
    early = original.allocation_history.loc[
        original.allocation_history.index.get_level_values(0) < returns.index[450]
    ]
    changed_early = altered.allocation_history.loc[
        altered.allocation_history.index.get_level_values(0) < returns.index[450]
    ]
    pd.testing.assert_frame_equal(early, changed_early)
    assert original.equity_curves.index.equals(altered.equity_curves.index)
