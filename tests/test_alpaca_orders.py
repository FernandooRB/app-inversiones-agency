from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from alpaca_order_fakes import ACCOUNT_ID, NOW, ORDER_ID, FakePaper

from alpaca_order_models import limit_inputs
from alpaca_order_store import SQLiteOrderStore
from alpaca_orders import order_states, prepare_order, reconcile_order, submit_order
from alpaca_paper import AlpacaPaperError


def prepared(tmp_path, *, quantity=1):
    server = FakePaper()
    store = SQLiteOrderStore(tmp_path / "orders.db")
    draft = prepare_order(server.client, store, "issuer", "alice", "SIM", "buy", quantity, "100", now=NOW)
    return server, store, draft


def send(server, store, draft, **kwargs):
    return submit_order(server.client, store, "issuer", "alice", draft, confirmed=True, now=NOW, **kwargs)


def test_prepare_never_posts_and_confirmation_claims_before_exactly_one_post(tmp_path):
    server, store, draft = prepared(tmp_path)
    assert not server.posts and store.load("issuer", "alice", ACCOUNT_ID) == []
    original = server.handle

    def checked(request):
        if request.method == "POST":
            assert store.load("issuer", "alice", ACCOUNT_ID)[0].kind == "intent"
        return original(request)

    server.client._client._transport.handler = checked
    state = send(server, store, draft)
    assert state.status == "new" and not state.unresolved
    assert [event.kind for event in store.load("issuer", "alice", ACCOUNT_ID)] == ["intent", "accepted"]
    assert len(server.posts) == 1
    assert send(server, store, draft).receipt["id"] == ORDER_ID
    assert len(server.posts) == 1


def test_two_sessions_cannot_send_the_same_intent_twice(tmp_path):
    server, store, draft = prepared(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: send(server, store, draft), range(2)))
    assert len(server.posts) == 1 and len(results) == 2
    assert len([e for e in store.load("issuer", "alice", ACCOUNT_ID) if e.kind == "intent"]) == 1


def test_expired_unconfirmed_or_changed_account_never_posts(tmp_path):
    server, store, draft = prepared(tmp_path)
    with pytest.raises(AlpacaPaperError, match="Confirma"):
        submit_order(server.client, store, "issuer", "alice", draft, confirmed=False, now=NOW)
    with pytest.raises(AlpacaPaperError, match="venció"):
        send(server, store, replace(draft, prepared_at=NOW - timedelta(minutes=6)))
    server.account["id"] = "10000000-0000-0000-0000-000000000002"
    with pytest.raises(AlpacaPaperError, match="cuenta cambió"):
        send(server, store, draft)
    assert not server.posts and not store.load("issuer", "alice", ACCOUNT_ID)


@pytest.mark.parametrize("change", ["cash", "reserved_cash", "asset", "restricted", "clock"])
def test_rechecks_availability_instrument_restrictions_and_clock_at_confirmation(tmp_path, change):
    server, store, draft = prepared(tmp_path)
    if change == "cash":
        server.account["cash"] = "1"
    elif change == "reserved_cash":
        server.account["non_marginable_buying_power"] = "1"
    elif change == "asset":
        server.asset["class"] = "crypto"
    elif change == "restricted":
        server.account["trade_suspended_by_user"] = True
    else:
        server.clock["is_open"] = True
    with pytest.raises(AlpacaPaperError):
        send(server, store, draft)
    assert not server.posts and not store.load("issuer", "alice", ACCOUNT_ID)


def test_sell_requires_available_long_shares_and_accounts_for_reservations(tmp_path):
    server = FakePaper()
    store = SQLiteOrderStore(tmp_path / "orders.db")
    with pytest.raises(AlpacaPaperError, match="títulos"):
        prepare_order(server.client, store, "issuer", "alice", "SIM", "sell", 1, "100", now=NOW)
    server.positions = [{"symbol": "SIM", "asset_class": "us_equity", "side": "long", "qty": "3",
                         "qty_available": "1", "avg_entry_price": "99", "current_price": "100",
                         "market_value": "300", "unrealized_pl": "3"}]
    with pytest.raises(AlpacaPaperError, match="títulos"):
        prepare_order(server.client, store, "issuer", "alice", "SIM", "sell", 2, "100", now=NOW)
    draft = prepare_order(server.client, store, "issuer", "alice", "SIM", "sell", 1, "100", now=NOW)
    assert send(server, store, draft).status == "new"


def test_timeout_after_accept_reconciles_without_another_post(tmp_path):
    server, store, draft = prepared(tmp_path)
    server.mode = "timeout_after_accept"
    state = send(server, store, draft)
    assert state.status == "new" and len(server.posts) == 1
    assert any(r.url.path.endswith(":by_client_order_id") for r in server.requests)


def test_duplicate_id_reply_is_looked_up_instead_of_resubmitted(tmp_path):
    server, store, draft = prepared(tmp_path)
    server.mode = "duplicate"
    assert send(server, store, draft).status == "new"
    assert len(server.posts) == 1


def test_lost_journal_response_after_post_is_recovered_without_resending(tmp_path):
    server, store, draft = prepared(tmp_path)

    class FailAfterClaim(SQLiteOrderStore):
        def append(self, issuer, subject, account_id, client_id, kind, payload):
            if kind == "accepted":
                raise AlpacaPaperError("Synthetic journal outage after broker response")
            return super().append(issuer, subject, account_id, client_id, kind, payload)

    failing = FailAfterClaim(store.path)
    with pytest.raises(AlpacaPaperError, match="Consulta el intento"):
        send(server, failing, draft)
    assert len(server.posts) == 1
    assert send(server, store, draft).unresolved
    assert len(server.posts) == 1
    recovered = reconcile_order(server.client, store, "issuer", "alice", ACCOUNT_ID, draft.client_order_id)
    assert recovered.status == "new" and len(server.posts) == 1


@pytest.mark.parametrize("mode", ["timeout_no_accept", "wrong_receipt", "redirect"])
def test_uncertain_submission_blocks_new_orders_until_reconciled(tmp_path, mode):
    server, store, draft = prepared(tmp_path)
    server.mode = mode
    state = send(server, store, draft)
    assert state.unresolved and len(server.posts) == 1
    assert send(server, store, draft).unresolved and len(server.posts) == 1
    with pytest.raises(AlpacaPaperError, match="sin confirmar"):
        prepare_order(server.client, store, "issuer", "alice", "SIM", "buy", 1, "100", now=NOW)


def test_explicit_provider_rejection_is_recorded_without_secrets(tmp_path):
    server, store, draft = prepared(tmp_path)
    server.mode = "rejected"
    state = send(server, store, draft)
    assert state.status == "solicitud_rechazada" and not state.unresolved
    assert "SYNTHETIC_PAPER_SECRET" not in repr(store.load("issuer", "alice", ACCOUNT_ID))
    assert state.latest.payload["http_status"] == 422
    assert reconcile_order(server.client, store, "issuer", "alice", ACCOUNT_ID,
                           draft.client_order_id).status == "solicitud_rechazada"


def test_partial_fill_complete_fill_and_later_stale_observation_do_not_regress(tmp_path):
    server, store, draft = prepared(tmp_path, quantity=2)
    send(server, store, draft)
    row = server.orders[draft.client_order_id]
    row.update(status="partially_filled", filled_qty="1", filled_avg_price="99")
    partial = reconcile_order(server.client, store, "issuer", "alice", ACCOUNT_ID, draft.client_order_id)
    assert partial.status == "partially_filled" and partial.receipt["filled_qty"] == "1"
    row.update(status="filled", filled_qty="2")
    complete = reconcile_order(server.client, store, "issuer", "alice", ACCOUNT_ID, draft.client_order_id)
    assert complete.status == "filled"
    row.update(status="new", filled_qty="0", filled_avg_price=None)
    stale = reconcile_order(server.client, store, "issuer", "alice", ACCOUNT_ID, draft.client_order_id)
    assert stale.status == "filled" and stale.receipt["filled_qty"] == "2"
    reopened = order_states(SQLiteOrderStore(store.path).load("issuer", "alice", ACCOUNT_ID))
    assert reopened[0].status == "filled"
    assert not store.load("issuer", "bob", ACCOUNT_ID)


def test_storage_failure_prevents_post_and_lookup_cannot_cross_owner(tmp_path):
    server, store, draft = prepared(tmp_path)

    class FailingStore:
        def load(self, *args):
            return []

        def append(self, *args):
            raise AlpacaPaperError("Storage unavailable")

    with pytest.raises(AlpacaPaperError):
        send(server, FailingStore(), draft)
    assert not server.posts
    send(server, store, draft)
    before = len(server.requests)
    with pytest.raises(AlpacaPaperError, match="usuario"):
        reconcile_order(server.client, store, "issuer", "bob", ACCOUNT_ID, draft.client_order_id)
    assert len(server.requests) == before


@pytest.mark.parametrize("symbol,side,quantity,price", [
    ("BTC/USD", "buy", 1, "100"), ("SIM", "short", 1, "100"), ("SIM", "buy", 0.5, "100"),
    ("SIM", "buy", 1, "NaN"), ("SIM", "buy", 1, "100.001"), ("SIM", "buy", 1, "0.00001"),
])
def test_unsupported_order_inputs_are_rejected(symbol, side, quantity, price):
    with pytest.raises(AlpacaPaperError):
        limit_inputs(symbol, side, quantity, price)
