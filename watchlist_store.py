"""Private per-OIDC-identity research lists, independent of client case storage."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from portfolio_core import PortfolioError, normalize_tickers


class WatchlistError(ValueError):
    """A safe storage or list validation explanation."""


def identity_key(issuer: str, subject: str) -> str:
    if not all(isinstance(value, str) and value.strip() for value in (issuer, subject)):
        raise WatchlistError("Se necesita una identidad OIDC verificada para guardar el seguimiento.")
    return hashlib.sha256(json.dumps([issuer, subject], ensure_ascii=True).encode()).hexdigest()


def normalize_watchlist(values: str | Iterable[str]) -> list[str]:
    values = values.split(",") if isinstance(values, str) else list(values)
    if not any(str(value).strip() for value in values):
        return []
    try:
        return normalize_tickers(values)
    except PortfolioError as exc:
        raise WatchlistError(str(exc)) from None


class WatchlistStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise WatchlistError("El archivo de seguimiento requiere una ruta absoluta privada.")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS technical_watchlists "
                "(owner TEXT PRIMARY KEY, symbols TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    def load(self, issuer: str, subject: str) -> list[str]:
        owner = identity_key(issuer, subject)
        try:
            with closing(self._connect()) as connection, connection:
                row = connection.execute(
                    "SELECT symbols FROM technical_watchlists WHERE owner = ?", (owner,)
                ).fetchone()
            if row is None:
                return []
            values = json.loads(row[0])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise WatchlistError("La lista guardada no tiene un formato válido.")
            return normalize_watchlist(values)
        except (OSError, sqlite3.Error, json.JSONDecodeError):
            raise WatchlistError("No se pudo leer el seguimiento del almacenamiento privado.") from None

    def save(self, issuer: str, subject: str, symbols: Iterable[str]) -> list[str]:
        owner = identity_key(issuer, subject)
        symbols = normalize_watchlist(symbols)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO technical_watchlists (owner, symbols, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(owner) DO UPDATE SET symbols = excluded.symbols, "
                    "updated_at = excluded.updated_at",
                    (owner, json.dumps(symbols), datetime.now(UTC).isoformat()),
                )
            return symbols
        except (OSError, sqlite3.Error):
            raise WatchlistError("No se pudo guardar la lista; revisa el almacenamiento privado.") from None
