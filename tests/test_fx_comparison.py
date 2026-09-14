from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fx_comparison import compare_series, fixed_metrics, internal_missing_dates, read_reference
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
    assert list(internal_missing_dates(prices, table.index)) == [prices.index[1]]


def test_full_h10_reference_matches_documented_observations():
    path = Path(__file__).resolve().parents[1] / "docs/fx_reference_fed_h10_2024h1.csv"
    reference = read_reference(path.read_bytes())
    assert len(reference) == 125
    assert reference.index.min() == pd.Timestamp("2024-01-02")
    assert reference.index.max() == pd.Timestamp("2024-06-28")
    assert reference.loc["2024-01-02"] == pytest.approx(17.0140)
    assert reference.loc["2024-06-03"] == pytest.approx(17.5780)
    assert reference.loc["2024-06-28"] == pytest.approx(18.2610)


def test_constant_fx_rescaling_does_not_change_returns_or_risk():
    rng = np.random.default_rng(21)
    prices = pd.DataFrame(100 * np.cumprod(1 + rng.normal(.001, .01, (80, 2)), axis=0))
    first = fixed_metrics(prices * 17, [.3, .7], .03, .95, 5)
    second = fixed_metrics(prices * 20, [.3, .7], .03, .95, 5)
    for key in first:
        assert first[key] == pytest.approx(second[key], abs=1e-10)
