import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest
from alpaca_order_fakes import ACCOUNT_ID, FakePaper

from alpaca_order_models import LimitDraft, new_draft, validate_receipt
from alpaca_order_store import OrderEvent, SQLiteOrderStore
from alpaca_orders import order_states, prepare_order, submit_order
from alpaca_paper import AlpacaPaperError, PaperAccountSnapshot, PaperPosition
from alpaca_results import paper_results
from alpaca_signal_context import alignment, context_json, reference_levels
from technical_analysis import BUY, WAIT, Condition, MarketHistory, TechnicalSnapshot
from technical_paper import signal_event
from technical_paper_store import SQLitePaperStore


def saved_signal(tmp_path, now, *, signal=BUY, symbol="SIM", currency="USD", atr=2):
    store = SQLitePaperStore(tmp_path / "signals.paper.db")
    observed = now - timedelta(minutes=2)
    snapshot = TechnicalSnapshot(symbol, signal, "Observación sintética.",
        as_of=(now - timedelta(days=1)).date(), close=100, relative_volume=2, rsi=60,
        indicators=pd.DataFrame({"MACDHistogram": [1], "ATR14": [atr]}),
        buy_conditions=tuple(Condition(f"Condición {i}", True, "Lectura sintética") for i in range(5)),
        sell_conditions=tuple(Condition(f"Salida {i}", False, "Lectura sintética") for i in range(4)))
    history = MarketHistory(symbol, pd.DataFrame(), currency, "NasdaqGS", "America/New_York", observed)
    event = store.append("issuer", "alice", signal_event(snapshot, history))
    return store, event


def test_link_saved_before_prepare_and_revalidate_before_post(tmp_path):
    now = datetime.now(UTC) + timedelta(seconds=1)
    server = FakePaper(now)
    orders = SQLiteOrderStore(tmp_path / "orders.db")
    signals, event = saved_signal(tmp_path, now)
    draft = prepare_order(server.client, orders, "issuer", "alice", "SIM", "buy", 1, "100",
                          now=now, signal_store=signals, signal_key=event.event_key)
    assert not server.posts
    assert alignment(draft) == "Coincide con la señal guardada"
    assert reference_levels(draft, Decimal("99")) == (Decimal("95"), Decimal("107"))
    assert LimitDraft.from_json(ACCOUNT_ID, draft.to_json()) == draft
    result = submit_order(server.client, orders, "issuer", "alice", draft, confirmed=True,
                          now=now, signal_store=signals)
    assert result.draft.research_json == draft.research_json and len(server.posts) == 1
    sent = json.loads(server.posts[0].content)
    assert "signal_context" not in sent and "atr" not in sent
    persisted = orders.load("issuer", "alice", ACCOUNT_ID)[0].payload
    assert persisted["signal_context"]["observation"]["atr"] == "2"
    assert not orders.load("issuer", "bob", ACCOUNT_ID)


def test_missing_other_user_or_modified_signal_blocks_before_post(tmp_path):
    now = datetime.now(UTC) + timedelta(seconds=1)
    server = FakePaper(now)
    orders = SQLiteOrderStore(tmp_path / "orders.db")
    signals, event = saved_signal(tmp_path, now)
    with pytest.raises(AlpacaPaperError, match="tu usuario"):
        prepare_order(server.client, orders, "issuer", "bob", "SIM", "buy", 1, "100",
                      now=now, signal_store=signals, signal_key=event.event_key)
    draft = prepare_order(server.client, orders, "issuer", "alice", "SIM", "buy", 1, "100",
                          now=now, signal_store=signals, signal_key=event.event_key)
    with pytest.raises(AlpacaPaperError, match="verificarse"):
        submit_order(server.client, orders, "issuer", "alice", draft, confirmed=True, now=now)
    context = json.loads(draft.research_json)
    context["observation"]["reason"] = "Alterada después de revisar"
    forged = replace(draft, research_json=context_json(context, "SIM", now))
    with pytest.raises(AlpacaPaperError, match="cambió"):
        submit_order(server.client, orders, "issuer", "alice", forged, confirmed=True,
                     now=now, signal_store=signals)
    assert not server.posts and not orders.load("issuer", "alice", ACCOUNT_ID)


@pytest.mark.parametrize("change", ["future", "ticker", "currency", "fetch", "nan", "atr"])
def test_context_rejects_future_mismatched_and_nonfinite_observations(tmp_path, change):
    now = datetime.now(UTC) + timedelta(seconds=1)
    _, event = saved_signal(tmp_path, now)
    context = {"key": event.event_key, "ticker": "SIM", "session": str(event.signal_date),
               "recorded_at": event.recorded_at.isoformat(), "observation": dict(event.payload)}
    if change == "future":
        context["recorded_at"] = (now + timedelta(seconds=1)).isoformat()
    elif change == "ticker":
        context["ticker"] = "OTHER"
    elif change == "currency":
        context["observation"]["origin_currency"] = "MXN"
    elif change == "fetch":
        context["observation"]["source_fetched_at"] = (now + timedelta(minutes=1)).isoformat()
    else:
        context["observation"]["rsi" if change == "nan" else "atr"] = "NaN"
    with pytest.raises(AlpacaPaperError):
        context_json(context, "SIM", now)


def test_wait_old_and_legacy_observations_are_not_strategy_confirmations(tmp_path):
    now = datetime.now(UTC) + timedelta(seconds=1)
    signals, event = saved_signal(tmp_path, now, signal=WAIT, atr=None)
    server, orders = FakePaper(now), SQLiteOrderStore(tmp_path / "orders.db")
    draft = prepare_order(server.client, orders, "issuer", "alice", "SIM", "buy", 1, "100",
                          now=now, signal_store=signals, signal_key=event.event_key)
    assert "Prueba manual" in alignment(draft)
    assert reference_levels(draft, 100) is None
    assert "Prueba técnica" in alignment(replace(draft, research_json=None))
    row = json.loads(draft.research_json)
    row["observation"]["signal"] = BUY
    draft = replace(draft, research_json=context_json(row, "SIM", now), prepared_at=now + timedelta(days=7))
    assert "Prueba manual" in alignment(draft)


def filled_state(now, side, qty, price, sequence, *, filled_at=True, status="filled"):
    draft = new_draft(ACCOUNT_ID, "SIM", side, qty, price,
                      {"is_open": True, "timestamp": now.isoformat(), "next_open": now.isoformat()}, now)
    intent = OrderEvent(sequence, ACCOUNT_ID, draft.client_order_id, draft.client_order_id,
                        "intent", draft.to_json(), now)
    receipt = {**draft.payload(), "id": str(uuid4()), "filled_qty": str(qty),
               "filled_avg_price": str(price), "status": status}
    if filled_at:
        receipt["filled_at"] = now.isoformat()
    received = OrderEvent(sequence + 1, ACCOUNT_ID, draft.client_order_id, str(uuid4()),
                          "observed", validate_receipt(draft, receipt), now)
    return order_states([intent, received])[0]


def snapshot_for(states, quantity, price=214.24):
    account = FakePaper().client.fetch_snapshot().account
    position = PaperPosition("SIM", "us_equity", "long", Decimal(str(quantity)), Decimal("217.495"),
                             Decimal(str(price)), None, None)
    return PaperAccountSnapshot(account, (position,) if quantity else (), (), datetime.now(UTC))


def test_two_independent_buys_keep_exact_cost_and_rounded_average_separate():
    now = datetime.now(UTC)
    states = [filled_state(now, "buy", 1, "217", 1, filled_at=False),
              filled_state(now + timedelta(seconds=1), "buy", 1, "217.99", 3, filled_at=False)]
    rows, limitations = paper_results(states, snapshot_for(states, 2))
    assert not limitations and len(rows) == 2
    assert sum(r["Entrada media · USD"] for r in rows) == Decimal("434.99")
    assert sum(r["Resultado abierto · USD"] for r in rows) == Decimal("-6.51")
    assert all(r["Resultado cerrado · USD"] is None for r in rows)


def test_fifo_partial_disposal_realized_and_open_results():
    now = datetime.now(UTC)
    states = [filled_state(now, "buy", 2, "100", 1),
              filled_state(now + timedelta(seconds=1), "buy", 1, "110", 3),
              filled_state(now + timedelta(seconds=2), "sell", 1, "120", 5)]
    rows, limitations = paper_results(states, snapshot_for(states, 2, price=115))
    assert not limitations
    assert rows[0]["Resultado cerrado · USD"] == Decimal("20")
    assert rows[0]["Rendimiento cerrado · %"] == Decimal("20")
    assert rows[0]["Abiertas"] == Decimal(1)
    assert sum(r["Resultado abierto · USD"] for r in rows) == Decimal("20")


@pytest.mark.parametrize("change", ["missing_time", "partial", "unmatched_sale", "position"])
def test_ambiguous_or_partial_results_have_visible_limitations(change):
    now = datetime.now(UTC)
    buy = filled_state(now, "buy", 1, "100", 1, filled_at=change != "missing_time",
                        status="partially_filled" if change == "partial" else "filled")
    sell = filled_state(now + timedelta(seconds=1), "sell", 1, "110", 3)
    states = [buy, sell] if change == "missing_time" else [sell] if change == "unmatched_sale" else [buy]
    rows, limitations = paper_results(states, snapshot_for(states, 3 if change == "position" else 0))
    assert limitations
    if change == "position":
        assert rows[0]["Resultado abierto · USD"] is None
    else:
        assert not rows


def test_ui_saves_reviewed_signal_and_shows_fill_result_without_an_extra_order(monkeypatch, tmp_path):
    from test_alpaca_orders_ui import confirm, open_orders, proposal

    app, server, _ = open_orders(monkeypatch, tmp_path)
    _, event = saved_signal(tmp_path, datetime.now(UTC) + timedelta(seconds=1))
    signals = SQLitePaperStore((tmp_path / "watchlist.db").with_suffix(".paper.db"))
    signals.append("issuer", "alice", replace(event, recorded_at=None))
    proposal(app)
    app.selectbox(key="technical_alpaca_order_signal").select(event.event_key).run()
    assert not any(item.key == "technical_alpaca_order_submit" for item in app.button)
    app.button(key="technical_alpaca_order_prepare").click().run()
    assert not app.exception and not app.error
    assert any("Coincide con la señal" in item.value for item in app.markdown)
    confirm(app)
    row = next(iter(server.orders.values()))
    row.update(status="filled", filled_qty="1", filled_avg_price="99",
               filled_at=datetime.now(UTC).isoformat())
    server.positions = [{"symbol": "SIM", "asset_class": "us_equity", "side": "long",
                         "qty": "1", "qty_available": "1", "avg_entry_price": "99",
                         "current_price": "105", "market_value": "105", "unrealized_pl": "6"}]
    app.button(key="technical_alpaca_order_reconcile").click().run()
    app.button(key="technical_alpaca_refresh").click().run()
    assert not app.exception and not app.error and len(server.posts) == 1
    frame = next(item.value for item in app.dataframe if "ID de entrada" in item.value.columns)
    assert frame.loc[0, "Resultado abierto · USD"] == 6
    assert frame.loc[0, "Stop de referencia · USD"] == 95
    assert frame.loc[0, "Objetivo de referencia · USD"] == 107
    assert frame.loc[0, "Clasificación"] == "Coincide con la señal guardada"


def test_external_recent_execution_suppresses_open_result():
    from alpaca_paper import PaperOrder

    now = datetime.now(UTC)
    states = [filled_state(now, "buy", 1, "100", 1)]
    snapshot = snapshot_for(states, 1)
    outside = PaperOrder(str(uuid4()), "SIM", "buy", "limit", "filled", Decimal(1), None,
                         Decimal(1), Decimal(100), Decimal(100), now)
    rows, limitations = paper_results(states, replace(snapshot, orders=(outside,)))
    assert limitations and rows[0]["Resultado abierto · USD"] is None


def test_complete_fifo_close_reports_zero_open_and_price_return():
    now = datetime.now(UTC)
    states = [filled_state(now, "buy", 1, "100", 1),
              filled_state(now + timedelta(seconds=1), "sell", 1, "110", 3)]
    rows, limitations = paper_results(states, snapshot_for(states, 0))
    assert not limitations and rows[0]["Abiertas"] == 0
    assert rows[0]["Resultado abierto · USD"] == 0
    assert rows[0]["Resultado cerrado · USD"] == Decimal("10")
    assert rows[0]["Rendimiento cerrado · %"] == Decimal("10")


@pytest.mark.parametrize("atr", ["ausente", float("nan"), -1])
def test_invalid_optional_atr_is_not_reconstructed(tmp_path, atr):
    _, event = saved_signal(tmp_path, datetime.now(UTC) + timedelta(seconds=30), atr=atr)
    assert event.payload["atr"] is None


def test_a_later_receipt_without_fill_time_keeps_the_confirmed_timestamp():
    state = filled_state(datetime.now(UTC), "buy", 1, "100", 1)
    payload = dict(state.receipt)
    payload.pop("filled_at")
    later = replace(state.latest, sequence=3, event_key=str(uuid4()), payload=payload)
    folded = order_states([state.intent, state.latest, later])[0]
    assert folded.receipt["filled_at"] == state.receipt["filled_at"]
