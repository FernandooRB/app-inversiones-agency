"""Daily long-only simulation of the exact versioned technical signal rules."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from technical_analysis import (
    MIN_SIGNAL_SESSIONS,
    STRATEGY_VERSION,
    TechnicalError,
    calculate_indicators,
    create_trade_plan,
    historical_signals,
    validate_bars,
    validate_costs,
)

TRADE_COLUMNS = (
    "Fecha señal", "Entrada", "Salida", "Referencia entrada", "Ejecución entrada",
    "Stop", "Objetivo", "Referencia salida", "Ejecución salida", "Motivo",
    "Sesiones", "Retorno bruto", "Retorno neto",
)


@dataclass(frozen=True)
class TechnicalBacktest:
    equity: pd.DataFrame
    trades: pd.DataFrame
    summary: pd.DataFrame
    win_rate: float | None
    start: pd.Timestamp
    end: pd.Timestamp
    strategy_version: str = STRATEGY_VERSION


def _simulate(
    indicators: pd.DataFrame, signals: pd.DataFrame, start_index: int,
    *, cost_rate: float, slippage_bps: float,
) -> TechnicalBacktest:
    """Signals from t-1 execute at t's open. Intrabar ambiguity always favors the stop."""
    validate_costs(cost_rate, slippage_bps)
    if start_index < 1 or start_index >= len(indicators):
        raise TechnicalError("La evaluación requiere una sesión anterior y sesiones posteriores.")
    if not signals.index.equals(indicators.index) or not {"Buy", "Sell"}.issubset(signals.columns):
        raise TechnicalError("Las señales y las velas deben corresponder a las mismas sesiones.")
    slippage = slippage_bps / 10_000
    buy_factor = (1 + slippage) * (1 + cost_rate)
    sell_factor = (1 - slippage) * (1 - cost_rate)
    net_cash = gross_cash = 100.0
    position = None
    rows = []
    trades = []
    first_open = float(indicators.iloc[start_index].Open)
    benchmark_net_units = 100 / (first_open * buy_factor)
    benchmark_gross_units = 100 / first_open
    baseline = indicators.index[start_index - 1]
    rows.append((baseline, 100.0, 100.0, 100.0, 100.0))

    def exit_position(price: float, reason: str, i: int, *, at_open: bool = False):
        nonlocal position, net_cash, gross_cash
        net_cash = position["net_units"] * price * sell_factor
        gross_cash = position["gross_units"] * price
        trades.append({
            "Fecha señal": position["signal_date"],
            "Entrada": indicators.index[position["index"]],
            "Salida": indicators.index[i],
            "Referencia entrada": position["entry"],
            "Ejecución entrada": position["entry"] * (1 + slippage),
            "Stop": position["stop"], "Objetivo": position["target"],
            "Referencia salida": price, "Ejecución salida": price * (1 - slippage),
            "Motivo": reason, "Sesiones": i - position["index"] + (0 if at_open else 1),
            "Retorno bruto": price / position["entry"] - 1,
            "Retorno neto": net_cash / position["initial_net"] - 1,
        })
        position = None

    for i in range(start_index, len(indicators)):
        bar = indicators.iloc[i]
        previous_signal = signals.iloc[i - 1]
        started_with_position = position is not None
        if position is not None:
            if bar.Open <= position["stop"]:
                exit_position(float(bar.Open), "Gap de stop", i, at_open=True)
            elif bar.Open >= position["target"]:
                exit_position(float(bar.Open), "Gap de objetivo", i, at_open=True)
            elif previous_signal.Sell:
                exit_position(float(bar.Open), "Señal de venta al cierre anterior", i, at_open=True)
            elif i - position["index"] >= 20:
                exit_position(float(bar.Open), "Máximo de 20 sesiones", i, at_open=True)
        if position is None and not started_with_position and previous_signal.Buy:
            atr = float(indicators.iloc[i - 1].ATR14)
            plan = create_trade_plan(float(bar.Open), atr, cost_rate=cost_rate,
                                     slippage_bps=slippage_bps)
            position = {
                "index": i, "signal_date": indicators.index[i - 1],
                "entry": plan.entry, "stop": plan.stop, "target": plan.target,
                "net_units": net_cash / (plan.entry * buy_factor),
                "gross_units": gross_cash / plan.entry, "initial_net": net_cash,
            }
        if position is not None:
            if bar.Low <= position["stop"]:
                reason = "Stop (ambos niveles en la vela)" if bar.High >= position["target"] else "Stop"
                exit_position(position["stop"], reason, i)
            elif bar.High >= position["target"]:
                exit_position(position["target"], "Objetivo", i)
            elif i == len(indicators) - 1:
                exit_position(float(bar.Close), "Liquidación al último cierre de evaluación", i)
        net_value = net_cash if position is None else position["net_units"] * float(bar.Close)
        gross_value = gross_cash if position is None else position["gross_units"] * float(bar.Close)
        benchmark_net = benchmark_net_units * float(bar.Close)
        if i == len(indicators) - 1:
            benchmark_net *= sell_factor
        rows.append((indicators.index[i], gross_value, net_value,
                     benchmark_gross_units * float(bar.Close), benchmark_net))

    equity = pd.DataFrame(rows, columns=[
        "Fecha", "Estrategia bruta", "Estrategia neta", "Comprar y mantener bruto", "Comprar y mantener neto",
    ]).set_index("Fecha")
    if not np.isfinite(equity.to_numpy()).all() or (equity <= 0).any().any():
        raise TechnicalError("La simulación no produjo una trayectoria de capital válida.")
    trade_table = pd.DataFrame(trades, columns=list(TRADE_COLUMNS))
    summaries = []
    for label, gross_column, net_column in (
        ("Estrategia", "Estrategia bruta", "Estrategia neta"),
        ("Comprar y mantener", "Comprar y mantener bruto", "Comprar y mantener neto"),
    ):
        curve = equity[net_column]
        summaries.append({
            "Alternativa": label,
            "Retorno bruto": float(equity[gross_column].iloc[-1] / 100 - 1),
            "Retorno neto": float(curve.iloc[-1] / 100 - 1),
            "Máxima caída neta": float((1 - curve / curve.cummax()).max()),
        })
    return TechnicalBacktest(
        equity, trade_table, pd.DataFrame(summaries).set_index("Alternativa"),
        float((trade_table["Retorno neto"] > 0).mean()) if len(trade_table) else None,
        indicators.index[start_index], indicators.index[-1],
    )


def run_technical_backtest(
    bars: pd.DataFrame, *, cost_rate: float = 0.0025, slippage_bps: float = 10,
) -> TechnicalBacktest:
    """Require two complete years with a mature signal before the first execution."""
    bars = validate_bars(bars)
    validate_costs(cost_rate, slippage_bps)
    cutoff = bars.index[-1] - pd.DateOffset(years=2)
    start_index = int(bars.index.searchsorted(cutoff))
    if start_index < MIN_SIGNAL_SESSIONS:
        raise TechnicalError(
            f"La prueba necesita dos años completos de evaluación y al menos {MIN_SIGNAL_SESSIONS} sesiones "
            "previas "
            "de calentamiento. No se calculó una ventana parcial."
        )
    indicators = calculate_indicators(bars)
    return _simulate(indicators, historical_signals(indicators), start_index,
                     cost_rate=cost_rate, slippage_bps=slippage_bps)
