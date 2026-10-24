from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from technical_analysis import (
    UNAVAILABLE,
    TechnicalError,
    analyze_history,
    calculate_indicators,
    completed_bars,
    create_trade_plan,
    historical_signals,
    signal_conditions,
)


def candles(closes):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "Open": closes, "High": closes + 0.1, "Low": closes - 0.1,
        "Close": closes, "Volume": 1_000.0,
    }, index=pd.bdate_range("2024-01-01", periods=len(closes)))


def test_wilder_rsi_matches_known_seed_and_recurrence():
    close = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
             45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    result = calculate_indicators(candles(close))
    assert result.RSI14.iloc[:14].isna().all()
    assert result.RSI14.iloc[14] == pytest.approx(70.46413502109705)
    assert result.RSI14.iloc[15] == pytest.approx(66.24961855355505)


@pytest.mark.parametrize("closes, expected", [
    (np.arange(30) + 100, 100), (100 - np.arange(30), 0), (np.full(30, 100), 50),
])
def test_rsi_monotone_and_constant_series(closes, expected):
    result = calculate_indicators(candles(closes))
    assert result.RSI14.iloc[-1] == expected


def test_atr_wilder_seed_and_overnight_gap():
    bars = candles(np.full(15, 100))
    bars["High"], bars["Low"] = 102.0, 99.0
    bars.iloc[-1, bars.columns.get_indexer(["Open", "High", "Low", "Close"])] = [110, 112, 109, 110]
    atr = calculate_indicators(bars).ATR14
    assert atr.iloc[:13].isna().all()
    assert atr.iloc[13] == 3
    assert atr.iloc[14] == pytest.approx((13 * 3 + 12) / 14)


def test_volume_and_structure_exclude_current_session():
    bars = candles(np.arange(30) + 100)
    bars.loc[bars.index[-1], "Volume"] = 2_000
    result = calculate_indicators(bars)
    assert result.RelativeVolume.iloc[-1] == 2
    assert result.Resistance20.iloc[-1] == bars.High.iloc[-21:-1].max()
    assert result.Support20.iloc[-1] == bars.Low.iloc[-21:-1].min()


def test_adjusted_close_does_not_enter_ohlc_indicators(technical_bars):
    first = calculate_indicators(technical_bars)
    changed = technical_bars.copy()
    changed["Adj Close"] = 1
    second = calculate_indicators(changed)
    pd.testing.assert_frame_equal(first.drop(columns="Adj Close"), second.drop(columns="Adj Close"))


def test_future_observations_do_not_rewrite_indicators_or_signals(technical_bars):
    past = calculate_indicators(technical_bars.iloc[:700])
    full = calculate_indicators(technical_bars)
    pd.testing.assert_frame_equal(past, full.iloc[:700])
    pd.testing.assert_frame_equal(historical_signals(past), historical_signals(full).iloc[:700])


def test_exact_buy_thresholds_and_signal_warmup():
    data = pd.DataFrame({
        "Close": 110.0, "SMA50": 105.0, "SMA200": 100.0, "Resistance20": 109.0,
        "Support20": 95.0, "RSI14": 60.0, "RelativeVolume": 1.5, "MACDHistogram": 0.1,
    }, index=pd.bdate_range("2024-01-01", periods=253))
    data.iloc[-2, data.columns.get_loc("RSI14")] = 59
    buy, sell = signal_conditions(data)
    assert buy.iloc[-1].all() and not sell.iloc[-1].all()
    signals = historical_signals(data)
    assert signals.iloc[:251].Buy.eq(False).all()
    assert signals.Buy.iloc[-1]
    for column, value in (("RelativeVolume", 1.499), ("RSI14", 70.01),
                          ("MACDHistogram", 0), ("Close", 109)):
        changed = data.copy()
        changed.loc[changed.index[-1], column] = value
        assert not historical_signals(changed).Buy.iloc[-1]


def test_oversold_alone_does_not_buy_and_overbought_alone_does_not_sell(technical_bars):
    data = calculate_indicators(technical_bars)
    data.loc[data.index[-1], "RSI14"] = 20
    assert not historical_signals(data).Buy.iloc[-1]
    data.loc[data.index[-1], "RSI14"] = 80
    assert not historical_signals(data).Sell.iloc[-1]


def test_sell_needs_volume_price_and_bearish_momentum(technical_bars):
    data = calculate_indicators(technical_bars)
    columns = ["Close", "Support20", "RSI14", "RelativeVolume", "MACDHistogram"]
    data.loc[data.index[-1], columns] = [90, 95, 44, 1.5, -0.1]
    assert historical_signals(data).Sell.iloc[-1]
    data.loc[data.index[-1], "RelativeVolume"] = 1.4
    assert not historical_signals(data).Sell.iloc[-1]


@pytest.mark.parametrize("column, value", [("Volume", 0), ("Volume", np.nan),
                                           ("Close", np.inf), ("Low", 1_000)])
def test_invalid_observation_makes_symbol_unavailable(technical_history, column, value):
    bars = technical_history.bars.copy()
    bars.loc[bars.index[-1], column] = value
    result = analyze_history(replace(technical_history, bars=bars))
    assert result.signal == UNAVAILABLE
    assert result.reason


def test_insufficient_stale_and_missing_metadata(technical_history):
    short = replace(technical_history, bars=technical_history.bars.iloc[-251:])
    assert analyze_history(short).signal == UNAVAILABLE
    future = datetime.now(UTC) + timedelta(days=10)
    result = analyze_history(technical_history, future)
    assert result.signal == UNAVAILABLE and "cinco días" in result.reason
    assert analyze_history(replace(technical_history, currency="")).signal == UNAVAILABLE
    assert analyze_history(replace(technical_history, timezone="invalid/zone")).signal == UNAVAILABLE


def test_today_requires_confirmed_close_and_provider_delay(technical_history):
    bars = candles(np.arange(300) + 100)
    bars.index = pd.bdate_range(end="2026-10-23", periods=len(bars), tz="America/New_York")
    history = replace(
        technical_history, bars=bars, regular_close=datetime(2026, 10, 23, 20, tzinfo=UTC),
        fetched_at=datetime(2026, 10, 23, 20, 16, tzinfo=UTC),
    )
    before = completed_bars(history, datetime(2026, 10, 23, 19, tzinfo=UTC))
    buffered = completed_bars(history, datetime(2026, 10, 23, 20, 5, tzinfo=UTC))
    after = completed_bars(history, datetime(2026, 10, 23, 20, 16, tzinfo=UTC))
    fallback = completed_bars(replace(history, regular_close=None), datetime(2026, 10, 23, 22, tzinfo=UTC))
    assert str(before.index[-1].date()) == "2026-10-22"
    assert len(buffered) == len(before) == len(fallback)
    assert str(after.index[-1].date()) == "2026-10-23"
    assert len(after) == len(before) + 1
    cached_partial = replace(history, fetched_at=datetime(2026, 10, 23, 19, tzinfo=UTC))
    late = completed_bars(cached_partial, datetime(2026, 10, 23, 22, tzinfo=UTC))
    assert len(late) == len(before)


def test_plan_recalculates_and_costs_reduce_reward_risk():
    free = create_trade_plan(100, 2, cost_rate=0, slippage_bps=0)
    paid = create_trade_plan(100, 2)
    moved = create_trade_plan(105, 2)
    assert (free.stop, free.target, free.net_reward_risk) == (96, 108, 2)
    assert paid.net_reward_risk < 2
    assert (moved.stop, moved.target) == (101, 113)
    with pytest.raises(TechnicalError):
        create_trade_plan(1, 2)
    with pytest.raises(TechnicalError):
        create_trade_plan(100, 2, cost_rate=np.nan)
