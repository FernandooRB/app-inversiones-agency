"""Insert-only trial settings, exit plans, broker fills and in-app alerts, scoped by owner/account."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from alpaca_paper import AlpacaPaperError, PaperFill
from supabase_watchlist import SupabaseWatchlistStore
from watchlist_store import identity_key

KINDS = {"settings", "plan", "fill", "fills_sync", "alert", "ack", "observation"}
FIELDS = "event_seq,account_id,event_key,kind,payload,recorded_at"
MAX_EVENTS = 10000
PAGE_SIZE = 500


@dataclass(frozen=True)
class TrialEvent:
    sequence: int
    account_id: str
    key: str
    kind: str
    payload: dict
    recorded_at: datetime


def stable_key(kind, value):
    return kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def event_input(account_id, kind, payload, key=None):
    try:
        account_id = str(UUID(account_id))
        key = key or kind + ":" + uuid4().hex
        if (
            kind not in KINDS
            or not re.fullmatch(r"[a-z_]+:[0-9a-f]{32,64}", key)
            or not key.startswith(kind + ":")
            or not isinstance(payload, dict)
            or len(json.dumps(payload, allow_nan=False).encode()) > 8192
        ):
            raise ValueError
        if kind == "fill":
            fill = PaperFill.from_json(payload)
            if key != stable_key("fill", fill.id):
                raise ValueError
        elif kind == "settings":
            from alpaca_risk import settings_payload

            expected = settings_payload(
                *(
                    payload[name]
                    for name in ("capital", "max_loss", "max_position", "max_order_loss", "cost_rate")
                ),
                started_at=payload["started_at"],
            )
            if expected != payload:
                raise ValueError
        elif kind == "plan":
            from datetime import date
            from decimal import Decimal

            from alpaca_order_models import limit_inputs

            limit_inputs(payload["symbol"], "buy", 1, "1")
            if not 0 < Decimal(payload["stop"]) < Decimal(payload["reference"]) < Decimal(payload["target"]):
                raise ValueError
            date.fromisoformat(payload["review_on"])
            if not isinstance(payload["reason"], str) or payload.get("protection") != "reference_only":
                raise ValueError
        return account_id, key
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        raise AlpacaPaperError("El registro de control de la prueba contiene datos inválidos.") from None


def event_row(row):
    try:
        account, key = event_input(row["account_id"], row["kind"], row["payload"], row["event_key"])
        stamp = datetime.fromisoformat(row["recorded_at"])
        if stamp.tzinfo is None:
            raise ValueError
        return TrialEvent(int(row["event_seq"]), account, key, row["kind"], row["payload"], stamp)
    except (KeyError, TypeError, ValueError):
        raise AlpacaPaperError("No se pudo interpretar el registro privado de la prueba.") from None


def ensure_sqlite_table(connection):
    connection.execute(
        "CREATE TABLE IF NOT EXISTS alpaca_trial_events (event_seq INTEGER PRIMARY KEY "
        "AUTOINCREMENT,owner TEXT NOT NULL,account_id TEXT NOT NULL,event_key TEXT NOT NULL,"
        "kind TEXT NOT NULL,payload TEXT NOT NULL,recorded_at TEXT NOT NULL,"
        "UNIQUE(owner,account_id,event_key))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS alpaca_trial_owner_account_seq "
        "ON alpaca_trial_events(owner,account_id,event_seq)"
    )


class SQLiteTrialStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise AlpacaPaperError("El control de la prueba requiere una ruta privada absoluta.")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        ensure_sqlite_table(connection)
        return connection

    def load(self, issuer, subject, account_id):
        owner = identity_key(issuer, subject)
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT {FIELDS} FROM alpaca_trial_events "
                    "WHERE owner=? AND account_id=? ORDER BY event_seq LIMIT ?",
                    (owner, str(UUID(account_id)), MAX_EVENTS + 1),
                ).fetchall()
            if len(rows) > MAX_EVENTS:
                raise AlpacaPaperError("El control de la prueba requiere exportación administrativa.")
            return [
                event_row(dict(zip(FIELDS.split(","), (*r[:4], json.loads(r[4]), r[5]), strict=True)))
                for r in rows
            ]
        except (OSError, sqlite3.Error, ValueError):
            raise AlpacaPaperError("No se pudo leer el control privado de la prueba.") from None

    def append(self, issuer, subject, account_id, kind, payload, *, key=None):
        owner = identity_key(issuer, subject)
        account, key = event_input(account_id, kind, payload, key)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                duplicate = connection.execute("SELECT 1 FROM alpaca_trial_events "
                    "WHERE owner=? AND account_id=? AND event_key=?", (owner, account, key)).fetchone()
                if not duplicate and connection.execute("SELECT count(*) FROM alpaca_trial_events "
                    "WHERE owner=? AND account_id=?", (owner, account)).fetchone()[0] >= MAX_EVENTS:
                    raise AlpacaPaperError("El control de la prueba requiere exportación administrativa.")
                connection.execute(
                    "INSERT OR IGNORE INTO alpaca_trial_events "
                    "(owner,account_id,event_key,kind,payload,recorded_at) VALUES (?,?,?,?,?,?)",
                    (owner, account, key, kind, json.dumps(payload), datetime.now(UTC).isoformat()),
                )
                row = connection.execute(
                    f"SELECT {FIELDS} FROM alpaca_trial_events "
                    "WHERE owner=? AND account_id=? AND event_key=?",
                    (owner, account, key),
                ).fetchone()
                saved = event_row(
                    dict(zip(FIELDS.split(","), (*row[:4], json.loads(row[4]), row[5]), strict=True))
                )
                if saved.kind != kind or (
                    saved.payload != payload and kind not in {"alert", "observation", "ack"}
                ):
                    raise AlpacaPaperError(
                        "La ejecución o alerta ya existe con datos distintos; requiere revisión."
                    )
                return saved
        except (OSError, sqlite3.Error):
            raise AlpacaPaperError("No se pudo guardar el control privado de la prueba.") from None


class SupabaseTrialStore:
    def __init__(self, watchlist):
        self.base = watchlist.endpoint.removesuffix("technical_watchlists")
        self.secret, self.client = watchlist.secret_key, watchlist.client

    def request(self, method, resource, **kwargs):
        headers = {"apikey": self.secret, "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        try:
            if self.client is not None:
                return self.client.request(
                    method,
                    self.base + resource,
                    headers=headers,
                    timeout=10,
                    follow_redirects=False,
                    **kwargs,
                )
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                return client.request(method, self.base + resource, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise AlpacaPaperError("No se pudo consultar el control de la prueba en Supabase.") from None

    def load(self, issuer, subject, account_id):
        owner = identity_key(issuer, subject)
        account = str(UUID(account_id))
        rows = []
        try:
            while True:
                response = self.request(
                    "GET",
                    "alpaca_trial_events",
                    params={
                        "owner": f"eq.{owner}",
                        "account_id": f"eq.{account}",
                        "select": FIELDS,
                        "order": "event_seq.asc",
                        "limit": str(PAGE_SIZE),
                        "offset": str(len(rows)),
                    },
                )
                if response.status_code != 200:
                    raise ValueError
                page = response.json()
                if not isinstance(page, list) or len(page) > PAGE_SIZE:
                    raise ValueError
                rows.extend(page)
                if len(rows) > MAX_EVENTS:
                    raise AlpacaPaperError("El control de la prueba requiere exportación administrativa.")
                if len(page) < PAGE_SIZE:
                    return [event_row(row) for row in rows]
        except (TypeError, ValueError):
            raise AlpacaPaperError("No se pudo leer el control de la prueba en Supabase.") from None

    def append(self, issuer, subject, account_id, kind, payload, *, key=None):
        account, key = event_input(account_id, kind, payload, key)
        response = self.request(
            "POST",
            "rpc/append_alpaca_trial_event",
            json={
                "p_owner": identity_key(issuer, subject),
                "p_account": account,
                "p_key": key,
                "p_kind": kind,
                "p_payload": payload,
            },
        )
        try:
            rows = response.json()
            if response.status_code != 200 or not isinstance(rows, list) or len(rows) != 1:
                raise ValueError
            saved = event_row(rows[0])
            if saved.kind != kind or (
                saved.payload != payload and kind not in {"alert", "observation", "ack"}
            ):
                raise ValueError
            return saved
        except (TypeError, ValueError):
            raise AlpacaPaperError(
                "Supabase no confirmó el registro de la prueba; revisa su estado."
            ) from None


def trial_store_for(watchlist):
    if isinstance(watchlist, SupabaseWatchlistStore):
        return SupabaseTrialStore(watchlist)
    return SQLiteTrialStore(watchlist.path.with_suffix(".alpaca-orders.db"))


def latest(events, kind):
    return next((e for e in reversed(events) if e.kind == kind), None)


def exit_plans(events):
    result = {}
    for event in events:
        if event.kind == "plan":
            result[event.payload["symbol"]] = event
    return result


def fills_digest(fills):
    rows = [f.to_json() for f in sorted(fills, key=lambda item: item.id)]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def stored_fills(events):
    fills = [PaperFill.from_json(e.payload) for e in events if e.kind == "fill"]
    sync = latest(events, "fills_sync")
    if fills and (sync is None or sync.payload.get("complete") is not True
                  or sync.payload.get("count") != len(fills)
                  or sync.payload.get("digest") != fills_digest(fills)):
        raise AlpacaPaperError("La descarga de ejecuciones no quedó completa. Pulsa Actualizar resultados.")
    return fills
