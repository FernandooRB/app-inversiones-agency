import numpy as np
import pandas as pd
import pytest

from black_litterman import (
    AbsoluteView,
    black_litterman_posterior,
    parse_absolute_views,
)
from portfolio_core import PortfolioError, optimize_portfolio


@pytest.fixture
def covariance():
    return pd.DataFrame(
        [[0.04, 0.006, 0.002], [0.006, 0.0225, 0.003], [0.002, 0.003, 0.01]],
        index=["AAA", "BBB", "CCC"],
        columns=["AAA", "BBB", "CCC"],
    )


def test_without_views_posterior_equals_equilibrium_prior(covariance):
    result = black_litterman_posterior(covariance, [0.5, 0.3, 0.2], 0.05)
    expected = 0.05 + 2.5 * covariance.to_numpy() @ np.array([0.5, 0.3, 0.2])
    np.testing.assert_allclose(result.prior_returns, expected)
    pd.testing.assert_series_equal(result.posterior_returns, result.prior_returns.rename("Posterior"))


def test_higher_confidence_moves_posterior_closer_to_view(covariance):
    low = black_litterman_posterior(
        covariance, [0.5, 0.3, 0.2], 0.05,
        views=(AbsoluteView("AAA", 0.20, 0.20),),
    )
    high = black_litterman_posterior(
        covariance, [0.5, 0.3, 0.2], 0.05,
        views=(AbsoluteView("AAA", 0.20, 0.90),),
    )
    assert abs(high.posterior_returns["AAA"] - 0.20) < abs(low.posterior_returns["AAA"] - 0.20)
    assert high.posterior_returns["AAA"] > high.prior_returns["AAA"]


def test_equilibrium_prior_recovers_reference_tangency_weights(covariance):
    reference = np.array([0.5, 0.3, 0.2])
    result = black_litterman_posterior(covariance, reference, 0.05, risk_aversion=3.0)
    optimized = optimize_portfolio(result.posterior_returns, covariance, 0.05)
    np.testing.assert_allclose(optimized.weights, reference, atol=2e-5)


def test_parser_accepts_case_and_rejects_bad_rows():
    views = parse_absolute_views("aaa,12.5,60\nCCC,-5,80", ("AAA", "BBB", "CCC"))
    assert views == (AbsoluteView("AAA", 0.125, 0.60), AbsoluteView("CCC", -0.05, 0.80))
    with pytest.raises(PortfolioError, match="más de una"):
        parse_absolute_views("AAA,10,50\nAAA,12,60", ("AAA", "BBB"))
    with pytest.raises(PortfolioError, match="no existe"):
        parse_absolute_views("ZZZ,10,50", ("AAA", "BBB"))
    with pytest.raises(PortfolioError, match="confianza"):
        parse_absolute_views("AAA,10,100", ("AAA", "BBB"))


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"risk_aversion": 0}, "aversión"),
        ({"tau": 0}, "Tau"),
        ({"views": (AbsoluteView("ZZZ", 0.1, 0.5),)}, "activos existentes"),
    ],
)
def test_invalid_model_assumptions_are_rejected(covariance, kwargs, match):
    with pytest.raises(PortfolioError, match=match):
        black_litterman_posterior(covariance, [0.5, 0.3, 0.2], 0.05, **kwargs)


def test_detail_records_only_declared_views(covariance):
    result = black_litterman_posterior(
        covariance, [0.5, 0.3, 0.2], 0.05,
        views=(AbsoluteView("BBB", 0.14, 0.75),),
    )
    assert result.detail.loc[result.detail["Activo"] == "BBB", "Opinión"].item() == 0.14
    assert result.detail["Opinión"].notna().sum() == 1
