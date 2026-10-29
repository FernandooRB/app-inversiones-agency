from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from test_alpaca_signal_results import filled_state, snapshot_for

from alpaca_order_store import SQLiteOrderStore
from alpaca_orders import order_states
from alpaca_paper import PaperFill, PaperOrder
from alpaca_results import paper_results
from alpaca_trial_store import SQLiteTrialStore, fills_digest, stable_key


def accepted_state(now, *, symbol="SIM"):
    state = filled_state(now, "buy", 1, "100", 3)
    draft = replace(state.draft, symbol=symbol)
    receipt = {**draft.payload(), "id": state.receipt["id"], "status": "accepted",
               "filled_qty": "0", "filled_avg_price": None}
    return order_states([replace(state.intent, payload=draft.to_json()),
                         replace(state.latest, payload=receipt)])[0]


@pytest.mark.parametrize("quantity", [0, 1])
def test_unfilled_journal_with_a_broker_position_requires_reconciliation(quantity):
    state = accepted_state(datetime.now(UTC))
    rows, limitations = paper_results([state], snapshot_for([state], quantity))
    assert not rows
    assert bool(limitations) is bool(quantity)
    if quantity:
        assert "Actualizar resultados" in limitations[0]


def test_recent_broker_execution_is_not_silently_omitted_when_account_is_flat():
    now = datetime.now(UTC)
    state = accepted_state(now)
    snapshot = snapshot_for([state], 0)
    executed = PaperOrder(str(uuid4()), "SIM", "buy", "limit", "filled", Decimal(1), None,
                          Decimal(1), Decimal(100), Decimal(100), now)
    rows, limitations = paper_results([state], replace(snapshot, orders=(executed,)))
    assert not rows and limitations


def test_missing_symbol_stops_full_totals_but_preserves_other_complete_lots():
    now = datetime.now(UTC)
    completed, pending = filled_state(now, "buy", 1, "100", 1), accepted_state(now, symbol="OTHER")
    snapshot = snapshot_for([completed, pending], 1, price=110)
    second_position = replace(snapshot.positions[0], symbol="OTHER")
    rows, limitations = paper_results([completed, pending], replace(
        snapshot, positions=(*snapshot.positions, second_position)))
    assert len(rows) == 1 and rows[0]["Símbolo"] == "SIM"
    assert rows[0]["Resultado abierto · USD"] == Decimal(10)
    assert len(limitations) == 1 and "OTHER" in limitations[0]


def test_ui_hides_total_when_a_second_position_has_no_confirmed_journal_fill(monkeypatch, tmp_path):
    from test_alpaca_orders_ui import open_orders

    app, server, _ = open_orders(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    complete, pending = filled_state(now, "buy", 1, "100", 1), accepted_state(now, symbol="OTHER")
    store = SQLiteOrderStore((tmp_path / "watchlist.db").with_suffix(".alpaca-orders.db"))
    for state in (complete, pending):
        store.append("issuer", "alice", state.draft.account_id, state.draft.client_order_id,
                     "intent", state.draft.to_json())
        store.append("issuer", "alice", state.draft.account_id, state.draft.client_order_id,
                     "observed", state.receipt)
    trial = SQLiteTrialStore(store.path)
    fill = PaperFill("synthetic:complete", complete.receipt["id"], "SIM", "buy", Decimal(1),
                     Decimal(100), now)
    trial.append("issuer", "alice", complete.draft.account_id, "fill", fill.to_json(),
                 key=stable_key("fill", fill.id))
    trial.append("issuer", "alice", complete.draft.account_id, "fills_sync",
                 {"digest": fills_digest([fill]), "complete": True, "count": 1})
    server.positions = [
        {"symbol": symbol, "asset_class": "us_equity", "side": "long", "qty": "1",
         "avg_entry_price": "100", "current_price": "110", "market_value": "110",
         "unrealized_pl": "10"} for symbol in ("SIM", "OTHER")]
    app.button(key="technical_alpaca_refresh").click().run()
    assert not app.exception and not app.error and not server.posts
    assert any("OTHER" in item.value and "Actualizar resultados" in item.value for item in app.warning)
    totals = {item.label: item.value for item in app.metric}
    assert totals["Resultado abierto del registro · USD"] == "—"
    frame = next(item.value for item in app.dataframe if "ID de entrada" in item.value.columns)
    assert frame.loc[0, "Símbolo"] == "SIM" and frame.loc[0, "Resultado abierto · USD"] == 10
