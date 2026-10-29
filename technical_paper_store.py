"""Insert-only, per-OIDC paper journal in private SQLite or server-side Supabase."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from supabase_watchlist import SupabaseWatchlistStore
from technical_analysis import BUY
from technical_paper import PaperError, PaperEvent
from watchlist_store import WatchlistError, WatchlistStore, identity_key, normalize_watchlist

MAX_EVENTS = 2000
PAGE_SIZE = 500
FIELDS = "event_key,signal_key,kind,ticker,signal_date,payload,recorded_at"


def paper_store_for(store: WatchlistStore | SupabaseWatchlistStore):
    if isinstance(store, SupabaseWatchlistStore):
        return SupabasePaperStore(store)
    return SQLitePaperStore(store.path.with_suffix(".paper.db"))


def _event_from_row(row: dict) -> PaperEvent:
    try:
        kind = row["kind"]
        event_key = row["event_key"]
        signal_key = row["signal_key"]
        ticker = row["ticker"]
        signal_date = date.fromisoformat(row["signal_date"])
        recorded_at = datetime.fromisoformat(row["recorded_at"])
        payload = row["payload"]
        expected = signal_key if kind == "signal" else signal_key + f":{kind}"
        if (
            kind not in ("signal", "entry", "exit") or event_key != expected
            or normalize_watchlist([ticker]) != [ticker]
            or not isinstance(payload, dict) or recorded_at.tzinfo is None
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError, WatchlistError):
        raise PaperError("La bitácora guardada contiene un registro inválido.") from None
    return PaperEvent(event_key, signal_key, kind, ticker, signal_date, payload, recorded_at)


def _check_append(event: PaperEvent, existing: list[PaperEvent]):
    if event.recorded_at is not None or event.kind not in ("signal", "entry", "exit"):
        raise PaperError("El registro en papel tiene un tipo o fecha inválida.")
    expected = event.signal_key if event.kind == "signal" else event.signal_key + f":{event.kind}"
    if event.event_key != expected or normalize_watchlist([event.ticker]) != [event.ticker]:
        raise PaperError("La clave del registro en papel no coincide con la señal.")
    if any(item.event_key == event.event_key for item in existing):
        raise PaperError("Esta observación ya está registrada; no se sobrescribe.")
    signals = [item for item in existing if item.event_key == event.signal_key and item.kind == "signal"]
    if event.kind in ("entry", "exit") and (
        len(signals) != 1 or signals[0].ticker != event.ticker
        or signals[0].signal_date != event.signal_date
    ):
        raise PaperError("Registra primero la señal correspondiente.")
    if event.kind == "entry" and signals[0].payload.get("signal") != BUY:
        raise PaperError("Sólo una señal Compra permite una entrada simulada.")
    if event.kind == "exit" and not any(
        item.event_key == event.signal_key + ":entry" for item in existing
    ):
        raise PaperError("Registra primero la entrada simulada.")
    if len(existing) >= MAX_EVENTS:
        raise PaperError("La bitácora llegó a su límite; exporta el historial antes de continuar.")


class SQLitePaperStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise PaperError("La bitácora SQLite requiere una ruta privada absoluta.")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS technical_paper_events ("
            "owner TEXT NOT NULL, event_key TEXT NOT NULL, signal_key TEXT NOT NULL, "
            "kind TEXT NOT NULL, ticker TEXT NOT NULL, signal_date TEXT NOT NULL, "
            "payload TEXT NOT NULL, recorded_at TEXT NOT NULL, "
            "PRIMARY KEY (owner, event_key))"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS paper_events_owner_time "
            "ON technical_paper_events (owner, recorded_at, event_key)"
        )
        return connection

    def load(self, issuer: str, subject: str) -> list[PaperEvent]:
        owner = identity_key(issuer, subject)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT {FIELDS} FROM technical_paper_events WHERE owner = ? "
                    "ORDER BY recorded_at, event_key LIMIT ?", (owner, MAX_EVENTS + 1),
                ).fetchall()
        except (OSError, sqlite3.Error):
            raise PaperError("No se pudo leer la bitácora privada.") from None
        if len(rows) > MAX_EVENTS:
            raise PaperError("La bitácora excede el límite de lectura; requiere exportación administrativa.")
        try:
            return [_event_from_row(dict(zip(FIELDS.split(","),
                                             (*row[:5], json.loads(row[5]), row[6]), strict=True)))
                    for row in rows]
        except (json.JSONDecodeError, TypeError):
            raise PaperError("La bitácora guardada contiene JSON inválido.") from None

    def append(self, issuer: str, subject: str, event: PaperEvent) -> PaperEvent:
        existing = self.load(issuer, subject)
        _check_append(event, existing)
        owner = identity_key(issuer, subject)
        timestamp = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    "INSERT INTO technical_paper_events "
                    "(owner,event_key,signal_key,kind,ticker,signal_date,payload,recorded_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (owner, event.event_key, event.signal_key, event.kind, event.ticker,
                     event.signal_date.isoformat(), json.dumps(event.payload, ensure_ascii=False),
                     timestamp),
                )
        except sqlite3.IntegrityError:
            raise PaperError("Esta observación ya está registrada; no se sobrescribe.") from None
        except (OSError, sqlite3.Error):
            raise PaperError("No se pudo guardar la bitácora privada.") from None
        return PaperEvent(event.event_key, event.signal_key, event.kind, event.ticker,
                          event.signal_date, event.payload, datetime.fromisoformat(timestamp))


class SupabasePaperStore:
    def __init__(self, watchlist_store: SupabaseWatchlistStore):
        self.endpoint = (
            watchlist_store.endpoint.removesuffix("technical_watchlists")
            + "technical_paper_events"
        )
        self.secret_key = watchlist_store.secret_key
        self.client = watchlist_store.client

    def _request(self, method: str, **kwargs) -> httpx.Response:
        headers = {"apikey": self.secret_key, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        if self.client is not None:
            return self.client.request(method, self.endpoint, headers=headers,
                                       timeout=10.0, follow_redirects=False, **kwargs)
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            return client.request(method, self.endpoint, headers=headers, **kwargs)

    def load(self, issuer: str, subject: str) -> list[PaperEvent]:
        owner = identity_key(issuer, subject)
        try:
            rows = []
            while True:
                response = self._request("GET", params={
                    "owner": f"eq.{owner}", "select": FIELDS,
                    "order": "recorded_at.asc,event_key.asc",
                    "limit": str(PAGE_SIZE), "offset": str(len(rows)),
                })
                if response.status_code != 200:
                    raise PaperError("No se pudo leer la bitácora en Supabase; revisa la tabla.")
                page = response.json()
                if not isinstance(page, list) or len(page) > PAGE_SIZE:
                    raise PaperError("Supabase devolvió una bitácora con formato inválido.")
                rows.extend(page)
                if len(rows) > MAX_EVENTS:
                    raise PaperError(
                        "La bitácora excede el límite de lectura; requiere exportación administrativa."
                    )
                if len(page) < PAGE_SIZE:
                    break
            return [_event_from_row(row) for row in rows]
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, PaperError):
                raise
            raise PaperError("No se pudo leer la bitácora en Supabase.") from None

    def append(self, issuer: str, subject: str, event: PaperEvent) -> PaperEvent:
        _check_append(event, self.load(issuer, subject))
        owner = identity_key(issuer, subject)
        try:
            response = self._request(
                "POST", headers={"Prefer": "return=representation"},
                json={"owner": owner, "event_key": event.event_key,
                      "signal_key": event.signal_key, "kind": event.kind,
                      "ticker": event.ticker, "signal_date": event.signal_date.isoformat(),
                      "payload": event.payload},
            )
            if response.status_code == 409:
                raise PaperError("Esta observación ya está registrada; no se sobrescribe.")
            if response.status_code != 201:
                raise PaperError("No se pudo guardar la bitácora en Supabase; revisa la tabla.")
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != 1:
                raise PaperError("Supabase no confirmó el registro guardado.")
            return _event_from_row(rows[0])
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, PaperError):
                raise
            raise PaperError("No se pudo guardar la bitácora en Supabase.") from None
