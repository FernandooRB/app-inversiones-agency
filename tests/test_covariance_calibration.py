import numpy as np
import pandas as pd
import pytest

from backtesting import run_holdout_backtest
from covariance_calibration import CANDIDATES, select_diagonal_shrinkage
from portfolio_core import PortfolioError
from walk_forward import run_walk_forward_backtest


def changing_covariance_returns() -> pd.DataFrame:
    rng = np.random.default_rng(913)
    common = rng.normal(0, 0.01, 500)
    b = common + rng.normal(0, 0.003, 500)
    b[250:] = -common[250:] + rng.normal(0, 0.003, 250)
    return pd.DataFrame(
        np.column_stack([common + 0.0002, b + 0.0002]),
        index=pd.date_range("2022-01-03", periods=500, freq="B"),
        columns=["A", "B"],
    )


def test_calibration_uses_nonoverlapping_prior_validation_blocks():
    returns = changing_covariance_returns().iloc[:350]
    result = select_diagonal_shrinkage(returns)
    assert result.intensity in CANDIDATES
    assert len(result.fold_scores) == 4
    assert result.fold_scores["Validación hasta"].max() <= returns.index[-1]
    assert (
        result.fold_scores["Estimación hasta"]
        < result.fold_scores["Validación desde"]
    ).all()
    for current, following in zip(
        result.fold_scores["Validación hasta"].iloc[:-1],
        result.fold_scores["Validación desde"].iloc[1:], strict=True,
    ):
        assert current < following
    selected_label = f"{result.intensity:.0%}"
    assert result.mean_scores[selected_label] == pytest.approx(result.mean_scores.min())


def test_outer_evaluation_change_does_not_change_calibrated_initial_allocation():
    original = changing_covariance_returns()
    altered = original.copy()
    altered.iloc[350:, 0] += 0.02
    first = run_holdout_backtest(
        original, training_fraction=0.7, covariance_shrinkage="cv"
    )
    changed = run_holdout_backtest(
        altered, training_fraction=0.7, covariance_shrinkage="cv"
    )
    assert first.covariance_shrinkage == changed.covariance_shrinkage
    pd.testing.assert_frame_equal(first.allocations, changed.allocations)
    assert not first.equity_curves.equals(changed.equity_curves)


def test_future_returns_do_not_change_prior_calibrated_reviews():
    original = changing_covariance_returns()
    altered = original.copy()
    altered.iloc[450:, 0] += 0.02
    first = run_walk_forward_backtest(
        original, training_fraction=0.6, covariance_shrinkage="cv"
    )
    changed = run_walk_forward_backtest(
        altered, training_fraction=0.6, covariance_shrinkage="cv"
    )
    early = first.allocation_history.loc[
        first.allocation_history.index.get_level_values(0) < original.index[450]
    ]
    changed_early = changed.allocation_history.loc[
        changed.allocation_history.index.get_level_values(0) < original.index[450]
    ]
    pd.testing.assert_frame_equal(early, changed_early)
    assert early["Contracción de covarianza"].isin(CANDIDATES).all()


def test_calibration_rejects_insufficient_or_unordered_training_data():
    returns = changing_covariance_returns()
    with pytest.raises(PortfolioError, match="100 retornos"):
        select_diagonal_shrinkage(returns.iloc[:99])
    with pytest.raises(PortfolioError, match="fechas únicas y ordenadas"):
        select_diagonal_shrinkage(returns.iloc[::-1])
