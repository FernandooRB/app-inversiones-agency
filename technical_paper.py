"""Prospective, one-share paper observations using manually observed SIC quotes."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from technical_analysis import (
    BUY,
    SELL,
    STRATEGY_VERSION,
    WAIT,
    MarketHistory,
    TechnicalSnapshot,
)
from watchlist_store import WatchlistError, normalize_watchlist

MEXICO_CITY = ZoneInfo("America/Mexico_City")
EXIT_REASONS = ("Stop", "Objetivo", "Señal de venta", "Máximo de 20 sesiones", "Cierre manual")


class PaperError(ValueError):
    """A safe validation or storage error for the paper journal."""


@dataclass(frozen=True)
class PaperEvent:
    event_key: str
    signal_key: str
    kind: str
    ticker: str
    signal_date: date
    payload: dict
    recorded_at: datetime | None = None


@dataclass(frozen=True)
class PaperResult:
    gross_return: Decimal
    net_return: Decimal
    benchmark_net_return: Decimal | None


def signal_key(ticker: str, session: date, version: str = STRATEGY_VERSION) -> str:
    try:
        normalized = normalize_watchlist([ticker])
    except WatchlistError:
        normalized = []
    if normalized != [ticker]:
        raise PaperError("El ticker debe estar normalizado.")
    if not isinstance(session, date) or isinstance(session, datetime):
        raise PaperError("La fecha de la señal debe ser una sesión válida.")
    return f"signal:{ticker}:{session.isoformat()}:{version}"


def signal_event(snapshot: TechnicalSnapshot, history: MarketHistory) -> PaperEvent:
    if (snapshot.signal not in (BUY, WAIT, SELL) or snapshot.as_of is None
            or snapshot.close is None or snapshot.indicators.empty):
        raise PaperError("Sólo se pueden registrar señales evaluables con fecha y cierre.")
    if snapshot.symbol != history.symbol:
        raise PaperError("El símbolo de la señal no corresponde al historial.")
    if history.fetched_at.tzinfo is None:
        raise PaperError("La hora de consulta del proveedor necesita zona horaria.")
    key = signal_key(snapshot.symbol, snapshot.as_of)
    last = snapshot.indicators.iloc[-1]
    values = {
        "close": snapshot.close, "relative_volume": snapshot.relative_volume,
        "rsi": snapshot.rsi, "macd_histogram": last.get("MACDHistogram"),
    }
    try:
        valid = all(value is not None and math.isfinite(float(value))
                    for value in values.values())
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise PaperError("Faltan indicadores finitos para registrar esta señal.")
    return PaperEvent(
        key, key, "signal", snapshot.symbol, snapshot.as_of,
        {"version": 1, "strategy_version": STRATEGY_VERSION, "signal": snapshot.signal,
         "reason": snapshot.reason, "origin_currency": history.currency,
         "origin_market": history.exchange, "origin_source": history.source,
         "source_fetched_at": history.fetched_at.astimezone(UTC).isoformat(),
         **{name: str(value) for name, value in values.items()},
         "buy_checks": [{"label": c.label, "met": c.met, "reading": c.reading}
                        for c in snapshot.buy_conditions],
         "sell_checks": [{"label": c.label, "met": c.met, "reading": c.reading}
                         for c in snapshot.sell_conditions]},
    )


def _positive(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PaperError(f"{name} debe ser un número válido.") from None
    if not number.is_finite() or number <= 0:
        raise PaperError(f"{name} debe ser positivo y finito.")
    return number


def _fee(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PaperError("El costo por lado debe ser válido.") from None
    if not number.is_finite() or not Decimal(0) <= number <= Decimal("0.1"):
        raise PaperError("El costo por lado debe estar entre 0 % y 10 %.")
    return number


def _identity(symbol: str, isin: str) -> tuple[str, str]:
    symbol, isin = symbol.strip().upper(), isin.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.* /-]{1,32}", symbol):
        raise PaperError("Indica la serie SIC exactamente como aparece en GBM.")
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        raise PaperError("Indica un ISIN de 12 caracteres para la serie local.")
    return symbol, isin


def _recent_quote(quote_at: datetime, now: datetime) -> datetime:
    if quote_at.tzinfo is None or now.tzinfo is None:
        raise PaperError("La cotización necesita fecha, hora y zona horaria.")
    age = (now - quote_at).total_seconds()
    if age < 0 or age > 15 * 60:
        raise PaperError("La cotización SIC debe tener 15 minutos o menos al registrarse.")
    return quote_at.astimezone(UTC)


def entry_event(
    signal: PaperEvent, *, local_symbol: str, local_isin: str,
    quote_at: datetime, bid_mxn: object, ask_mxn: object, volume: int,
    stop_mxn: object, target_mxn: object, cost_rate: object,
    benchmark_symbol: str = "", benchmark_isin: str = "",
    benchmark_ask_mxn: object | None = None, benchmark_bid_mxn: object | None = None,
    benchmark_volume: int | None = None, now: datetime | None = None,
) -> PaperEvent:
    now = now or datetime.now(UTC)
    if signal.kind != "signal" or signal.payload.get("signal") != BUY or signal.recorded_at is None:
        raise PaperError("La entrada en papel exige una señal Compra previamente registrada.")
    quote_utc = _recent_quote(quote_at, now)
    if quote_at.astimezone(MEXICO_CITY).date() <= signal.signal_date:
        raise PaperError("La entrada SIC debe registrarse después de la sesión de la señal.")
    # Minute-resolution quote widgets can be at most 59 seconds before the recorded signal time.
    if quote_utc < signal.recorded_at.astimezone(UTC).replace(second=0, microsecond=0):
        raise PaperError("Registra primero la señal y después una cotización SIC nueva.")
    local_symbol, local_isin = _identity(local_symbol, local_isin)
    bid, ask = _positive(bid_mxn, "Bid SIC"), _positive(ask_mxn, "Ask SIC")
    stop, target = _positive(stop_mxn, "Stop SIC"), _positive(target_mxn, "Objetivo SIC")
    fee = _fee(cost_rate)
    if bid > ask or not stop < ask < target or type(volume) is not int or volume < 1:
        raise PaperError("Revisa bid ≤ ask, stop < ask < objetivo y volumen SIC positivo.")
    if target * (1 - fee) <= ask * (1 + fee):
        raise PaperError("El objetivo local no deja beneficio después de los costos supuestos.")
    benchmark = None
    benchmark_fields = (benchmark_symbol, benchmark_isin, benchmark_ask_mxn,
                        benchmark_bid_mxn, benchmark_volume)
    if any(value not in ("", None) for value in benchmark_fields):
        benchmark_symbol, benchmark_isin = _identity(benchmark_symbol, benchmark_isin)
        benchmark_bid = _positive(benchmark_bid_mxn, "Bid de referencia")
        benchmark_ask = _positive(benchmark_ask_mxn, "Ask de referencia")
        if benchmark_bid > benchmark_ask or type(benchmark_volume) is not int or benchmark_volume < 1:
            raise PaperError("La referencia necesita bid ≤ ask y volumen positivo.")
        benchmark = {"symbol": benchmark_symbol, "isin": benchmark_isin,
                     "bid_mxn": str(benchmark_bid), "ask_mxn": str(benchmark_ask),
                     "volume": benchmark_volume}
    return PaperEvent(
        signal.signal_key + ":entry", signal.signal_key, "entry", signal.ticker,
        signal.signal_date,
        {"version": 1, "source": "GBM, captura manual", "quote_at": quote_utc.isoformat(),
         "local_symbol": local_symbol, "local_isin": local_isin,
         "bid_mxn": str(bid), "ask_mxn": str(ask), "volume": volume,
         "stop_mxn": str(stop), "target_mxn": str(target),
         "cost_rate": str(fee), "quantity": 1, "benchmark": benchmark},
    )


def exit_event(
    entry: PaperEvent, *, quote_at: datetime, bid_mxn: object, volume: int,
    reason: str, benchmark_bid_mxn: object | None = None,
    benchmark_volume: int | None = None, now: datetime | None = None,
) -> PaperEvent:
    now = now or datetime.now(UTC)
    if entry.kind != "entry" or entry.recorded_at is None:
        raise PaperError("La salida exige una entrada en papel ya guardada.")
    quote_utc = _recent_quote(quote_at, now)
    if quote_utc < entry.recorded_at.astimezone(UTC).replace(second=0, microsecond=0):
        raise PaperError("La salida no puede tener una cotización anterior a la entrada.")
    bid = _positive(bid_mxn, "Bid de salida SIC")
    if type(volume) is not int or volume < 1 or reason not in EXIT_REASONS:
        raise PaperError("Indica volumen local positivo y motivo de salida válido.")
    benchmark = entry.payload.get("benchmark")
    benchmark_exit = None
    if benchmark_bid_mxn is not None or benchmark_volume is not None:
        if not benchmark:
            raise PaperError("No se puede añadir una referencia sólo al salir.")
        benchmark_bid = _positive(benchmark_bid_mxn, "Bid de salida de referencia")
        if type(benchmark_volume) is not int or benchmark_volume < 1:
            raise PaperError("El volumen de referencia de salida debe ser positivo.")
        benchmark_exit = {"bid_mxn": str(benchmark_bid), "volume": benchmark_volume}
    return PaperEvent(
        entry.signal_key + ":exit", entry.signal_key, "exit", entry.ticker,
        entry.signal_date,
        {"version": 1, "source": "GBM, captura manual", "quote_at": quote_utc.isoformat(),
         "bid_mxn": str(bid), "volume": volume, "reason": reason,
         "benchmark": benchmark_exit},
    )


def paper_result(entry: PaperEvent, exit: PaperEvent) -> PaperResult:
    if entry.kind != "entry" or exit.kind != "exit" or entry.signal_key != exit.signal_key:
        raise PaperError("La entrada y salida no pertenecen a la misma prueba.")
    ask = _positive(entry.payload.get("ask_mxn"), "Ask de entrada")
    bid = _positive(exit.payload.get("bid_mxn"), "Bid de salida")
    fee = _fee(entry.payload.get("cost_rate"))
    gross = bid / ask - 1
    net = bid * (1 - fee) / (ask * (1 + fee)) - 1
    reference = None
    if entry.payload.get("benchmark") and exit.payload.get("benchmark"):
        reference_ask = _positive(entry.payload["benchmark"].get("ask_mxn"), "Ask de referencia")
        reference_bid = _positive(exit.payload["benchmark"].get("bid_mxn"), "Bid de referencia")
        reference = reference_bid * (1 - fee) / (reference_ask * (1 + fee)) - 1
    return PaperResult(gross, net, reference)
