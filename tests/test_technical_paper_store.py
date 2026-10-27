import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from supabase_watchlist import SupabaseWatchlistStore
from technical_paper import PaperError, PaperEvent
from technical_paper_store import PAGE_SIZE, SQLitePaperStore, SupabasePaperStore
from watchlist_store import identity_key

NOW = datetime(2026, 10, 27, 16, 0, tzinfo=UTC)
SIGNAL_KEY = "signal:AAPL:2026-10-26:tendencias-confirmadas-v1"


def event(kind="signal"):
    key = SIGNAL_KEY if kind == "signal" else SIGNAL_KEY + f":{kind}"
    return PaperEvent(key, SIGNAL_KEY, kind, "AAPL", date(2026, 10, 26),
                      {"signal": "Compra"} if kind == "signal" else {"ask_mxn": "100"})


def test_sqlite_journal_is_insert_only_and_isolated(tmp_path: Path):
    path = tmp_path / "journal.db"
    store = SQLitePaperStore(path)
    saved = store.append("issuer", "alice", event())
    assert saved.recorded_at is not None
    assert store.load("issuer", "alice")[0].payload == {"signal": "Compra"}
    assert store.load("issuer", "bob") == []
    with pytest.raises(PaperError, match="ya está registrada"):
        store.append("issuer", "alice", event())
    with pytest.raises(PaperError, match="Registra primero la señal"):
        store.append("issuer", "bob", event("entry"))
    store.append("issuer", "alice", event("entry"))
    store.append("issuer", "alice", event("exit"))
    assert [item.kind for item in SQLitePaperStore(path).load("issuer", "alice")] == [
        "signal", "entry", "exit"
    ]


def test_wait_signal_cannot_receive_paper_entry(tmp_path):
    store = SQLitePaperStore(tmp_path / "journal.db")
    store.append("issuer", "alice", replace(event(), payload={"signal": "Esperar"}))
    with pytest.raises(PaperError, match="Sólo una señal Compra"):
        store.append("issuer", "alice", event("entry"))


def test_supabase_journal_filters_owner_and_never_updates():
    rows, requests = {}, []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/rest/v1/technical_paper_events"
        assert request.headers["apikey"] == "sb_secret_synthetic_test_only"
        assert "authorization" not in request.headers
        owner = request.url.params.get("owner", "").removeprefix("eq.")
        if request.method == "GET":
            return httpx.Response(200, json=rows.get(owner, []))
        assert request.method == "POST"
        data = json.loads(request.content)
        owner = data.pop("owner")
        data["recorded_at"] = NOW.isoformat()
        rows.setdefault(owner, []).append(data)
        return httpx.Response(201, json=[data])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    base = SupabaseWatchlistStore("https://projectref.supabase.co",
                                  "sb_secret_synthetic_test_only", client=client)
    store = SupabasePaperStore(base)
    store.append("issuer", "alice", event())
    assert store.load("issuer", "bob") == []
    assert len(rows[identity_key("issuer", "alice")]) == 1
    assert all(request.method in ("GET", "POST") for request in requests)
    assert all(request.url.params.get("owner") == f"eq.{identity_key('issuer', 'alice')}"
               for request in requests if request.method == "GET" and
               request.url.params.get("owner") != f"eq.{identity_key('issuer', 'bob')}")


def test_supabase_reads_all_pages_without_silently_truncating():
    requests = []
    day = date(2026, 10, 26)
    rows = [{"event_key": f"signal:AAPL:{day}:v{i}",
             "signal_key": f"signal:AAPL:{day}:v{i}", "kind": "signal",
             "ticker": "AAPL", "signal_date": day.isoformat(),
             "payload": {"signal": "Esperar"}, "recorded_at": NOW.isoformat()}
            for i in range(PAGE_SIZE + 1)]

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json=rows[offset:offset + PAGE_SIZE])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    base = SupabaseWatchlistStore("https://projectref.supabase.co",
                                  "sb_secret_synthetic_test_only", client=client)
    loaded = SupabasePaperStore(base).load("issuer", "alice")
    assert len(loaded) == PAGE_SIZE + 1
    assert [int(request.url.params["offset"]) for request in requests] == [0, PAGE_SIZE]


def test_supabase_failure_is_visible_and_never_uses_local_storage():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503)))
    base = SupabaseWatchlistStore("https://projectref.supabase.co",
                                  "sb_secret_synthetic_test_only", client=client)
    with pytest.raises(PaperError, match="No se pudo leer la bitácora en Supabase"):
        SupabasePaperStore(base).load("issuer", "alice")


def test_saved_event_timestamp_cannot_be_supplied_or_rewritten(tmp_path):
    store = SQLitePaperStore(tmp_path / "journal.db")
    with pytest.raises(PaperError, match="tipo o fecha"):
        store.append("issuer", "alice", replace(event(), recorded_at=NOW))
