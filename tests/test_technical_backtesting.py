import numpy as np
import pandas as pd
import pytest

from technical_analysis import TechnicalError
from technical_backtesting import _simulate, run_technical_backtest


def execution_case(periods=30):
    bars = pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
        "Volume": 1_000.0, "ATR14": 5.0,
    }, index=pd.bdate_range("2025-01-01", periods=periods))
    signals = pd.DataFrame({"Buy": False, "Sell": False}, index=bars.index)
    signals.loc[signals.index[0], "Buy"] = True
    return bars, signals


def simulate(bars, signals, cost=0.0, slippage=0.0):
    return _simulate(bars, signals, 1, cost_rate=cost, slippage_bps=slippage)


def test_entry_and_technical_exit_use_following_open():
    bars, signals = execution_case()
    signals.loc[signals.index[1], "Sell"] = True
    bars.loc[bars.index[2], ["Open", "High", "Low", "Close"]] = [103, 104, 102, 103]
    result = simulate(bars, signals)
    trade = result.trades.iloc[0]
    assert trade["Fecha señal"] == bars.index[0]
    assert trade["Entrada"] == bars.index[1] and trade["Salida"] == bars.index[2]
    assert trade["Retorno bruto"] == pytest.approx(0.03)
    assert trade["Referencia salida"] == 103


def test_same_candle_both_levels_resolves_stop_first():
    bars, signals = execution_case()
    bars.loc[bars.index[1], ["High", "Low"]] = [121, 89]
    result = simulate(bars, signals)
    assert result.trades.iloc[0]["Referencia salida"] == 90
    assert "ambos niveles" in result.trades.iloc[0]["Motivo"]
    assert result.equity["Estrategia neta"].iloc[-1] == 90


@pytest.mark.parametrize("opening, reason", [(85, "Gap de stop"), (125, "Gap de objetivo")])
def test_gap_executes_at_open_instead_of_unavailable_level(opening, reason):
    bars, signals = execution_case()
    bars.loc[bars.index[2], ["Open", "High", "Low", "Close"]] = [opening, opening + 1, opening - 1, opening]
    result = simulate(bars, signals, 0.0025, 10)
    trade = result.trades.iloc[0]
    assert trade["Referencia salida"] == opening
    assert trade["Ejecución salida"] == opening * 0.999
    assert trade["Motivo"] == reason


def test_stop_is_frozen_using_signal_day_atr():
    bars, signals = execution_case()
    bars.loc[bars.index[1]:, "ATR14"] = 20
    bars.loc[bars.index[2], ["High", "Low"]] = [101, 89]
    result = simulate(bars, signals)
    assert result.trades.iloc[0]["Stop"] == 90


def test_maximum_twenty_sessions_and_final_liquidation():
    bars, signals = execution_case()
    trade = simulate(bars, signals).trades.iloc[0]
    assert trade["Salida"] == bars.index[21]
    assert trade["Sesiones"] == 20
    assert trade["Motivo"] == "Máximo de 20 sesiones"
    short_bars, short_signals = execution_case(5)
    last = simulate(short_bars, short_signals).trades.iloc[0]
    assert last["Salida"] == short_bars.index[-1]
    assert "Liquidación" in last["Motivo"]


def test_costs_apply_on_both_sides_to_both_alternatives():
    bars, signals = execution_case(5)
    result = simulate(bars, signals, 0.0025, 10)
    expected = 100 * (0.999 * 0.9975) / (1.001 * 1.0025)
    assert result.equity["Estrategia neta"].iloc[-1] == pytest.approx(expected)
    assert result.equity["Comprar y mantener neto"].iloc[-1] == pytest.approx(expected)
    assert result.equity["Estrategia bruta"].iloc[-1] == 100
    assert result.summary.loc["Estrategia", "Máxima caída neta"] == pytest.approx(1 - expected / 100)


def test_no_trades_is_cash_and_winning_percentage_not_applicable():
    bars, signals = execution_case()
    signals["Buy"] = False
    result = simulate(bars, signals)
    assert result.trades.empty and result.win_rate is None
    assert result.equity["Estrategia neta"].eq(100).all()


def test_complete_window_cost_sensitivity_and_read_only_input(technical_bars):
    original = technical_bars.copy(deep=True)
    free = run_technical_backtest(technical_bars, cost_rate=0, slippage_bps=0)
    paid = run_technical_backtest(technical_bars)
    assert len(paid.trades) > 0
    assert paid.equity["Estrategia neta"].iloc[-1] < free.equity["Estrategia neta"].iloc[-1]
    assert np.isfinite(paid.equity.to_numpy()).all()
    assert paid.trades["Sesiones"].max() <= 20
    pd.testing.assert_frame_equal(original, technical_bars)
    pd.testing.assert_frame_equal(paid.equity[["Estrategia bruta"]], free.equity[["Estrategia bruta"]])


def test_short_history_does_not_silently_use_a_partial_window(technical_bars):
    with pytest.raises(TechnicalError, match="ventana parcial"):
        run_technical_backtest(technical_bars.iloc[-600:])


def test_full_window_requires_a_mature_signal_before_first_execution(technical_bars):
    cutoff = technical_bars.index[-1] - pd.DateOffset(years=2)
    first_execution = int(technical_bars.index.searchsorted(cutoff))
    # SMA200 alone is insufficient: the shared signal engine needs 252 sessions.
    insufficient = technical_bars.iloc[first_execution - 200:]
    with pytest.raises(TechnicalError, match="252 sesiones"):
        run_technical_backtest(insufficient)
    complete = technical_bars.iloc[first_execution - 252:]
    result = run_technical_backtest(complete)
    assert result.start == technical_bars.index[first_execution]
