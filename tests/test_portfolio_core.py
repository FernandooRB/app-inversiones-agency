from datetime import date

import numpy as np
import pandas as pd
import pytest

import portfolio_core as core


@pytest.fixture
def returns():
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        rng.normal(loc=[0.0005, 0.0003, 0.0002], scale=[0.012, 0.008, 0.006], size=(500, 3)),
        columns=["AAA", "BBB", "CCC"],
    )


def test_normalize_tickers_deduplicates_and_uppercases():
    assert core.normalize_tickers(" aapl, MSFT, aapl ") == ["AAPL", "MSFT"]


def test_normalize_tickers_rejects_unsafe_characters():
    with pytest.raises(core.PortfolioError, match="formato inválido"):
        core.normalize_tickers("AAPL; DROP TABLE")


def test_current_weights_accepts_rounding_and_rejects_bad_totals():
    weights = core.parse_current_weights("33.33, 33.33, 33.33", 3)
    assert weights.sum() == pytest.approx(1.0)
    with pytest.raises(core.PortfolioError, match="sumar 100"):
        core.parse_current_weights("60, 30, 5", 3)


def test_download_uses_adjusted_prices_and_reports_rejected(monkeypatch):
    index = pd.date_range("2024-01-01", periods=80, freq="B")
    columns = pd.MultiIndex.from_product([["Close"], ["AAA", "BAD"]])
    values = np.column_stack([np.linspace(100, 120, 80), np.full(80, np.nan)])
    supplied = pd.DataFrame(values, index=index, columns=columns)
    captured = {}

    def fake_download(*args, **kwargs):
        captured.update(kwargs)
        return supplied

    monkeypatch.setattr(core.yf, "download", fake_download)
    result = core.download_adjusted_prices(["AAA", "BAD"], date(2024, 1, 1), date(2024, 4, 30))
    assert captured["auto_adjust"] is True
    assert captured["end"] == "2024-05-01"
    assert result.valid_tickers == ("AAA",)
    assert result.rejected_tickers == ("BAD",)


def test_optimization_respects_budget_and_concentration(returns):
    means, covariance = core.annualized_moments(returns)
    result = core.optimize_portfolio(means, covariance, 0.04, max_weight=0.5)
    assert result.weights.sum() == pytest.approx(1.0)
    assert result.weights.min() >= -1e-9
    assert result.weights.max() <= 0.5 + 1e-7
    assert np.isfinite(result.sharpe_ratio)


def test_minimum_volatility_is_not_riskier_than_equal_weight(returns):
    means, covariance = core.annualized_moments(returns)
    result = core.optimize_portfolio(means, covariance, 0.04, "min_volatility")
    _, equal_volatility, _ = core.portfolio_statistics(np.full(3, 1 / 3), means, covariance, 0.04)
    assert result.annual_volatility <= equal_volatility + 1e-8


def test_efficient_frontier_has_ordered_returns(returns):
    means, covariance = core.annualized_moments(returns)
    frontier = core.efficient_frontier(means, covariance, max_weight=0.7, points=12)
    assert len(frontier) >= 2
    assert frontier["Retorno"].is_monotonic_increasing
    assert (frontier["Volatilidad"] >= 0).all()


def test_random_portfolios_are_reproducible(returns):
    means, covariance = core.annualized_moments(returns)
    first = core.random_portfolios(means, covariance, 0.04, simulations=20, seed=9)
    second = core.random_portfolios(means, covariance, 0.04, simulations=20, seed=9)
    pd.testing.assert_frame_equal(first, second)


def test_risk_metrics_are_positive_loss_magnitudes(returns):
    risk = core.calculate_risk_metrics(returns, np.full(3, 1 / 3), 0.95, 5)
    assert risk.parametric_var >= 0
    assert risk.historical_var >= 0
    assert risk.historical_cvar >= risk.historical_var


def test_infeasible_weight_limit_is_rejected(returns):
    means, covariance = core.annualized_moments(returns)
    with pytest.raises(core.PortfolioError, match="peso máximo"):
        core.optimize_portfolio(means, covariance, 0.04, max_weight=0.2)
