"""Transport contracts for private trial RPCs; never connects to a real service."""

import json

import httpx
import pytest
from alpaca_order_fakes import ACCOUNT_ID, NOW
from test_alpaca_trial_controls import controls, proposal

import alpaca_trial_store
from alpaca_order_store import OrderAlreadyRecorded, SupabaseOrderStore
from alpaca_paper import AlpacaPaperError
from alpaca_trial_store import SupabaseTrialStore, stable_key
from supabase_watchlist import SupabaseWatchlistStore
from watchlist_store import identity_key


def base_store(handler):
    return SupabaseWatchlistStore(
        "https://projectref.supabase.co", "sb_secret_synthetic_only",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_trial_rpc_deduplication_pagination_and_identity(monkeypatch):
    monkeypatch.setattr(alpaca_trial_store, "PAGE_SIZE", 2)
    rows, reads = [], []

    def handler(request):
        assert request.headers["apikey"] == "sb_secret_synthetic_only"
        if request.method == "POST":
            assert request.url.path == "/rest/v1/rpc/append_alpaca_trial_event"
            body = json.loads(request.content)
            match = next((r for r in rows if r["owner"] == body["p_owner"]
                          and r["account_id"] == body["p_account"]
                          and r["event_key"] == body["p_key"]), None)
            if match is None:
                match = dict(owner=body["p_owner"], account_id=body["p_account"],
                             event_key=body["p_key"], kind=body["p_kind"],
                             payload=body["p_payload"], event_seq=len(rows)+1,
                             recorded_at=NOW.isoformat())
                rows.append(match)
            return httpx.Response(200, json=[match])
        assert request.method == "GET" and request.url.path == "/rest/v1/alpaca_trial_events"
        params = request.url.params
        reads.append(params)
        selected = [r for r in rows if "eq."+r["owner"] == params["owner"]
                    and "eq."+r["account_id"] == params["account_id"]]
        offset, limit = int(params["offset"]), int(params["limit"])
        return httpx.Response(200, json=selected[offset:offset+limit])

    store = SupabaseTrialStore(base_store(handler))
    key = stable_key("alert", "same-stop")
    first = store.append("issuer", "alice", ACCOUNT_ID, "alert", {"message": "first"}, key=key)
    duplicate = store.append("issuer", "alice", ACCOUNT_ID, "alert", {"message": "later"}, key=key)
    assert first == duplicate
    for index in range(3):
        store.append("issuer", "alice", ACCOUNT_ID, "ack", {"index": index})
    assert len(store.load("issuer", "alice", ACCOUNT_ID)) == 4
    assert [int(p["offset"]) for p in reads] == [0, 2, 4]
    assert not store.load("issuer", "bob", ACCOUNT_ID)
    assert reads[-1]["owner"] == "eq."+identity_key("issuer", "bob")


def test_trial_rpc_failures_are_visible_and_do_not_expose_response():
    store = SupabaseTrialStore(base_store(lambda _: httpx.Response(500, text="sensitive response")))
    with pytest.raises(AlpacaPaperError, match="no confirmó") as error:
        store.append("issuer", "alice", ACCOUNT_ID, "ack", {"key": "example"})
    assert "sensitive" not in str(error.value)
    with pytest.raises(AlpacaPaperError, match="No se pudo leer"):
        store.load("issuer", "alice", ACCOUNT_ID)


def test_controlled_intent_uses_atomic_rpc_and_duplicate_never_falls_back(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path)
    draft = proposal(now, server, orders, trial)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/rest/v1/rpc/claim_alpaca_trial_order"
        body = json.loads(request.content)
        assert body["p_owner"] == identity_key("issuer", "alice")
        assert body["p_payload"]["trial_context"]["settings"]["capital"] == "1000"
        return httpx.Response(409, json={"message": "ORDER_ALREADY_RECORDED"})

    store = SupabaseOrderStore(base_store(handler))
    with pytest.raises(OrderAlreadyRecorded):
        store.append("issuer", "alice", ACCOUNT_ID, draft.client_order_id, "intent", draft.to_json())
    assert len(requests) == 1
