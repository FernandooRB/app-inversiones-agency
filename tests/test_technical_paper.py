from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from technical_analysis import BUY, WAIT, TechnicalSnapshot
from technical_paper import PaperError, entry_event, exit_event, paper_result, signal_event


def signal_for_trial(now):
    day = now.astimezone(ZoneInfo("America/Mexico_City")).date() - timedelta(days=1)
    return signal_event(
        TechnicalSnapshot("AAPL", BUY, "Confirmación sintética.", as_of=day,
                          close=100, relative_volume=2, rsi=60,
                          indicators=pd.DataFrame({"MACDHistogram": [1]})),
        type("History", (), {"symbol": "AAPL", "currency": "USD", "exchange": "NasdaqGS",
                             "source": "Serie sintética", "fetched_at": now})(),
    )


def entry_for_trial(signal, now):
    return entry_event(
        signal, local_symbol="AAPL *", local_isin="US0378331005",
        quote_at=now - timedelta(minutes=1), bid_mxn="99", ask_mxn="100",
        volume=100, stop_mxn="90", target_mxn="120", cost_rate="0.0035",
        benchmark_symbol="SPY *", benchmark_isin="US78462F1030",
        benchmark_bid_mxn="49", benchmark_ask_mxn="50", benchmark_volume=500,
        now=now,
    )


def test_signal_snapshot_and_paired_mxn_result_are_immutable_inputs():
    now = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
    signal = signal_for_trial(now)
    assert signal.kind == "signal" and signal.payload["origin_currency"] == "USD"
    assert signal.payload["relative_volume"] == "2"
    saved_signal = replace(signal, recorded_at=now - timedelta(minutes=2))
    entry = entry_for_trial(saved_signal, now)
    saved_entry = replace(entry, recorded_at=now - timedelta(seconds=30))
    exit_ = exit_event(saved_entry, quote_at=now, bid_mxn="110", volume=80,
                       reason="Objetivo", benchmark_bid_mxn="52", benchmark_volume=400, now=now)
    result = paper_result(entry, exit_)
    assert result.gross_return == Decimal("0.10")
    assert result.net_return == Decimal("110") * Decimal("0.9965") / (
        Decimal("100") * Decimal("1.0035")) - 1
    assert result.benchmark_net_return == Decimal("52") * Decimal("0.9965") / (
        Decimal("50") * Decimal("1.0035")) - 1
    assert entry.payload["quantity"] == 1
    assert entry.payload["source"] == "GBM, captura manual"


def test_requires_prior_buy_and_recent_next_day_quote():
    now = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
    unsaved = signal_for_trial(now)
    with pytest.raises(PaperError, match="previamente"):
        entry_for_trial(unsaved, now)
    saved = replace(unsaved, recorded_at=now - timedelta(minutes=2))
    with pytest.raises(PaperError, match="previamente"):
        entry_for_trial(replace(saved, payload={**saved.payload, "signal": WAIT}), now)
    with pytest.raises(PaperError, match="15 minutos"):
        entry_event(saved, local_symbol="AAPL *", local_isin="US0378331005",
                    quote_at=now - timedelta(minutes=16), bid_mxn=99, ask_mxn=100,
                    volume=100, stop_mxn=90, target_mxn=120, cost_rate=0.0035, now=now)
    with pytest.raises(PaperError, match="después de la sesión"):
        entry_event(replace(saved, signal_date=now.date()), local_symbol="AAPL *",
                    local_isin="US0378331005", quote_at=now, bid_mxn=99, ask_mxn=100,
                    volume=100, stop_mxn=90, target_mxn=120, cost_rate=0.0035, now=now)


def test_costs_and_reference_cannot_be_backfilled_at_exit():
    now = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
    saved = replace(signal_for_trial(now), recorded_at=now - timedelta(minutes=2))
    entry = entry_event(saved, local_symbol="AAPL *", local_isin="US0378331005",
                        quote_at=now - timedelta(minutes=1), bid_mxn=99, ask_mxn=100,
                        volume=100, stop_mxn=90, target_mxn=120, cost_rate=0.0035, now=now)
    saved_entry = replace(entry, recorded_at=now)
    with pytest.raises(PaperError, match="referencia sólo al salir"):
        exit_event(saved_entry, quote_at=now, bid_mxn=110, volume=100,
                   reason="Objetivo", benchmark_bid_mxn=52, benchmark_volume=100, now=now)
    exit_ = exit_event(saved_entry, quote_at=now, bid_mxn=110, volume=100,
                       reason="Objetivo", now=now)
    assert paper_result(entry, exit_).benchmark_net_return is None
    with pytest.raises(PaperError, match="objetivo"):
        entry_event(saved, local_symbol="AAPL *", local_isin="US0378331005",
                    quote_at=now, bid_mxn=99, ask_mxn=100, volume=100,
                    stop_mxn=90, target_mxn=99, cost_rate=0.0035, now=now)
    with pytest.raises(PaperError, match="beneficio"):
        entry_event(saved, local_symbol="AAPL *", local_isin="US0378331005",
                    quote_at=now, bid_mxn=99, ask_mxn=100, volume=100,
                    stop_mxn=90, target_mxn=100.1, cost_rate=0.0035, now=now)
