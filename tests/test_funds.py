import numpy as np
import pandas as pd
import pytest

from funds import merge_fund_index, prepare_fund_total_return, read_fund_total_return_csv
from portfolio_core import PortfolioError


def test_fund_total_return_includes_cash_distribution():
    dates = pd.date_range("2026-01-05", periods=4, freq="B")
    observations = pd.DataFrame({
        "Valor": [10.0, 10.1, 9.8, 9.9],
        "Distribucion": [0.0, 0.0, 0.4, 0.0],
    }, index=dates)
    result = prepare_fund_total_return(
        observations,
        share_value_column="Valor",
        distribution_column="Distribucion",
        fund_id="Fondo de prueba",
        series_id="A1",
        currency="MXN",
        name="FONDO_A1",
    )
    assert result.index.iloc[2] / result.index.iloc[1] == pytest.approx((9.8 + 0.4) / 10.1)
    assert result.fund_id == "Fondo de prueba"
    assert result.series_id == "A1"
    assert result.returns.name == "FONDO_A1"


def test_fund_csv_requires_exact_constant_fund_series_and_currency():
    valid = (
        b"Fecha,Fondo,Serie,Moneda,ValorAccion,Distribucion\n"
        b"2026-01-05,Fondo A,A1,MXN,10.0,0\n"
        b"2026-01-06,Fondo A,A1,MXN,10.1,0\n"
        b"2026-01-07,Fondo A,A1,MXN,9.8,0.4\n"
    )
    result = read_fund_total_return_csv(valid, name="FONDO_A1")
    assert result.currency == "MXN"
    mixed_series = valid.replace(b"Fondo A,A1,MXN,9.8", b"Fondo A,B1,MXN,9.8")
    with pytest.raises(PortfolioError, match="una sola serie"):
        read_fund_total_return_csv(mixed_series)
    usd = valid.replace(b",MXN,", b",USD,")
    with pytest.raises(PortfolioError, match="sólo admite"):
        read_fund_total_return_csv(usd)


@pytest.mark.parametrize(
    ("values", "distributions", "message"),
    [
        ([10.0, 0.0, 10.2], [0.0, 0.0, 0.0], "debe ser positivo"),
        ([10.0, 10.1, 10.2], [0.0, -0.1, 0.0], "no pueden ser negativas"),
        ([10.0, 10.1, 10.2], [0.1, 0.0, 0.0], "primera observación"),
    ],
)
def test_fund_rejects_invalid_values(values, distributions, message):
    observations = pd.DataFrame(
        {"Valor": values, "Distribucion": distributions},
        index=pd.date_range("2026-01-05", periods=3, freq="B"),
    )
    with pytest.raises(PortfolioError, match=message):
        prepare_fund_total_return(
            observations,
            share_value_column="Valor",
            distribution_column="Distribucion",
            fund_id="Fondo A",
            series_id="A1",
            currency="MXN",
        )


def test_merge_fund_rejects_internal_gap():
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    market = pd.DataFrame({"A": np.linspace(100, 110, 70)}, index=dates)
    fund = pd.Series(np.linspace(100, 103, 69), index=dates.delete(20), name="FONDO_A1")
    with pytest.raises(PortfolioError, match="fondo omite 1 fecha"):
        merge_fund_index(market, fund)
