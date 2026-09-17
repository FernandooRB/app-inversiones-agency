import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError
from risk_attribution import attribute_volatility


def test_diagonal_covariance_has_analytical_euler_contributions():
    covariance = pd.DataFrame(
        [[0.04, 0.0], [0.0, 0.01]], index=["A", "B"], columns=["A", "B"]
    )
    result = attribute_volatility(
        covariance, [0.5, 0.5], alternative_name="Pesos iguales"
    )
    expected_volatility = np.sqrt(0.0125)
    assert result.portfolio_volatility == pytest.approx(expected_volatility)
    np.testing.assert_allclose(
        result.detail["% contribución a volatilidad"], [0.8, 0.2]
    )
    assert result.detail["Contribución a volatilidad"].sum() == pytest.approx(
        expected_volatility
    )
    assert result.effective_positions == pytest.approx(2.0)
    assert result.effective_risk_contributors == pytest.approx(1 / (0.8**2 + 0.2**2))


def test_perfect_positive_dependence_has_no_diversification_benefit():
    volatilities = np.array([0.20, 0.10, 0.05])
    covariance = pd.DataFrame(
        np.outer(volatilities, volatilities),
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    result = attribute_volatility(covariance, [0.5, 0.3, 0.2], alternative_name="Cartera")
    assert result.diversification_ratio == pytest.approx(1.0)


def test_negative_component_is_preserved_but_absolute_shares_sum_to_one():
    covariance = pd.DataFrame(
        [[0.04, -0.015], [-0.015, 0.01]], index=["A", "B"], columns=["A", "B"]
    )
    result = attribute_volatility(covariance, [0.2, 0.8], alternative_name="Cobertura")
    assert (result.detail["Contribución a volatilidad"] < 0).any()
    assert result.detail["% absoluto del riesgo"].sum() == pytest.approx(1.0)
    assert result.detail["% contribución a volatilidad"].sum() == pytest.approx(1.0)


def test_invalid_labels_weights_and_zero_risk_are_rejected():
    covariance = pd.DataFrame(np.eye(2), index=["A", "B"], columns=["A", "B"])
    with pytest.raises(PortfolioError, match="Pesos inválidos"):
        attribute_volatility(covariance, [1.0, 1.0], alternative_name="Cartera")
    with pytest.raises(PortfolioError, match="etiquetas"):
        attribute_volatility(
            covariance.rename(columns={"B": "C"}), [0.5, 0.5], alternative_name="Cartera"
        )
    zero = pd.DataFrame(np.zeros((2, 2)), index=["A", "B"], columns=["A", "B"])
    with pytest.raises(PortfolioError, match="demasiado pequeña"):
        attribute_volatility(zero, [0.5, 0.5], alternative_name="Cartera")
