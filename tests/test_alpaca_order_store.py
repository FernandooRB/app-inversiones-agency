import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from alpaca_order_fakes import ACCOUNT_ID, NOW

import alpaca_order_store
from alpaca_order_models import new_draft
from alpaca_order_store import OrderAlreadyRecorded, SQLiteOrderStore, SupabaseOrderStore, order_store_for
from alpaca_paper import AlpacaPaperError
from supabase_watchlist import SupabaseWatchlistStore
from watchlist_store import identity_key


def draft():
    return new_draft(ACCOUNT_ID, "SIM", "buy", 1, "100",
                     {"timestamp": NOW.isoformat(), "is_open": False,
                      "next_open": (NOW + timedelta(days=1)).isoformat()}, now=NOW)


def append_intent(store, subject, proposal):
    return store.append("issuer", subject, ACCOUNT_ID, proposal.client_order_id, "intent", proposal.to_json())


def test_atomic_claim_is_persistent_and_observations_require_same_owner_and_account(tmp_path):
    store = SQLiteOrderStore(tmp_path / "orders.db")
    proposal = draft()
    append_intent(store, "alice", proposal)
    with pytest.raises(OrderAlreadyRecorded):
        append_intent(store, "alice", proposal)
    with pytest.raises(AlpacaPaperError):
        store.append("issuer", "bob", ACCOUNT_ID, proposal.client_order_id, "unknown", {})
    store.append("issuer", "alice", ACCOUNT_ID, proposal.client_order_id, "unknown", {"reason": "timeout"})
    reopened = SQLiteOrderStore(store.path)
    assert [event.kind for event in reopened.load("issuer", "alice", ACCOUNT_ID)] == ["intent", "unknown"]
    assert reopened.load("issuer", "bob", ACCOUNT_ID) == []
    assert reopened.load("issuer", "alice", "10000000-0000-0000-0000-000000000002") == []


def test_concurrent_claim_has_one_winner(tmp_path):
    store = SQLiteOrderStore(tmp_path / "orders.db")
    proposal = draft()

    def claim(_):
        try:
            append_intent(store, "alice", proposal)
            return "claimed"
        except OrderAlreadyRecorded:
            return "already_recorded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(claim, range(2))) == ["already_recorded", "claimed"]


def test_supabase_filters_and_pages_by_owner_account_and_only_inserts(monkeypatch):
    monkeypatch.setattr(alpaca_order_store, "PAGE_SIZE", 2)
    rows, requests = [], []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/rest/v1/alpaca_paper_order_events"
        assert request.headers["apikey"] == "sb_secret_synthetic_only"
        if request.method == "POST":
            body = json.loads(request.content)
            if any(row["owner"] == body["owner"] and row["account_id"] == body["account_id"]
                   and row["event_key"] == body["event_key"] for row in rows):
                return httpx.Response(409)
            body.update(event_seq=len(rows) + 1, recorded_at=NOW.isoformat())
            rows.append(body)
            return httpx.Response(201, json=[body])
        assert request.method == "GET"
        owner = request.url.params["owner"].removeprefix("eq.")
        account = request.url.params["account_id"].removeprefix("eq.")
        selected = [row for row in rows if row["owner"] == owner and row["account_id"] == account]
        offset, limit = int(request.url.params["offset"]), int(request.url.params["limit"])
        return httpx.Response(200, json=selected[offset:offset + limit])

    base = SupabaseWatchlistStore("https://projectref.supabase.co", "sb_secret_synthetic_only",
                                  client=httpx.Client(transport=httpx.MockTransport(handler)))
    store = order_store_for(base)
    assert isinstance(store, SupabaseOrderStore)
    proposal = draft()
    append_intent(store, "alice", proposal)
    with pytest.raises(OrderAlreadyRecorded):
        append_intent(store, "alice", proposal)
    for _ in range(4):
        store.append("issuer", "alice", ACCOUNT_ID, proposal.client_order_id, "unknown", {})
    assert len(store.load("issuer", "alice", ACCOUNT_ID)) == 5
    assert not store.load("issuer", "bob", ACCOUNT_ID)
    alice_reads = [r for r in requests if r.method == "GET"
                   and r.url.params["owner"] == f"eq.{identity_key('issuer', 'alice')}"]
    assert [int(r.url.params["offset"]) for r in alice_reads] == [0, 2, 4]


def test_remote_failure_and_capacity_fail_visibly(monkeypatch, tmp_path):
    base = SupabaseWatchlistStore("https://projectref.supabase.co", "sb_secret_synthetic_only",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(AlpacaPaperError, match="Supabase"):
        order_store_for(base).load("issuer", "alice", ACCOUNT_ID)
    store, proposal = SQLiteOrderStore(tmp_path / "orders.db"), draft()
    append_intent(store, "alice", proposal)
    store.append("issuer", "alice", ACCOUNT_ID, proposal.client_order_id, "unknown", {})
    monkeypatch.setattr(alpaca_order_store, "MAX_EVENTS", 1)
    with pytest.raises(AlpacaPaperError, match="exportación"):
        store.load("issuer", "alice", ACCOUNT_ID)
