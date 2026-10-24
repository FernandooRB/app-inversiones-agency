"""OHLCV adapter kept separate from the optimizer's adjusted-close download."""

from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from portfolio_core import PortfolioError, normalize_tickers
from technical_analysis import MarketHistory, TechnicalError


def download_market_history(symbol: str) -> MarketHistory:
    try:
        symbols = normalize_tickers([symbol])
    except PortfolioError as exc:
        raise TechnicalError(str(exc)) from None
    ticker = yf.Ticker(symbols[0])
    try:
        bars = ticker.history(
            period="5y", interval="1d", auto_adjust=False, back_adjust=False,
            actions=True, repair=False, raise_errors=True, timeout=12,
        )
        metadata = ticker.get_history_metadata() or {}
    except Exception:
        raise TechnicalError("No fue posible consultar precios, volumen y metadatos del proveedor.") from None
    if not isinstance(bars, pd.DataFrame) or bars.empty or not isinstance(bars.index, pd.DatetimeIndex):
        raise TechnicalError("El proveedor no devolvió sesiones para este ticker.")
    if not isinstance(metadata, dict):
        raise TechnicalError("El proveedor no devolvió metadatos válidos para este ticker.")
    periods = metadata.get("currentTradingPeriod") or {}
    regular = (periods.get("regular") or {}) if isinstance(periods, dict) else {}
    regular_close = None
    try:
        end = regular.get("end") if isinstance(regular, dict) else None
        if isinstance(end, datetime):
            regular_close = end.astimezone(UTC) if end.tzinfo is not None else None
        elif end is not None:
            regular_close = datetime.fromtimestamp(float(end), UTC)
    except (ValueError, TypeError, OverflowError, OSError):
        regular_close = None
    timezone = metadata.get("exchangeTimezoneName") or str(bars.index.tz or "")
    return MarketHistory(
        symbol=symbols[0], bars=bars, currency=str(metadata.get("currency") or ""),
        exchange=str(metadata.get("fullExchangeName") or metadata.get("exchangeName") or ""),
        timezone=timezone, fetched_at=datetime.now(UTC), regular_close=regular_close,
    )
