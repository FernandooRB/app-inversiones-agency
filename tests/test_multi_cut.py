import numpy as np
import pandas as pd
import pytest

from covariance_calibration import CANDIDATES
from multi_cut import run_multi_cut_backtest
from portfolio_core import PortfolioError


def regime_returns() -> pd.DataFrame:
    rng = np.random.default_rng(240)
    early = rng.normal([0.0015, 0.0001], [0.008, 0.008], size=(150, 2))
    late = rng.normal([-0.0015, 0.0008], [0.008, 0.008], size=(150, 2))
    return pd.DataFrame(
        np.vstack([early, late]),
        index=pd.date_range("2023-01-02", periods=300, freq="B"),
        columns=["A", "B"],
    )


def test_four_cuts_have_disjoint_train_eval_and_paired_equal_weight_differences():
    result = run_multi_cut_backtest(regime_returns(), current_weights=np.array([0.2, 0.8]))
    assert tuple(result.results) == ("50%", "60%", "70%", "80%")
    assert result.summary.index.names == ["Corte inicial", "Escenario"]
    for cut, holdout in result.results.items():
        assert holdout.training_end < holdout.evaluation_start
        assert holdout.training_observations + holdout.evaluation_observations == 300
        assert holdout.equity_curves.iloc[0].eq(1).all()
        equal = result.summary.loc[(cut, "Pesos iguales"), "Retorno total neto"]
        maximum = result.summary.loc[(cut, "Máximo Sharpe")]
        assert maximum["Diferencia total neta vs pesos iguales"] == pytest.approx(
            maximum["Retorno total neto"] - equal
        )
        assert result.summary.loc[
            (cut, "Pesos iguales"), "Diferencia total neta vs pesos iguales"
        ] == 0
    for _, group in result.allocations.groupby(level="Corte inicial"):
        assert group["Pesos iguales"].sum() == pytest.approx(1)


def test_future_change_cannot_change_weights_at_first_cut():
    original = regime_returns()
    changed = original.copy()
    changed.iloc[150:, 0] += 0.02
    first = run_multi_cut_backtest(original)
    altered = run_multi_cut_backtest(changed)
    pd.testing.assert_frame_equal(
        first.results["50%"].allocations,
        altered.results["50%"].allocations,
    )
    assert not first.results["50%"].equity_curves.equals(
        altered.results["50%"].equity_curves
    )


def test_calibrated_covariance_uses_each_cuts_training_history():
    result = run_multi_cut_backtest(regime_returns(), covariance_shrinkage="cv")
    for cut, holdout in result.results.items():
        assert holdout.covariance_shrinkage in CANDIDATES
        assert result.summary.loc[
            (cut, "Máximo Sharpe"), "Contracción de covarianza"
        ] == holdout.covariance_shrinkage


def test_four_cuts_reject_short_or_unordered_series():
    returns = regime_returns()
    with pytest.raises(PortfolioError, match="120 retornos"):
        run_multi_cut_backtest(returns.iloc[:119])
    with pytest.raises(PortfolioError, match="200 retornos"):
        run_multi_cut_backtest(returns.iloc[:199], covariance_shrinkage="cv")
    with pytest.raises(PortfolioError, match="fechas únicas y ordenadas"):
        run_multi_cut_backtest(returns.iloc[::-1])
