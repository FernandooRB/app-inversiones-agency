"""Historical period checks must be disjoint and cannot use future observations."""

import pandas as pd
import pytest

from technical_analysis import TechnicalError
from technical_validation import run_chronological_validation


def test_three_windows_are_complete_disjoint_and_use_prefix_only(technical_bars):
    result = run_chronological_validation(technical_bars)
    assert len(result.windows) == 3
    for previous, current in zip(result.windows.iloc[:-1].itertuples(),
                                 result.windows.iloc[1:].itertuples(), strict=True):
        assert previous.Fin < current.Inicio
    prefix = technical_bars.iloc[:-252]
    earlier = run_chronological_validation(prefix, windows=2)
    pd.testing.assert_frame_equal(result.windows.iloc[:2], earlier.windows)
    assert (result.windows["Estrategia neta con estrés"]
            <= result.windows["Estrategia neta"]).all()


def test_rejects_partial_history_and_optimistic_stress(technical_bars):
    with pytest.raises(TechnicalError, match="ventanas completas"):
        run_chronological_validation(technical_bars.iloc[-1000:])
    with pytest.raises(TechnicalError, match="costos menores"):
        run_chronological_validation(technical_bars, stress_cost_rate=0.001)
    with pytest.raises(TechnicalError, match="entre una y cinco"):
        run_chronological_validation(technical_bars, windows=True)
