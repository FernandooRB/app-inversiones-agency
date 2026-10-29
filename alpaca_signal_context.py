"""Immutable, prospective links from Paper proposals to saved technical observations."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from alpaca_paper import AlpacaPaperError
from technical_analysis import BUY, SELL, STRATEGY_VERSION, WAIT


def context_json(row: dict, symbol: str, prepared_at: datetime) -> str:
    """Validate a persisted snapshot, including its chronology; never infer past signals."""
    try:
        payload = row["observation"]
        session = date.fromisoformat(row["session"])
        captured = datetime.fromisoformat(row["recorded_at"])
        fetched = datetime.fromisoformat(payload["source_fetched_at"])
        version = payload["strategy_version"]
        if (row["ticker"] != symbol or row["key"] != f"signal:{symbol}:{session}:{version}"
                or payload["origin_currency"] != "USD" or payload["signal"] not in (BUY, SELL, WAIT)
                or prepared_at.tzinfo is None or captured.tzinfo is None or fetched.tzinfo is None
                or not fetched <= captured <= prepared_at
                or session > prepared_at.astimezone(ZoneInfo("America/New_York")).date()):
            raise ValueError
        for name in ("reason", "origin_source", "origin_market", "strategy_version"):
            if not isinstance(payload[name], str) or not 0 < len(payload[name]) <= 2500:
                raise ValueError
        for name in ("close", "relative_volume", "rsi", "macd_histogram"):
            value = Decimal(str(payload[name]))
            if not value.is_finite():
                raise ValueError
        atr = payload.get("atr")
        if atr is not None and (not Decimal(str(atr)).is_finite() or Decimal(str(atr)) <= 0):
            raise ValueError
        for name in ("buy_checks", "sell_checks"):
            if not isinstance(payload[name], list) or any(
                not isinstance(check, dict) or type(check.get("met")) is not bool
                or not isinstance(check.get("label"), str) for check in payload[name]
            ):
                raise ValueError
        result = json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(result.encode()) > 6000:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise AlpacaPaperError(
            "La señal debe ser del mismo ticker, en USD y guardada antes de la propuesta."
        ) from None


def saved_context(signal_store, issuer, subject, key, symbol, prepared_at):
    from technical_paper import PaperError

    try:
        event = next((e for e in signal_store.load(issuer, subject)
                      if e.kind == "signal" and e.event_key == key), None)
        if event is None or event.recorded_at is None:
            raise AlpacaPaperError("No existe esa señal congelada para tu usuario.")
        return context_json({"key": event.event_key, "ticker": event.ticker,
                             "session": event.signal_date.isoformat(),
                             "recorded_at": event.recorded_at.isoformat(),
                             "observation": event.payload}, symbol, prepared_at)
    except PaperError:
        raise AlpacaPaperError(
            "No se pudo verificar la señal congelada; vuelve a preparar la propuesta."
        ) from None


def alignment(draft) -> str:
    if not draft.research_json:
        return "Prueba técnica · sin señal previa vinculada"
    row = json.loads(draft.research_json)
    payload = row["observation"]
    signal, checks = ((BUY, "buy_checks") if draft.side == "buy" else (SELL, "sell_checks"))
    age = (draft.prepared_at.astimezone(ZoneInfo("America/New_York")).date()
           - date.fromisoformat(row["session"])).days
    expected_count = 5 if draft.side == "buy" else 4
    if (payload["signal"] == signal and payload["strategy_version"] == STRATEGY_VERSION
            and 0 <= age <= 5 and len(payload[checks]) == expected_count
            and all(check["met"] for check in payload[checks])):
        return "Coincide con la señal guardada"
    return "Prueba manual · señal de referencia sin confirmación de la estrategia"


def reference_levels(draft, entry):
    if draft.side != "buy" or not draft.research_json:
        return None
    atr = json.loads(draft.research_json)["observation"].get("atr")
    if atr is None:
        return None
    atr, entry = Decimal(str(atr)), Decimal(str(entry))
    if entry <= 2 * atr:
        return None
    return entry - 2 * atr, entry + 4 * atr
