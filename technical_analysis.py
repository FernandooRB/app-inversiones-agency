"""Deterministic, price-only technical research; no order execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

STRATEGY_VERSION = "tendencias-confirmadas-v1"
MIN_SIGNAL_SESSIONS = 252
BUY = "Compra"
SELL = "Venta / revisar reducción"
WAIT = "Esperar"
UNAVAILABLE = "No evaluable"
OHLCV = ("Open", "High", "Low", "Close", "Volume")


class TechnicalError(ValueError):
    """An explanation safe to present to the researcher."""


@dataclass(frozen=True)
class MarketHistory:
    symbol: str
    bars: pd.DataFrame
    currency: str
    exchange: str
    timezone: str
    fetched_at: datetime
    regular_close: datetime | None = None
    source: str = "Yahoo Finance mediante yfinance"


@dataclass(frozen=True)
class Condition:
    label: str
    met: bool
    reading: str


@dataclass(frozen=True)
class TechnicalSnapshot:
    symbol: str
    signal: str
    reason: str
    as_of: date | None = None
    close: float | None = None
    daily_change: float | None = None
    relative_volume: float | None = None
    rsi: float | None = None
    indicators: pd.DataFrame = field(default_factory=pd.DataFrame)
    buy_conditions: tuple[Condition, ...] = ()
    sell_conditions: tuple[Condition, ...] = ()


@dataclass(frozen=True)
class TradePlan:
    entry: float
    stop: float
    target: float
    gross_reward_risk: float
    net_reward_risk: float


def validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Reject bad observations rather than silently shorten or fill the history."""
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        raise TechnicalError("El proveedor no devolvió sesiones con precios y volumen.")
    if bars.columns.has_duplicates or not set(OHLCV).issubset(bars.columns):
        raise TechnicalError("Faltan columnas únicas de apertura, máximo, mínimo, cierre o volumen.")
    if (
        not isinstance(bars.index, pd.DatetimeIndex)
        or bars.index.hasnans
        or bars.index.has_duplicates
        or not bars.index.is_monotonic_increasing
    ):
        raise TechnicalError("Las sesiones deben tener fechas únicas y ordenadas.")
    try:
        values = bars.loc[:, list(OHLCV)].to_numpy(dtype=float)
    except (ValueError, TypeError):
        raise TechnicalError("Los precios y el volumen deben ser numéricos.") from None
    invalid = ~np.isfinite(values) | (values <= 0)
    if invalid.any():
        row, column = np.argwhere(invalid)[0]
        labels = ("apertura", "máximo", "mínimo", "cierre", "volumen")
        raise TechnicalError(
            f"Sesión {bars.index[row].date()}: {labels[column]} ausente, no finito o menor o igual a cero."
        )
    opening, high, low, close, _volume = values.T
    if (high < np.maximum(opening, close)).any() or (low > np.minimum(opening, close)).any():
        raise TechnicalError(
            "Hay velas inconsistentes: el máximo o el mínimo no contienen apertura y cierre."
        )
    result = bars.copy()
    result[list(OHLCV)] = values
    return result


def completed_bars(history: MarketHistory, now: datetime | None = None) -> pd.DataFrame:
    """Use today's candle only with a matching, confirmed regular-session close."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise TechnicalError("La hora de evaluación necesita una zona horaria.")
    try:
        zone = ZoneInfo(history.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise TechnicalError("El proveedor no identificó una zona horaria válida para la bolsa.") from None
    bars = history.bars.copy()
    if not isinstance(bars.index, pd.DatetimeIndex) or bars.index.hasnans:
        raise TechnicalError("El proveedor no entregó fechas de sesión válidas.")
    if bars.index.tz is not None:
        bars.index = bars.index.tz_convert(zone).tz_localize(None)
    bars.index = bars.index.normalize()
    today = now.astimezone(zone).date()
    close = history.regular_close
    confirmed_today = (
        close is not None
        and close.tzinfo is not None
        and close.astimezone(zone).date() == today
        and now >= close + timedelta(minutes=15)
        and history.fetched_at.tzinfo is not None
        and history.fetched_at >= close + timedelta(minutes=15)
    )
    mask = bars.index.date <= today if confirmed_today else bars.index.date < today
    return validate_bars(bars.loc[mask])


def _wilder(series: pd.Series, period: int = 14) -> pd.Series:
    """Seed Wilder's recurrence with the first period's arithmetic average."""
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    valid = np.flatnonzero(np.isfinite(values))
    if len(valid) >= period:
        start = int(valid[0])
        seed = start + period - 1
        result[seed] = values[start:seed + 1].mean()
        for i in range(seed + 1, len(values)):
            result[i] = ((period - 1) * result[i - 1] + values[i]) / period
    return pd.Series(result, index=series.index)


def calculate_indicators(bars: pd.DataFrame) -> pd.DataFrame:
    result = validate_bars(bars)
    close = result["Close"]
    for period in (20, 50, 200):
        result[f"SMA{period}"] = close.rolling(period).mean()
    result["VolumeMean20"] = result["Volume"].shift(1).rolling(20).mean()
    result["RelativeVolume"] = result["Volume"] / result["VolumeMean20"]
    change = close.diff()
    gain = _wilder(change.clip(lower=0))
    loss = _wilder((-change).clip(lower=0))
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0)
    result["RSI14"] = rsi.mask((gain == 0) & (loss == 0), 50)
    true_range = pd.concat([
        result["High"] - result["Low"],
        (result["High"] - close.shift(1)).abs(),
        (result["Low"] - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    result["ATR14"] = _wilder(true_range)
    result["MACD"] = (
        close.ewm(span=12, adjust=False, min_periods=12).mean()
        - close.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    result["MACDSignal"] = result["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    result["MACDHistogram"] = result["MACD"] - result["MACDSignal"]
    result["Resistance20"] = result["High"].shift(1).rolling(20).max()
    result["Support20"] = result["Low"].shift(1).rolling(20).min()
    return result


def signal_conditions(indicators: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One source of truth for both snapshots and historical signals."""
    close = indicators["Close"]
    rsi = indicators["RSI14"]
    buy = pd.DataFrame({
        "Ruptura de resistencia de 20 sesiones": close > indicators["Resistance20"],
        "Cierre > media 50 > media 200": (
            (close > indicators["SMA50"]) & (indicators["SMA50"] > indicators["SMA200"])
        ),
        "Volumen relativo ≥ 1.5": indicators["RelativeVolume"] >= 1.5,
        "RSI entre 50 y 70, creciendo": rsi.between(50, 70) & (rsi > rsi.shift(1)),
        "Histograma MACD positivo": indicators["MACDHistogram"] > 0,
    }, index=indicators.index)
    sell = pd.DataFrame({
        "Ruptura de soporte de 20 sesiones": close < indicators["Support20"],
        "Volumen relativo ≥ 1.5": indicators["RelativeVolume"] >= 1.5,
        "RSI inferior a 45": rsi < 45,
        "Histograma MACD negativo": indicators["MACDHistogram"] < 0,
    }, index=indicators.index)
    return buy, sell


def historical_signals(indicators: pd.DataFrame) -> pd.DataFrame:
    buy, sell = signal_conditions(indicators)
    ready = np.arange(len(indicators)) >= MIN_SIGNAL_SESSIONS - 1
    return pd.DataFrame({"Buy": buy.all(axis=1) & ready, "Sell": sell.all(axis=1) & ready})


def analyze_history(history: MarketHistory, now: datetime | None = None) -> TechnicalSnapshot:
    now = now or datetime.now(UTC)
    try:
        bars = completed_bars(history, now)
        if not history.currency or not history.exchange:
            raise TechnicalError("El proveedor no identificó la moneda y el mercado de la serie.")
        if len(bars) < MIN_SIGNAL_SESSIONS:
            raise TechnicalError(f"Hay {len(bars)} sesiones válidas; se requieren 252.")
        today = now.astimezone(ZoneInfo(history.timezone)).date()
        if (today - bars.index[-1].date()).days > 5:
            raise TechnicalError("La última observación tiene más de cinco días naturales.")
        indicators = calculate_indicators(bars)
        buy, sell = signal_conditions(indicators)
        current, previous = indicators.iloc[-1], indicators.iloc[-2]
        buy_readings = (
            f"Cierre {current.Close:,.2f}; resistencia {current.Resistance20:,.2f}",
            f"{current.Close:,.2f} / {current.SMA50:,.2f} / {current.SMA200:,.2f}",
            f"{current.Volume:,.0f} títulos / media de 20 previas "
            f"{current.VolumeMean20:,.0f} = {current.RelativeVolume:.2f}×",
            f"RSI {current.RSI14:.2f}; anterior {previous.RSI14:.2f}",
            f"{current.MACDHistogram:,.4f}",
        )
        sell_readings = (
            f"Cierre {current.Close:,.2f}; soporte {current.Support20:,.2f}",
            buy_readings[2], buy_readings[3], buy_readings[4],
        )
        signal = BUY if buy.iloc[-1].all() else SELL if sell.iloc[-1].all() else WAIT
        if signal == BUY:
            reason = "La ruptura tiene confirmación de tendencia, volumen e impulso."
        elif signal == SELL:
            reason = "La pérdida de soporte tiene confirmación de volumen e impulso bajista."
        else:
            missing_buy = ", ".join(label for label in buy.columns if not buy.iloc[-1][label])
            missing_sell = ", ".join(label for label in sell.columns if not sell.iloc[-1][label])
            reason = (
                f"Para compra faltan: {missing_buy}. "
                f"Para venta o reducción faltan: {missing_sell}."
            )
        return TechnicalSnapshot(
            history.symbol, signal, reason, bars.index[-1].date(), float(current.Close),
            float(current.Close / previous.Close - 1), float(current.RelativeVolume),
            float(current.RSI14), indicators,
            tuple(Condition(label, bool(buy.iloc[-1][label]), reading)
                  for label, reading in zip(buy.columns, buy_readings, strict=True)),
            tuple(Condition(label, bool(sell.iloc[-1][label]), reading)
                  for label, reading in zip(sell.columns, sell_readings, strict=True)),
        )
    except TechnicalError as exc:
        return TechnicalSnapshot(history.symbol, UNAVAILABLE, str(exc))


def validate_costs(cost_rate: float, slippage_bps: float) -> None:
    if not np.isfinite(cost_rate) or not 0 <= cost_rate <= 0.1:
        raise TechnicalError("El costo por lado debe estar entre 0 % y 10 %.")
    if not np.isfinite(slippage_bps) or not 0 <= slippage_bps <= 500:
        raise TechnicalError("El deslizamiento por lado debe estar entre 0 y 500 puntos básicos.")


def create_trade_plan(
    entry: float, atr: float, *, cost_rate: float = 0.0025, slippage_bps: float = 10,
) -> TradePlan:
    validate_costs(cost_rate, slippage_bps)
    if not np.isfinite([entry, atr]).all() or entry <= 0 or atr <= 0 or entry - 2 * atr <= 0:
        raise TechnicalError("La entrada y el ATR deben permitir un stop positivo y una distancia válida.")
    stop, target = entry - 2 * atr, entry + 4 * atr
    slippage = slippage_bps / 10_000
    entry_cost = entry * (1 + slippage) * (1 + cost_rate)
    exit_factor = (1 - slippage) * (1 - cost_rate)
    net_ratio = (target * exit_factor - entry_cost) / (entry_cost - stop * exit_factor)
    return TradePlan(entry, stop, target, 2.0, float(net_ratio))
