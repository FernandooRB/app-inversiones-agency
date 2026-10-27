"""Durable insert-only paper order claims and observations, isolated by OIDC owner/account."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from alpaca_order_models import CLIENT_ID, LimitDraft
from alpaca_paper import AlpacaPaperError
from supabase_watchlist import SupabaseWatchlistStore
from watchlist_store import WatchlistStore, identity_key

FIELDS = "event_seq,account_id,client_order_id,event_key,kind,payload,recorded_at"
KINDS = ("intent", "accepted", "rejected", "unknown", "observed")
MAX_EVENTS = 5000
PAGE_SIZE = 500


class OrderAlreadyRecorded(AlpacaPaperError):
    """The immutable intent was claimed by another request; never submit it again."""


@dataclass(frozen=True)
class OrderEvent:
    sequence: int
    account_id: str
    client_order_id: str
    event_key: str
    kind: str
    payload: dict
    recorded_at: datetime


def _row(row) -> OrderEvent:
    try:
        event = OrderEvent(int(row["event_seq"]), str(UUID(row["account_id"])), row["client_order_id"],
                           row["event_key"], row["kind"], row["payload"],
                           datetime.fromisoformat(row["recorded_at"]))
        if (not CLIENT_ID.fullmatch(event.client_order_id) or event.kind not in KINDS
                or not isinstance(event.payload, dict) or event.recorded_at.tzinfo is None):
            raise ValueError
        if event.kind == "intent":
            if event.event_key != event.client_order_id:
                raise ValueError
            draft = LimitDraft.from_json(event.account_id, event.payload)
            if draft.client_order_id != event.client_order_id:
                raise ValueError
        else:
            UUID(event.event_key)
        return event
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AlpacaPaperError("El registro de órdenes Paper contiene un evento inválido.") from None


def _input(account_id, client_order_id, kind, payload):
    try:
        account_id = str(UUID(account_id))
        if kind not in KINDS or not CLIENT_ID.fullmatch(client_order_id) or not isinstance(payload, dict):
            raise ValueError
        if kind == "intent":
            draft = LimitDraft.from_json(account_id, payload)
            if draft.client_order_id != client_order_id:
                raise ValueError
        if len(json.dumps(payload, allow_nan=False).encode()) > 8192:
            raise ValueError
        key = client_order_id if kind == "intent" else str(uuid4())
        return account_id, key
    except (TypeError, ValueError, AttributeError):
        raise AlpacaPaperError("El evento de la orden Paper no es válido para guardarse.") from None


class SQLiteOrderStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise AlpacaPaperError("El registro de órdenes requiere una ruta privada absoluta.")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alpaca_paper_order_events ("
            "event_seq INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, "
            "account_id TEXT NOT NULL, client_order_id TEXT NOT NULL, event_key TEXT NOT NULL, "
            "kind TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL, "
            "UNIQUE(owner,account_id,event_key), "
            "FOREIGN KEY(owner,account_id,client_order_id) "
            "REFERENCES alpaca_paper_order_events(owner,account_id,event_key))"
        )
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS alpaca_intent_unique "
                           "ON alpaca_paper_order_events(account_id,event_key) WHERE kind='intent'")
        connection.execute("CREATE INDEX IF NOT EXISTS alpaca_events_owner_account_seq "
                           "ON alpaca_paper_order_events(owner,account_id,event_seq)")
        return connection

    def load(self, issuer: str, subject: str, account_id: str) -> list[OrderEvent]:
        owner = identity_key(issuer, subject)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT {FIELDS} FROM alpaca_paper_order_events WHERE owner=? AND account_id=? "
                    "ORDER BY event_seq LIMIT ?", (owner, str(UUID(account_id)), MAX_EVENTS + 1),
                ).fetchall()
            if len(rows) > MAX_EVENTS:
                raise AlpacaPaperError("El registro Paper requiere una exportación administrativa.")
            return [_row(dict(zip(FIELDS.split(","), (*r[:5], json.loads(r[5]), r[6]), strict=True)))
                    for r in rows]
        except (OSError, sqlite3.Error, ValueError) as exc:
            if isinstance(exc, AlpacaPaperError):
                raise
            raise AlpacaPaperError("No se pudo leer el registro privado de órdenes Paper.") from None

    def append(self, issuer, subject, account_id, client_order_id, kind, payload) -> OrderEvent:
        owner = identity_key(issuer, subject)
        account_id, key = _input(account_id, client_order_id, kind, payload)
        timestamp = datetime.now(UTC).isoformat()
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    "INSERT INTO alpaca_paper_order_events "
                    "(owner,account_id,client_order_id,event_key,kind,payload,recorded_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (owner, account_id, client_order_id, key, kind, json.dumps(payload), timestamp),
                )
                sequence = cursor.lastrowid
        except sqlite3.IntegrityError:
            if kind == "intent":
                raise OrderAlreadyRecorded("El intento ya está registrado; consulta su estado.") from None
            raise AlpacaPaperError(
                "La observación no tiene un intento registrado para este usuario y cuenta."
            ) from None
        except (OSError, sqlite3.Error):
            raise AlpacaPaperError("No se pudo guardar el registro de órdenes Paper.") from None
        values = (sequence, account_id, client_order_id, key, kind, payload, timestamp)
        return _row(dict(zip(FIELDS.split(","), values, strict=True)))


class SupabaseOrderStore:
    def __init__(self, watchlist: SupabaseWatchlistStore):
        self.endpoint = watchlist.endpoint.removesuffix("technical_watchlists") + "alpaca_paper_order_events"
        self._secret_key, self._client = watchlist.secret_key, watchlist.client

    def _request(self, method, **kwargs):
        headers = {"apikey": self._secret_key, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        if self._client is not None:
            return self._client.request(method, self.endpoint, headers=headers, timeout=10,
                                        follow_redirects=False, **kwargs)
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            return client.request(method, self.endpoint, headers=headers, **kwargs)

    def load(self, issuer, subject, account_id) -> list[OrderEvent]:
        owner = identity_key(issuer, subject)
        try:
            account_id = str(UUID(account_id))
            rows = []
            while True:
                response = self._request("GET", params={"owner": f"eq.{owner}",
                    "account_id": f"eq.{account_id}", "select": FIELDS, "order": "event_seq.asc",
                    "limit": str(PAGE_SIZE), "offset": str(len(rows))})
                if response.status_code != 200:
                    raise AlpacaPaperError("No se pudo leer el registro Paper en Supabase.")
                page = response.json()
                if not isinstance(page, list) or len(page) > PAGE_SIZE:
                    raise ValueError
                rows.extend(page)
                if len(rows) > MAX_EVENTS:
                    raise AlpacaPaperError("El registro Paper requiere una exportación administrativa.")
                if len(page) < PAGE_SIZE:
                    break
            return [_row(row) for row in rows]
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, AlpacaPaperError):
                raise
            raise AlpacaPaperError("No se pudo leer el registro Paper en Supabase.") from None

    def append(self, issuer, subject, account_id, client_order_id, kind, payload) -> OrderEvent:
        owner = identity_key(issuer, subject)
        account_id, key = _input(account_id, client_order_id, kind, payload)
        try:
            response = self._request("POST", headers={"Prefer": "return=representation"}, json={
                "owner": owner, "account_id": account_id, "client_order_id": client_order_id,
                "event_key": key, "kind": kind, "payload": payload})
            if response.status_code == 409 and kind == "intent":
                raise OrderAlreadyRecorded("El intento ya está registrado; consulta su estado.")
            if response.status_code != 201:
                raise AlpacaPaperError("No se pudo guardar el registro Paper en Supabase.")
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError
            return _row(rows[0])
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, AlpacaPaperError):
                raise
            raise AlpacaPaperError(
                "Supabase no confirmó el registro Paper; revisa los intentos antes de continuar."
            ) from None


def order_store_for(watchlist: WatchlistStore | SupabaseWatchlistStore):
    if isinstance(watchlist, SupabaseWatchlistStore):
        return SupabaseOrderStore(watchlist)
    return SQLiteOrderStore(watchlist.path.with_suffix(".alpaca-orders.db"))
