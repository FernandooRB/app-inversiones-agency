from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError, calculate_returns
from price_upload import read_adjusted_price_csv


def sample_csv(rows: int = 80) -> bytes:
    dates = pd.date_range("2024-01-02", periods=rows, freq="B")
    lines = ["Fecha,B,A"]
    lines.extend(
        f"{day.date().isoformat()},{100 + number * 0.2:.2f},{50 + number * 0.1:.2f}"
        for number, day in enumerate(dates)
    )
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def test_import_reorders_tickers_filters_dates_and_preserves_returns():
    result = read_adjusted_price_csv(
        sample_csv(), ("A", "B"), date(2024, 1, 2), date(2024, 4, 30)
    )
    assert result.valid_tickers == ("A", "B")
    assert result.rejected_tickers == ()
    assert list(result.prices) == ["A", "B"]
    assert len(result.prices) == 80
    assert result.prices.iloc[0].tolist() == [50.0, 100.0]
    assert len(calculate_returns(result.prices)) == 79
    assert np.isfinite(result.prices.to_numpy()).all()


def test_import_rejects_missing_price_instead_of_silently_dropping_date():
    missing = sample_csv().decode("utf-8-sig").replace(",101.00,50.50", ",,50.50")
    with pytest.raises(PortfolioError, match="Precio faltante"):
        read_adjusted_price_csv(
            missing.encode(), ("A", "B"), date(2024, 1, 2), date(2024, 4, 30)
        )


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (("Fecha,B,A", "Fecha,B,C"), "exactamente una columna"),
        (("2024-01-02,100.00,50.00", "2024-01-02,0,50.00"), "positivos"),
        (("2024-01-03,100.20,50.10", "2024-01-02,100.20,50.10"), "únicas"),
    ],
)
def test_import_rejects_invalid_symbols_prices_or_dates(replacement, message):
    changed = sample_csv().decode("utf-8-sig").replace(*replacement)
    with pytest.raises(PortfolioError, match=message):
        read_adjusted_price_csv(
            changed.encode(), ("A", "B"), date(2024, 1, 2), date(2024, 4, 30)
        )


def test_import_requires_60_prices_inside_requested_period():
    with pytest.raises(PortfolioError, match="60"):
        read_adjusted_price_csv(
            sample_csv(), ("A", "B"), date(2024, 1, 2), date(2024, 3, 15)
        )


def test_import_rejects_weekly_series_as_non_daily():
    dates = pd.date_range("2023-01-02", periods=80, freq="W-MON")
    weekly = "Fecha,A,B\n" + "\n".join(
        f"{day.date().isoformat()},100,200" for day in dates
    )
    with pytest.raises(PortfolioError, match="sesiones diarias"):
        read_adjusted_price_csv(
            weekly.encode(), ("A", "B"), date(2023, 1, 1), date(2024, 12, 31)
        )


def test_import_rejects_a_long_internal_gap():
    lines = sample_csv().decode("utf-8-sig").splitlines()
    with_gap = "\n".join(lines[:30] + lines[40:])
    with pytest.raises(PortfolioError, match="sesiones diarias"):
        read_adjusted_price_csv(
            with_gap.encode(), ("A", "B"), date(2024, 1, 2), date(2024, 4, 30)
        )
