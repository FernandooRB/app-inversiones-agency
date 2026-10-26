"""Portable, owner-free backup of one authorized user's ticker list."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from watchlist_store import WatchlistError, normalize_watchlist

BACKUP_FORMAT = "sig-technical-watchlist"
MAX_BACKUP_BYTES = 8192


def export_watchlist(symbols: list[str], *, now: datetime | None = None) -> bytes:
    normalized = normalize_watchlist(symbols)
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    payload = {
        "format": BACKUP_FORMAT,
        "version": 1,
        "exported_at": moment.isoformat(),
        "symbols": normalized,
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def import_watchlist(contents: bytes) -> list[str]:
    if not isinstance(contents, bytes) or not 0 < len(contents) <= MAX_BACKUP_BYTES:
        raise WatchlistError("El respaldo está vacío o supera 8 KB.")
    try:
        payload = json.loads(contents.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise WatchlistError("El respaldo no es JSON UTF-8 válido.") from None
    if not isinstance(payload, dict) or set(payload) != {"format", "version", "exported_at", "symbols"}:
        raise WatchlistError("El respaldo no tiene el formato de Seguimiento esperado.")
    if payload["format"] != BACKUP_FORMAT or type(payload["version"]) is not int or payload["version"] != 1:
        raise WatchlistError("La versión del respaldo no es compatible.")
    try:
        timestamp = datetime.fromisoformat(payload["exported_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise WatchlistError("El respaldo no tiene una fecha válida con zona horaria.") from None
    symbols = payload["symbols"]
    if not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols):
        raise WatchlistError("El respaldo no contiene una lista de tickers válida.")
    normalized = normalize_watchlist(symbols)
    if normalized != symbols:
        raise WatchlistError("Los tickers del respaldo deben estar normalizados y sin duplicados.")
    return normalized
