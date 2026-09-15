import numpy as np
import pandas as pd
import pytest

from backtesting import run_holdout_backtest
from portfolio_core import PortfolioError


def regime_returns() -> pd.DataFrame:
    rng = np.random.default_rng(432)
    training = rng.normal([0.0025, 0.0004], [0.005, 0.005], size=(140, 2))
    evaluation = rng.normal([-0.0030, 0.0004], [0.005, 0.005], size=(60, 2))
    return pd.DataFrame(
        np.vstack([training, evaluation]),
        index=pd.date_range("2024-01-02", periods=200, freq="B"),
        columns=["A", "B"],
    )


def test_evaluation_changes_do_not_change_training_allocations():
    first = regime_returns()
    second = first.copy()
    second.iloc[140:, 0] += 0.02
    baseline = run_holdout_backtest(first, training_fraction=0.70, max_weight=1.0)
    changed = run_holdout_backtest(second, training_fraction=0.70, max_weight=1.0)
    pd.testing.assert_frame_equal(baseline.allocations, changed.allocations)
    assert not baseline.summary.equals(changed.summary)
    assert baseline.training_end < baseline.evaluation_start
    assert baseline.training_observations == 140
    assert baseline.evaluation_observations == 60


def test_regime_reversal_can_make_optimized_portfolio_worse_than_equal_weights():
    result = run_holdout_backtest(regime_returns(), training_fraction=0.70, max_weight=1.0)
    assert result.allocations.loc["A", "Máximo Sharpe"] > 0.5
    assert (
        result.summary.loc["Máximo Sharpe", "Retorno total neto"]
        < result.summary.loc["Pesos iguales", "Retorno total neto"]
    )


def test_entry_cost_uses_current_portfolio_turnover_and_no_rebalancing():
    returns = regime_returns()
    current = np.array([0.25, 0.75])
    gross = run_holdout_backtest(
        returns, training_fraction=0.70, current_weights=current
    )
    net = run_holdout_backtest(
        returns, training_fraction=0.70, current_weights=current,
        trading_cost_bps=100,
    )
    for scenario in net.summary.index:
        assert net.summary.loc[scenario, "Retorno total neto"] <= gross.summary.loc[
            scenario, "Retorno total neto"
        ]
    assert net.summary.loc["Cartera actual", "Costo inicial sobre capital"] == 0
    assert net.summary.loc["Máximo Sharpe", "Rotación inicial"] == pytest.approx(
        0.5 * np.abs(net.allocations["Máximo Sharpe"].to_numpy() - current).sum()
    )
    assert net.equity_curves.iloc[0].eq(1).all()


def test_holdout_rejects_too_little_evaluation_data():
    with pytest.raises(PortfolioError, match="20 para evaluación"):
        run_holdout_backtest(regime_returns().iloc[:70], training_fraction=0.90)
