import numpy as np
import pandas as pd
import pytest

from fx_comparison import compare_series, fixed_metrics, read_reference
from portfolio_core import PortfolioError


@pytest.mark.parametrize("data", [
    b"Date,USDMXN\n2024-01-02,-1",
    b"Date,USDMXN\n2024-01-02,NaN",
    b"Date,USDMXN\n2024-01-02,17\n2024-01-02,18",
    b"Date,USDMXN\n02/01/2024,17",
    b"Date,Other\n2024-01-02,17",
])
def test_reference_rejects_ambiguous_or_invalid_data(data):
    with pytest.raises(PortfolioError):
        read_reference(data)


def test_alignment_uses_intersection_without_filling():
    prices = pd.DataFrame({"A": [10., 11., 12.]}, index=pd.date_range("2024-01-01", periods=3))
    yahoo = pd.Series([17., 18., 19.], index=prices.index)
    reference = read_reference(b"Date,USDMXN\n2024-01-03,20\n2024-01-01,16")
    table, baseline, alternative = compare_series(prices, yahoo, reference)
    assert len(table) == 2
    assert baseline.index.equals(alternative.index)
    assert baseline["A"].tolist() == [170., 228.]
    assert alternative["A"].tolist() == [160., 240.]
    assert table.iloc[0]["Diferencia relativa"] == pytest.approx(17 / 16 - 1)


def test_constant_fx_rescaling_does_not_change_returns_or_risk():
    rng = np.random.default_rng(21)
    prices = pd.DataFrame(100 * np.cumprod(1 + rng.normal(.001, .01, (80, 2)), axis=0))
    first = fixed_metrics(prices * 17, [.3, .7], .03, .95, 5)
    second = fixed_metrics(prices * 20, [.3, .7], .03, .95, 5)
    for key in first:
        assert first[key] == pytest.approx(second[key], abs=1e-10)
