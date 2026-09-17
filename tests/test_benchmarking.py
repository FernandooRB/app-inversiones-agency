import numpy as np
import pandas as pd
import pytest

from benchmarking import analyze_benchmark
from portfolio_core import PortfolioError


def sample_data():
    index = pd.date_range("2024-01-02", periods=100, freq="B")
    benchmark_returns = np.linspace(-0.01, 0.012, len(index))
    asset_returns = pd.DataFrame({
        "A": benchmark_returns,
        "B": benchmark_returns * 0.5 + 0.0002,
    }, index=index)
    benchmark_prices = pd.Series(
        100 * np.cumprod(1 + benchmark_returns), index=index, name="IPC"
    )
    return asset_returns, benchmark_prices


def test_identical_portfolio_has_unit_beta_and_zero_active_risk():
    returns, prices = sample_data()
    result = analyze_benchmark(
        returns[["A"]], [1.0], prices,
        benchmark_name="Índice ficticio", risk_free_rate=0.05,
    )
    assert result.observations == 99
    assert result.beta == pytest.approx(1.0)
    assert result.correlation == pytest.approx(1.0)
    assert result.annualized_alpha == pytest.approx(0.0, abs=1e-12)
    assert result.tracking_error == pytest.approx(0.0, abs=1e-12)
    assert np.isnan(result.information_ratio)
    pd.testing.assert_series_equal(
        result.curves["Cartera"], result.curves["Benchmark"], check_names=False
    )


def test_alignment_and_active_metrics_use_only_common_dates():
    returns, prices = sample_data()
    prices = prices.iloc[10:]
    result = analyze_benchmark(
        returns, [0.6, 0.4], prices,
        benchmark_name="IPC ficticio", risk_free_rate=0.04,
    )
    assert result.observations == 89
    assert result.start == prices.index[1]
    assert np.isfinite([
        result.information_ratio, result.beta, result.annualized_alpha,
        result.correlation, result.portfolio_max_drawdown,
        result.benchmark_max_drawdown,
    ]).all()
    assert result.curves.iloc[0].eq(1).all()


@pytest.mark.parametrize(
    "modifier,match",
    [
        (lambda series: series.iloc[:30], "60"),
        (lambda series: pd.Series(100.0, index=series.index), "variación"),
        (lambda series: series.rename_axis(None).set_axis(series.index[::-1]), "ordenada"),
    ],
)
def test_invalid_benchmark_series_is_rejected(modifier, match):
    returns, prices = sample_data()
    with pytest.raises(PortfolioError, match=match):
        analyze_benchmark(returns, [0.5, 0.5], modifier(prices), benchmark_name="IPC")


def test_benchmark_name_is_required():
    returns, prices = sample_data()
    with pytest.raises(PortfolioError, match="nombre"):
        analyze_benchmark(returns, [0.5, 0.5], prices, benchmark_name="")
