import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError
from stress import (
    deterministic_shock,
    historical_worst_windows,
    parse_asset_shocks,
    parse_class_shocks,
    validate_scenario_metadata,
)


def test_historical_worst_windows_compound_and_report_dates():
    index = pd.date_range("2024-01-01", periods=6, freq="B")
    returns = pd.DataFrame({"A": [0.02, -0.10, -0.20, 0.30, -0.05, 0.01]}, index=index)
    result = historical_worst_windows(returns, [1], horizons=(1, 2))
    assert result.loc[0, "Peor retorno"] == pytest.approx(-0.20)
    assert result.loc[1, "Peor retorno"] == pytest.approx(0.9 * 0.8 - 1)
    assert result.loc[1, "Inicio"] == index[1]
    assert result.loc[1, "Fin"] == index[2]


def test_historical_stress_preserves_cross_asset_dependence():
    index = pd.date_range("2024-01-01", periods=3, freq="B")
    returns = pd.DataFrame({"A": [-0.20, 0.10, 0.00], "B": [0.20, -0.10, 0.00]}, index=index)
    result = historical_worst_windows(returns, [0.5, 0.5], horizons=(1,))
    assert result.loc[0, "Peor retorno"] == pytest.approx(0)


def test_parse_and_apply_deterministic_shocks():
    shocks = parse_asset_shocks("-20, 10", 2)
    result = deterministic_shock([0.6, 0.4], shocks, 1000, labels=["A", "B"])
    assert result.portfolio_return == pytest.approx(-0.08)
    assert result.stressed_value == pytest.approx(920)
    assert result.loss_amount == pytest.approx(80)
    assert result.contributions.to_dict() == pytest.approx({"A": -0.12, "B": 0.04})


@pytest.mark.parametrize("raw", ["-101,0", "nan,0", "10", "a,0"])
def test_invalid_asset_shocks_are_rejected(raw):
    with pytest.raises(PortfolioError):
        parse_asset_shocks(raw, 2)


def test_total_loss_shock_is_supported():
    result = deterministic_shock([1], parse_asset_shocks("-100", 1), 1000)
    assert result.stressed_value == 0
    assert result.loss_amount == 1000


def test_class_shocks_expand_to_each_asset_and_preserve_class_table():
    classes = ("renta_variable", "deuda", "renta_variable", "efectivo")
    class_shocks, asset_shocks = parse_class_shocks(
        "renta_variable,-25\ndeuda,-3\nefectivo,0", classes
    )
    assert class_shocks.to_dict() == pytest.approx({
        "deuda": -0.03, "efectivo": 0.0, "renta_variable": -0.25,
    })
    np.testing.assert_allclose(asset_shocks, [-0.25, -0.03, -0.25, 0.0])
    result = deterministic_shock([0.4, 0.3, 0.2, 0.1], asset_shocks, 1000)
    assert result.portfolio_return == pytest.approx(-0.159)


@pytest.mark.parametrize(
    "raw,match",
    [
        ("renta_variable,-20", "Faltan shocks"),
        ("renta_variable,-20\ndeuda,-5\notra,0", "no utilizadas"),
        ("renta_variable,-20\nrenta_variable,-10\ndeuda,-5", "más de una vez"),
        ("renta_variable,-101\ndeuda,-5", "-100%"),
    ],
)
def test_class_shocks_reject_incomplete_duplicate_or_unknown_rules(raw, match):
    with pytest.raises(PortfolioError, match=match):
        parse_class_shocks(raw, ("renta_variable", "deuda"))


def test_scenario_metadata_is_required_and_trimmed():
    assert validate_scenario_metadata("  Venta global  ", "  Aversión al riesgo  ") == (
        "Venta global", "Aversión al riesgo"
    )
    with pytest.raises(PortfolioError, match="nombre"):
        validate_scenario_metadata("", "Fundamento")
    with pytest.raises(PortfolioError, match="fundamento"):
        validate_scenario_metadata("Escenario", "")


def test_historical_stress_rejects_nonfinite_returns():
    returns = pd.DataFrame({"A": np.full(5, np.nan)})
    with pytest.raises(PortfolioError, match="inválidos"):
        historical_worst_windows(returns, [1])


def test_historical_stress_requires_observation_dates():
    returns = pd.DataFrame({"A": np.zeros(5)})
    with pytest.raises(PortfolioError, match="inválidos"):
        historical_worst_windows(returns, [1])
