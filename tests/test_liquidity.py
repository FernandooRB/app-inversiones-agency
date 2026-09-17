import numpy as np
import pandas as pd
import pytest

from liquidity import (
    merge_liquidity_index,
    prepare_liquidity_accrual,
    read_liquidity_rate_csv,
)
from portfolio_core import PortfolioError


def test_nominal_360_uses_previous_rate_and_calendar_days():
    dates = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    observations = pd.DataFrame({"Tasa": [7.2, 9.0, 10.0]}, index=dates)
    result = prepare_liquidity_accrual(
        observations,
        rate_column="Tasa",
        vehicle="Cuenta remunerada de prueba",
        convention="nominal_360",
        treatment="NETA",
    )
    assert result.index.iloc[1] == pytest.approx(100 * (1 + 0.072 * 3 / 360))
    assert result.index.iloc[2] / result.index.iloc[1] == pytest.approx(1 + 0.09 / 360)
    assert result.calendar_days.tolist() == [0, 3, 1]
    assert result.treatment == "NETA"


def test_effective_365_compounds_declared_annual_rate():
    dates = pd.to_datetime(["2026-01-01", "2026-07-02", "2027-01-01"])
    observations = pd.DataFrame({"Tasa": [10.0, 10.0, 10.0]}, index=dates)
    result = prepare_liquidity_accrual(
        observations,
        rate_column="Tasa",
        vehicle="Fondo diario de prueba",
        convention="efectiva_365",
        treatment="BRUTA",
    )
    assert result.index.iloc[-1] == pytest.approx(110.0)


def test_liquidity_csv_requires_constant_identity_and_conventions():
    valid = (
        b"Fecha,Vehiculo,TasaAnualPct,Convencion,Tratamiento\n"
        b"2026-01-02,Cuenta A,8.0,nominal_360,NETA\n"
        b"2026-01-05,Cuenta A,8.1,nominal_360,NETA\n"
        b"2026-01-06,Cuenta A,8.2,nominal_360,NETA\n"
    )
    result = read_liquidity_rate_csv(valid, name="LIQUIDEZ_MXN")
    assert result.vehicle == "Cuenta A"
    assert result.convention == "nominal_360"
    mixed = valid.replace(b"Cuenta A,8.2", b"Cuenta B,8.2")
    with pytest.raises(PortfolioError, match="un solo vehículo"):
        read_liquidity_rate_csv(mixed)
    mixed_convention = valid.replace(b"8.2,nominal_360", b"8.2,efectiva_365")
    with pytest.raises(PortfolioError, match="una sola convención"):
        read_liquidity_rate_csv(mixed_convention)
    empty = b"Fecha,Vehiculo,TasaAnualPct,Convencion,Tratamiento\n"
    with pytest.raises(PortfolioError, match="vehículo"):
        read_liquidity_rate_csv(empty)


@pytest.mark.parametrize(
    ("rates", "convention", "treatment", "message"),
    [
        ([8.0, np.nan, 8.0], "nominal_360", "NETA", "faltantes"),
        ([8.0, 8.0, 8.0], "desconocida", "NETA", "convención"),
        ([8.0, 8.0, 8.0], "nominal_360", "DESCONOCIDA", "tratamiento"),
        ([-100.0, 8.0, 8.0], "nominal_360", "NETA", "mayor a -100%"),
    ],
)
def test_liquidity_rejects_invalid_inputs(rates, convention, treatment, message):
    observations = pd.DataFrame(
        {"Tasa": rates}, index=pd.date_range("2026-01-05", periods=3, freq="B")
    )
    with pytest.raises(PortfolioError, match=message):
        prepare_liquidity_accrual(
            observations,
            rate_column="Tasa",
            vehicle="Cuenta A",
            convention=convention,
            treatment=treatment,
        )


def test_liquidity_rejects_missing_vehicle_identifier():
    observations = pd.DataFrame(
        {"Tasa": [8.0, 8.0, 8.0]}, index=pd.date_range("2026-01-05", periods=3, freq="B")
    )
    with pytest.raises(PortfolioError, match="identificador válido"):
        prepare_liquidity_accrual(
            observations,
            rate_column="Tasa",
            vehicle=None,
            convention="nominal_360",
            treatment="NETA",
        )


def test_merge_liquidity_rejects_internal_gap():
    dates = pd.date_range("2025-01-01", periods=70, freq="B")
    market = pd.DataFrame({"A": np.linspace(100, 110, 70)}, index=dates)
    liquidity = pd.Series(np.linspace(100, 101, 69), index=dates.delete(25), name="LIQUIDEZ")
    with pytest.raises(PortfolioError, match="liquidez omite 1 fecha"):
        merge_liquidity_index(market, liquidity)
