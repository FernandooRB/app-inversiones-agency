import numpy as np
import pandas as pd
import pytest

from fixed_income import cetes_price, prepare_cetes_total_return, read_banxico_cetes_csv
from portfolio_core import PortfolioError


def test_cetes_price_matches_official_formula_example_shape():
    assert cetes_price(0.10, 28) == pytest.approx(10 / (1 + 0.10 * 28 / 360))
    values = cetes_price(np.array([0.10, 0.11]), np.array([28, 91]))
    assert values.shape == (2,)
    assert np.all(values < 10)


def test_total_return_accrues_and_redeems_at_maturity():
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-08"])
    observations = pd.DataFrame(
        {"Precio": [9.90, 9.95, 9.60], "Plazo": [3, 2, 28]}, index=dates
    )
    result = prepare_cetes_total_return(
        observations, price_column="Precio", term_column="Plazo", name="CETES28"
    )
    assert result.index.iloc[-1] == pytest.approx(100 * 10 / 9.90)
    assert result.roll_dates == (pd.Timestamp("2026-01-08"),)
    assert result.maturity_dates == (pd.Timestamp("2026-01-08"),)
    assert result.returns.name == "CETES28"


def test_early_reference_change_does_not_create_artificial_price_loss():
    dates = pd.date_range("2026-01-05", periods=3, freq="B")
    observations = pd.DataFrame(
        {"price": [9.80, 9.81, 9.60], "term": [20, 19, 28]}, index=dates
    )
    result = prepare_cetes_total_return(
        observations, price_column="price", term_column="term"
    )
    assert result.index.iloc[-1] == pytest.approx(100 * 9.81 / 9.80)
    assert result.roll_dates == (dates[-1],)
    assert not result.maturity_dates


def test_csv_adapter_reads_banxico_style_columns():
    contents = (
        b"Fecha,Precio Limpio,Plazo\n"
        b"05/01/2026,9.90,3\n"
        b"06/01/2026,9.95,2\n"
        b"08/01/2026,9.60,28\n"
    )
    result = read_banxico_cetes_csv(
        contents, date_column="Fecha", price_column="Precio Limpio", term_column="Plazo"
    )
    assert len(result.index) == 3


@pytest.mark.parametrize(
    "frame,message",
    [
        (pd.DataFrame({"p": [1, 2], "t": [2, 1]}), "fechas"),
        (
            pd.DataFrame(
                {"p": [9.8, -1, 9.9], "t": [3, 2, 1]},
                index=pd.date_range("2026-01-01", periods=3),
            ),
            "positivos",
        ),
    ],
)
def test_total_return_rejects_invalid_observations(frame, message):
    with pytest.raises(PortfolioError, match=message):
        prepare_cetes_total_return(frame, price_column="p", term_column="t")
