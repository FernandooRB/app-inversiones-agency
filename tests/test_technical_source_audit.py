"""Cross-source checks reveal data drift before a signal is trusted."""

from dataclasses import replace
from datetime import UTC

import pandas as pd
import pytest

from scripts.audit_market_sources import parse_nasdaq_rows
from technical_analysis import TechnicalError
from technical_source_audit import compare_market_histories


def _evaluation_time(history):
    return (history.bars.index[-1] + pd.Timedelta(days=2)).to_pydatetime().replace(tzinfo=UTC)


def test_identical_sources_agree_and_changed_volume_flags_condition(technical_history):
    other = replace(technical_history, source="Fuente independiente")
    same = compare_market_histories(technical_history, other,
                                    now=_evaluation_time(technical_history))
    assert same.compared_sessions == 504
    assert same.signal_disagreements == 0
    assert same.condition_disagreements == 0
    assert same.max_close_gap_pct == 0
    assert same.reasons_to_review == ()

    altered = technical_history.bars.copy()
    altered.loc[altered.index[-1], "Volume"] = 1.0
    drift = compare_market_histories(technical_history, replace(other, bars=altered),
                                     now=_evaluation_time(technical_history))
    assert drift.condition_disagreements > 0
    assert drift.last_volume_gap_pct > 99
    assert any("condiciones" in reason for reason in drift.reasons_to_review)


def test_stale_second_source_does_not_compare_latest_prices(technical_history):
    other = replace(technical_history, bars=technical_history.bars.iloc[:-1],
                    source="Fuente anterior")
    audit = compare_market_histories(technical_history, other,
                                     now=_evaluation_time(technical_history))
    assert audit.left_latest != audit.right_latest
    assert audit.last_close_gap_pct is None
    assert any("sesiones distintas" in reason for reason in audit.reasons_to_review)


def test_currency_and_history_requirements_are_strict(technical_history):
    now = _evaluation_time(technical_history)
    with pytest.raises(TechnicalError, match="misma moneda"):
        compare_market_histories(technical_history,
                                 replace(technical_history, currency="MXN"), now=now)
    with pytest.raises(TechnicalError, match="252 sesiones"):
        compare_market_histories(technical_history,
                                 replace(technical_history, bars=technical_history.bars.iloc[-200:]),
                                 now=now)


def test_nasdaq_parser_explains_missing_volume_without_filling_it():
    record = {"date": "04/20/2026", "open": "710.14", "high": "710.14",
              "low": "710.14", "close": "710.14", "volume": "N/A"}
    with pytest.raises(ValueError, match="Nasdaq SPY, 04/20/2026: Volume ausente"):
        parse_nasdaq_rows("SPY", [record])
