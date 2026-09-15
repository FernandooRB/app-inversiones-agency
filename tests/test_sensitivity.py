import numpy as np
import pandas as pd
import pytest

from portfolio_core import PortfolioError
from sensitivity import analyze_allocation_sensitivity


def changing_regime_returns() -> pd.DataFrame:
    rng = np.random.default_rng(444)
    early = rng.normal([0.002, -0.001], [0.006, 0.006], size=(160, 2))
    late = rng.normal([-0.002, 0.002], [0.006, 0.006], size=(140, 2))
    return pd.DataFrame(
        np.vstack([early, late]),
        index=pd.date_range("2024-01-02", periods=300, freq="B"),
        columns=["A", "B"],
    )


def test_windows_end_together_and_reveal_regime_sensitive_weights():
    returns = changing_regime_returns()
    result = analyze_allocation_sensitivity(returns)
    assert set(result.summary.index.get_level_values("Muestra")) == {
        "Muestra completa", "Últimos 252", "Últimos 126", "Últimos 60"
    }
    assert result.summary["Hasta"].eq(returns.index[-1]).all()
    assert result.summary.loc[("Últimos 60", "Máximo Sharpe"), "Desde"] == returns.index[-60]
    assert result.summary.loc[
        ("Últimos 60", "Máximo Sharpe"), "Cambio de pesos vs. muestra completa"
    ] > 0.1
    for _, group in result.weights.groupby(level=["Muestra", "Modelo"]):
        assert group["Peso"].sum() == pytest.approx(1)
        assert group["Peso"].ge(0).all()


def test_same_data_with_shorter_history_only_shows_available_windows():
    result = analyze_allocation_sensitivity(changing_regime_returns().iloc[-90:])
    assert set(result.summary.index.get_level_values("Muestra")) == {
        "Muestra completa", "Últimos 60"
    }


def test_unordered_dates_and_short_windows_rejected():
    returns = changing_regime_returns()
    with pytest.raises(PortfolioError, match="fechas únicas y ordenadas"):
        analyze_allocation_sensitivity(returns.iloc[::-1])
    with pytest.raises(PortfolioError, match="al menos 60"):
        analyze_allocation_sensitivity(returns, windows=(30,))
