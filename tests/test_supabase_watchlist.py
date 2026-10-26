"""Supabase's API contract without contacting or exposing a real project."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from supabase_watchlist import SupabaseWatchlistStore
from watchlist_store import WatchlistError, WatchlistStore, identity_key

URL = "https://projectref.supabase.co"
SECRET = "sb_secret_synthetic_test_only"


def fake_store(rows, requests, *, legacy_path=None):
    def handler(request):
        requests.append(request)
        assert request.url.host == "projectref.supabase.co"
        assert request.url.path == "/rest/v1/technical_watchlists"
        assert request.headers["apikey"] == SECRET
        assert "authorization" not in request.headers
        query = parse_qs(request.url.query.decode())
        if request.method == "GET":
            assert query["select"] == ["symbols"]
            assert query["limit"] == ["1"]
            owner = query["owner"][0].removeprefix("eq.")
            return httpx.Response(200, json=[{"symbols": rows[owner]}] if owner in rows else [])
        assert request.method == "POST"
        assert query["on_conflict"] == ["owner"]
        assert request.headers["prefer"] == "resolution=merge-duplicates,return=minimal"
        entry = json.loads(request.content)[0]
        rows[entry["owner"]] = entry["symbols"]
        assert entry["updated_at"].endswith("+00:00")
        return httpx.Response(201)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseWatchlistStore(URL, SECRET, legacy_path=legacy_path, client=client)


def test_supabase_persists_isolated_lists_and_empty_list():
    rows, requests = {}, []
    store = fake_store(rows, requests)
    assert store.load("issuer-a", "subject-a") == []
    assert store.save("issuer-a", "subject-a", "aapl, MSFT, AAPL") == ["AAPL", "MSFT"]
    store.save("issuer-b", "subject-a", ["GOOG"])
    assert rows[identity_key("issuer-a", "subject-a")] == ["AAPL", "MSFT"]
    assert store.load("issuer-a", "subject-a") == ["AAPL", "MSFT"]
    assert store.load("issuer-b", "subject-a") == ["GOOG"]
    store.save("issuer-a", "subject-a", [])
    assert store.load("issuer-a", "subject-a") == []
    assert rows[identity_key("issuer-b", "subject-a")] == ["GOOG"]
    assert len(requests) == 7


def test_supabase_imports_existing_sqlite_once_without_resurrecting_cleared_list(tmp_path):
    local = WatchlistStore(tmp_path / "watchlists.db")
    local.save("issuer", "subject", ["AAPL", "MSFT"])
    rows, requests = {}, []
    store = fake_store(rows, requests, legacy_path=local.path)
    assert store.load("issuer", "subject") == ["AAPL", "MSFT"]
    assert rows[identity_key("issuer", "subject")] == ["AAPL", "MSFT"]
    assert [request.method for request in requests] == ["GET", "POST"]
    store.save("issuer", "subject", [])
    assert store.load("issuer", "subject") == []
    assert rows[identity_key("issuer", "subject")] == []
    assert local.load("issuer", "subject") == ["AAPL", "MSFT"]


def test_invalid_configuration_and_tickers_never_send_a_request():
    rows, requests = {}, []
    for url in (
        "http://projectref.supabase.co", "https://evil.example", "https://projectref.supabase.co.evil",
        "https://projectref.supabase.co:8443", "https://projectref.supabase.co/other",
        "https://user:pass@projectref.supabase.co", "https://[bad",
    ):
        with pytest.raises(WatchlistError, match="URL HTTPS"):
            SupabaseWatchlistStore(url, SECRET)
    with pytest.raises(WatchlistError, match="sb_secret_"):
        SupabaseWatchlistStore(URL, "sb_publishable_wrong")
    store = fake_store(rows, requests)
    with pytest.raises(WatchlistError):
        store.save("issuer", "subject", [f"T{i}" for i in range(26)])
    assert requests == []


def test_remote_failure_or_bad_response_does_not_fall_back_to_sqlite(tmp_path):
    local = WatchlistStore(tmp_path / "watchlists.db")
    local.save("issuer", "subject", ["AAPL"])

    for response in (httpx.Response(503), httpx.Response(200, json={"bad": True})):
        client = httpx.Client(transport=httpx.MockTransport(lambda _request, value=response: value))
        store = SupabaseWatchlistStore(URL, SECRET, legacy_path=local.path, client=client)
        with pytest.raises(WatchlistError):
            store.load("issuer", "subject")
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503)))
    store = SupabaseWatchlistStore(URL, SECRET, client=client)
    with pytest.raises(WatchlistError, match="guardar"):
        store.save("issuer", "subject", ["AAPL"])


def test_bad_saved_remote_symbols_are_not_accepted():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=[{"symbols": {"bad": "data"}}])
        )
    )
    store = SupabaseWatchlistStore(URL, SECRET, client=client)
    with pytest.raises(WatchlistError, match="formato"):
        store.load("issuer", "subject")


def test_configured_watchlist_requires_complete_remote_secrets(monkeypatch):
    import technical_ui

    configuration = {"backend": "supabase", "url": URL, "secret_key": SECRET}
    fake_user = SimpleNamespace(to_dict=lambda: {"iss": "issuer", "sub": "subject"})
    fake_streamlit = SimpleNamespace(
        secrets={"access": {}, "technical_watchlist": configuration}, user=fake_user
    )
    monkeypatch.setattr(technical_ui, "st", fake_streamlit)
    monkeypatch.setattr(technical_ui, "authorized", lambda *_: True)
    store, issuer, subject = technical_ui.configured_watchlist()
    assert isinstance(store, SupabaseWatchlistStore)
    assert (issuer, subject) == ("issuer", "subject")
    assert store.legacy_path.is_absolute()
    configuration.pop("secret_key")
    with pytest.raises(WatchlistError, match="sb_secret_"):
        technical_ui.configured_watchlist()
