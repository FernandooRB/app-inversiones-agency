"""Retrospective, non-overlapping checks of the fixed technical rules."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from technical_analysis import (
    MIN_SIGNAL_SESSIONS,
    STRATEGY_VERSION,
    TechnicalError,
    calculate_indicators,
    historical_signals,
    validate_bars,
    validate_costs,
)
from technical_backtesting import _simulate

WINDOW_SESSIONS = 252


@dataclass(frozen=True)
class ChronologicalValidation:
    windows: pd.DataFrame
    base_cost_rate: float
    base_slippage_bps: float
    stress_cost_rate: float
    stress_slippage_bps: float
    strategy_version: str = STRATEGY_VERSION


def run_chronological_validation(
    bars: pd.DataFrame, *, windows: int = 3,
    cost_rate: float = 0.0025, slippage_bps: float = 10,
    stress_cost_rate: float = 0.005, stress_slippage_bps: float = 20,
) -> ChronologicalValidation:
    """Replay consecutive 252-session windows with only earlier bars available to each.

    This is a retrospective robustness check, not a prospective out-of-sample result.
    The strategy is fixed and no parameters are fitted on these windows.
    """
    bars = validate_bars(bars)
    validate_costs(cost_rate, slippage_bps)
    validate_costs(stress_cost_rate, stress_slippage_bps)
    if type(windows) is not int or not 1 <= windows <= 5:
        raise TechnicalError("La validación requiere entre una y cinco ventanas completas.")
    if stress_cost_rate < cost_rate or stress_slippage_bps < slippage_bps:
        raise TechnicalError("El escenario de estrés no puede tener costos menores que el base.")
    required = MIN_SIGNAL_SESSIONS + windows * WINDOW_SESSIONS
    if len(bars) < required:
        raise TechnicalError(
            f"La validación requiere {required} sesiones: {MIN_SIGNAL_SESSIONS} de calentamiento "
            f"y {windows} ventanas completas de {WINDOW_SESSIONS}. Hay {len(bars)}."
        )
    rows = []
    first_start = len(bars) - windows * WINDOW_SESSIONS
    for number in range(windows):
        start = first_start + number * WINDOW_SESSIONS
        end = start + WINDOW_SESSIONS
        # Truncation ensures the period cannot see observations from later windows.
        indicators = calculate_indicators(bars.iloc[:end])
        signals = historical_signals(indicators)
        base = _simulate(indicators, signals, start,
                         cost_rate=cost_rate, slippage_bps=slippage_bps)
        stressed = _simulate(indicators, signals, start,
                             cost_rate=stress_cost_rate,
                             slippage_bps=stress_slippage_bps)
        rows.append({
            "Periodo": number + 1,
            "Inicio": base.start.date(),
            "Fin": base.end.date(),
            "Operaciones": len(base.trades),
            "Ganadoras netas": base.win_rate,
            "Estrategia neta": float(base.summary.loc["Estrategia", "Retorno neto"]),
            "Comprar y mantener neto": float(base.summary.loc["Comprar y mantener", "Retorno neto"]),
            "Caída máxima neta": float(base.summary.loc["Estrategia", "Máxima caída neta"]),
            "Estrategia neta con estrés": float(stressed.summary.loc["Estrategia", "Retorno neto"]),
        })
    return ChronologicalValidation(
        pd.DataFrame(rows).set_index("Periodo"), cost_rate, slippage_bps,
        stress_cost_rate, stress_slippage_bps,
    )
