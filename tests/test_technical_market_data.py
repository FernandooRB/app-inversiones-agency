from types import SimpleNamespace

import pandas as pd
import pytest

import technical_market_data as adapter
from technical_analysis import TechnicalError


@pytest.mark.parametrize("regular_end", [
    1_792_783_200, pd.Timestamp("2026-10-23 16:00", tz="America/New_York"),
])
def test_adapter_uses_daily_unadjusted_ohlc_with_events_and_metadata(
    monkeypatch, technical_bars, regular_end,
):
    seen = {}

    def history(**kwargs):
        seen.update(kwargs)
        return technical_bars

    fake = SimpleNamespace(history=history, get_history_metadata=lambda: {
        "currency": "USD", "exchangeName": "NMS", "exchangeTimezoneName": "America/New_York",
        "currentTradingPeriod": {"regular": {"end": regular_end}},
    })
    monkeypatch.setattr(adapter.yf, "Ticker", lambda symbol: fake)
    result = adapter.download_market_history("aapl")
    assert result.symbol == "AAPL" and result.currency == "USD"
    assert result.bars is technical_bars
    assert seen["period"] == "5y" and seen["interval"] == "1d"
    assert seen["auto_adjust"] is False and seen["actions"] is True
    assert result.regular_close.tzinfo is not None


def test_provider_failure_is_sanitized_and_invalid_symbol_is_rejected(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("provider implementation details should stay private")

    monkeypatch.setattr(adapter.yf, "Ticker", lambda symbol: SimpleNamespace(history=fail))
    with pytest.raises(TechnicalError) as error:
        adapter.download_market_history("AAPL")
    assert "implementation" not in str(error.value)
    with pytest.raises(TechnicalError):
        adapter.download_market_history("invalid;command")
