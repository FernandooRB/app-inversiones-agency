import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError
from walk_forward import run_walk_forward_backtest


def sample_returns() -> pd.DataFrame:
    rng = np.random.default_rng(332)
    observations = rng.normal([0.0008, 0.0003], [0.008, 0.006], size=(520, 2))
    return pd.DataFrame(
        observations, index=pd.date_range("2023-01-02", periods=520, freq="B"),
        columns=["A", "B"],
    )


def test_future_change_cannot_change_prior_review_weights():
    first = sample_returns()
    altered = first.copy()
    altered.iloc[450:, 0] += 0.02
    original = run_walk_forward_backtest(first, training_fraction=0.6)
    changed = run_walk_forward_backtest(altered, training_fraction=0.6)
    early = original.allocation_history.loc[
        original.allocation_history.index.get_level_values(0) < first.index[450]
    ]
    changed_early = changed.allocation_history.loc[
        changed.allocation_history.index.get_level_values(0) < first.index[450]
    ]
    pd.testing.assert_frame_equal(early, changed_early)
    assert (original.allocation_history.index.get_level_values(0)
            > original.allocation_history["Estimación hasta"].to_numpy()).all()
    assert not original.equity_curves.equals(changed.equity_curves)


def test_review_schedule_and_cost_apply_to_drifted_portfolio():
    returns = sample_returns()
    baseline = np.array([0.2, 0.8])
    gross = run_walk_forward_backtest(
        returns, training_fraction=0.6, current_weights=baseline,
        cadence_months=3,
    )
    net = run_walk_forward_backtest(
        returns, training_fraction=0.6, current_weights=baseline,
        cadence_months=3, trading_cost_bps=100,
    )
    reviews = net.allocation_history.xs("Pesos iguales", level="Escenario")
    assert len(reviews) >= 3
    assert reviews.index[1] >= reviews.index[0] + pd.DateOffset(months=3)
    assert reviews.iloc[0]["Rotación"] == pytest.approx(0.3)
    assert reviews.iloc[1]["Rotación"] > 0
    assert net.summary.loc["Pesos iguales", "Costo pagado sobre capital inicial"] > 0.003
    assert net.summary.loc["Cartera actual sin rebalanceo", "Rotación acumulada"] == 0
    assert net.equity_curves.iloc[0].eq(1).all()
    for name in net.equity_curves:
        assert net.equity_curves[name].iloc[-1] <= gross.equity_curves[name].iloc[-1]


def test_cadence_and_return_validations():
    returns = sample_returns()
    with pytest.raises(PortfolioError, match="3, 6 o 12"):
        run_walk_forward_backtest(returns, cadence_months=1)
    with pytest.raises(PortfolioError, match="fechas únicas y ordenadas"):
        run_walk_forward_backtest(returns.iloc[::-1])
