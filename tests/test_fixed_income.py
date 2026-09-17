import numpy as np
import pandas as pd
import pytest

from fixed_income import (
    cetes_price,
    merge_bond_index,
    merge_cetes_index,
    prepare_bond_total_return,
    prepare_cetes_total_return,
    read_banxico_cetes_csv,
    read_bond_total_return_csv,
)
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


def test_early_reference_change_requires_issue_level_sale_price():
    dates = pd.date_range("2026-01-05", periods=3, freq="B")
    observations = pd.DataFrame(
        {"price": [9.80, 9.81, 9.60], "term": [20, 19, 28]}, index=dates
    )
    with pytest.raises(PortfolioError, match="antes de vencer"):
        prepare_cetes_total_return(observations, price_column="price", term_column="term")


def test_shorter_term_can_also_signal_an_early_issue_change():
    dates = pd.date_range("2026-01-05", periods=3, freq="B")
    observations = pd.DataFrame(
        {"price": [9.80, 9.81, 9.90], "term": [28, 27, 20]}, index=dates
    )
    with pytest.raises(PortfolioError, match="2026-01-07"):
        prepare_cetes_total_return(observations, price_column="price", term_column="term")


def test_missing_cetes_calendar_day_does_not_mimic_early_switch():
    dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-09"])
    observations = pd.DataFrame(
        {"price": [9.80, 9.81, 9.84], "term": [28, 27, 24]}, index=dates
    )
    result = prepare_cetes_total_return(observations, price_column="price", term_column="term")
    assert result.index.iloc[-1] == pytest.approx(100 * 9.84 / 9.80)
    assert not result.roll_dates


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


def test_official_cf300_28_day_observations_match_valuation_and_calendar():
    # Transcription of Banxico CF300, observed 2026-09-10, 11 and 14.
    official = (
        b"Fecha,Precio,Plazo,Tasa\n"
        b"10/09/2026,9.949391,28,6.539970\n"
        b"11/09/2026,9.951346,27,6.518917\n"
        b"14/09/2026,9.956812,24,6.506299\n"
    )
    result = read_banxico_cetes_csv(
        official, date_column="Fecha", price_column="Precio", term_column="Plazo"
    )
    assert result.index.iloc[-1] == pytest.approx(100 * 9.956812 / 9.949391)
    assert result.roll_dates == ()


def test_csv_adapter_rejects_wrong_rate_units_and_missing_price():
    wrong_rate = (
        b"Fecha,Precio,Plazo,Tasa\n"
        b"2026-01-05,9.95,28,0.06\n"
        b"2026-01-06,9.96,27,0.06\n"
        b"2026-01-07,9.97,26,0.06\n"
    )
    with pytest.raises(PortfolioError, match="no coinciden"):
        read_banxico_cetes_csv(
            wrong_rate, date_column="Fecha", price_column="Precio", term_column="Plazo"
        )
    missing_price = (
        b"Fecha,Precio,Plazo\n"
        b"2026-01-05,9.95,28\n"
        b"2026-01-06,N/E,27\n"
        b"2026-01-07,9.97,26\n"
    )
    with pytest.raises(PortfolioError, match="no numérico o faltante"):
        read_banxico_cetes_csv(
            missing_price, date_column="Fecha", price_column="Precio", term_column="Plazo"
        )


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


def test_merge_cetes_index_allows_only_leading_and_trailing_truncation():
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    market = pd.DataFrame({"A": np.linspace(100, 110, 70)}, index=dates)
    cetes = pd.Series(np.linspace(100, 101, 65), index=dates[3:68], name="CETES28")
    combined = merge_cetes_index(market, cetes)
    assert combined.index.equals(dates[3:68])
    assert list(combined.columns) == ["A", "CETES28"]


def test_merge_cetes_index_rejects_internal_gap():
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    market = pd.DataFrame({"A": np.linspace(100, 110, 70)}, index=dates)
    cetes = pd.Series(np.linspace(100, 101, 69), index=dates.delete(20), name="CETES28")
    with pytest.raises(PortfolioError, match="omite 1 fecha"):
        merge_cetes_index(market, cetes)


def test_bond_total_return_uses_dirty_price_and_coupon_cash_flow():
    dates = pd.date_range("2026-01-05", periods=4, freq="B")
    observations = pd.DataFrame({
        "Limpio": [98.0, 98.1, 95.2, 95.3],
        "Devengado": [2.8, 2.9, 0.1, 0.2],
        "Cupon": [0.0, 0.0, 3.0, 0.0],
    }, index=dates)
    result = prepare_bond_total_return(
        observations,
        clean_price_column="Limpio",
        accrued_interest_column="Devengado",
        coupon_column="Cupon",
        issue_id="M 310529",
        maturity_date="2031-05-29",
        name="BONO_M_310529",
    )
    expected_coupon_factor = (95.2 + 0.1 + 3.0) / (98.1 + 2.9)
    assert result.index.iloc[2] / result.index.iloc[1] == pytest.approx(expected_coupon_factor)
    assert result.dirty_prices.iloc[1] == pytest.approx(101.0)
    assert result.issue_id == "M 310529"
    assert result.returns.name == "BONO_M_310529"


def test_bond_csv_requires_one_issue_and_constant_maturity():
    valid = (
        b"Fecha,Emision,Vencimiento,PrecioLimpio,InteresDevengado,Cupon\n"
        b"2026-01-05,M 310529,2031-05-29,98.0,2.8,0\n"
        b"2026-01-06,M 310529,2031-05-29,98.1,2.9,0\n"
        b"2026-01-07,M 310529,2031-05-29,95.2,0.1,3\n"
    )
    result = read_bond_total_return_csv(valid, name="BONO_M_310529")
    assert result.maturity_date == pd.Timestamp("2031-05-29")
    mixed_issue = valid.replace(b"M 310529,2031-05-29,95.2", b"M 290531,2031-05-29,95.2")
    with pytest.raises(PortfolioError, match="una sola emisión"):
        read_bond_total_return_csv(mixed_issue)
    mixed_maturity = valid.replace(b"2031-05-29,95.2", b"2029-05-31,95.2")
    with pytest.raises(PortfolioError, match="constante"):
        read_bond_total_return_csv(mixed_maturity)
    missing_issue = valid.replace(b"M 310529,2031-05-29,95.2", b",2031-05-29,95.2")
    with pytest.raises(PortfolioError, match="una sola emisión"):
        read_bond_total_return_csv(missing_issue)


@pytest.mark.parametrize(
    ("modifier", "message"),
    [
        (lambda frame: frame.assign(Cupon=[1.0, 0.0, 0.0]), "primera observación"),
        (lambda frame: frame.assign(Interes=[0.1, -0.1, 0.2]), "interés devengado"),
        (lambda frame: frame.set_axis(pd.to_datetime([
            "2031-05-28", "2031-05-29", "2031-05-30"
        ])), "posteriores al vencimiento"),
    ],
)
def test_bond_total_return_rejects_invalid_inputs(modifier, message):
    frame = pd.DataFrame({
        "Precio": [99.0, 99.1, 99.2],
        "Interes": [0.1, 0.2, 0.3],
        "Cupon": [0.0, 0.0, 0.0],
    }, index=pd.date_range("2026-01-05", periods=3, freq="B"))
    with pytest.raises(PortfolioError, match=message):
        prepare_bond_total_return(
            modifier(frame),
            clean_price_column="Precio",
            accrued_interest_column="Interes",
            coupon_column="Cupon",
            issue_id="M 310529",
            maturity_date="2031-05-29",
        )


def test_merge_bond_index_rejects_internal_gap():
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    market = pd.DataFrame({"A": np.linspace(100, 110, 70)}, index=dates)
    bond = pd.Series(np.linspace(100, 104, 69), index=dates.delete(25), name="BONO_M")
    with pytest.raises(PortfolioError, match="bono omite 1 fecha"):
        merge_bond_index(market, bond)
