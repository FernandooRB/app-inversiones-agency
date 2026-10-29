from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pandas as pd
import pytest
from alpaca_order_fakes import ACCOUNT_ID, FakePaper
from test_alpaca_signal_results import filled_state, snapshot_for

from alpaca_alerts import active_alerts, observation_key
from alpaca_fill_results import fill_results
from alpaca_orders import order_states
from alpaca_paper import AlpacaPaperError, PaperFill
from alpaca_performance import cohort_summary, compare_to_hold
from alpaca_risk import plan_payload
from alpaca_trial_store import SQLiteTrialStore, fills_digest, stable_key, stored_fills


def state(now, side, requested, executed, average, sequence):
    original = filled_state(now, side, requested, "200" if side == "buy" else "1", sequence)
    receipt = {
        **original.receipt,
        "filled_qty": str(executed),
        "filled_avg_price": str(average),
        "status": "filled" if requested == executed else "partially_filled",
    }
    return order_states([original.intent, replace(original.latest, payload=receipt)])[0]


def fill(order, qty, price, when):
    return PaperFill(
        str(uuid4()),
        order.receipt["id"],
        "SIM",
        order.draft.side,
        Decimal(str(qty)),
        Decimal(str(price)),
        when,
    )


def test_partial_orders_use_individual_fifo_and_costs_on_each_side():
    now = datetime.now(UTC)
    buy = state(now, "buy", 1, 1, "106", 1)
    sell = state(now, "sell", 1, ".5", "120", 3)
    fills = [
        fill(buy, ".4", "100", now + timedelta(seconds=1)),
        fill(buy, ".6", "110", now + timedelta(seconds=2)),
        fill(sell, ".5", "120", now + timedelta(seconds=3)),
    ]
    rows, issues, flows = fill_results([buy, sell], snapshot_for([buy, sell], ".5", price=115), fills)
    assert not issues and len(rows) == 1
    row = rows[0]
    assert row["Resultado cerrado · USD"] == Decimal("9.0")
    assert row["Neto cerrado estimado · USD"] == Decimal("8.61150")
    assert row["Resultado abierto · USD"] == Decimal("2.5")
    assert row["Neto abierto estimado · USD"] == Decimal("2.10625")
    assert row["Abiertas"] == Decimal(".5") and row["Ejecuciones de entrada"] == 2
    assert sum(f["net_profit"] for f in flows) == Decimal("8.61150")


def test_partial_canceled_entry_can_be_closed_without_losing_its_fills():
    now = datetime.now(UTC)
    buy = state(now, "buy", 1, ".4", "100", 1)
    buy = order_states([buy.intent, replace(buy.latest, payload={**buy.receipt, "status": "canceled"})])[0]
    sell = state(now, "sell", 1, ".4", "110", 3)
    trades = [
        fill(buy, ".4", 100, now + timedelta(seconds=1)),
        fill(sell, ".4", 110, now + timedelta(seconds=2)),
    ]
    rows, issues, _ = fill_results([buy, sell], snapshot_for([buy, sell], 0), trades, cost_rate=0)
    assert not issues and rows[0]["Cerrada"]
    assert rows[0]["Neto cerrado estimado · USD"] == Decimal(4)


def test_missing_fill_and_duplicate_or_corrected_fill_never_create_partial_results(tmp_path):
    now = datetime.now(UTC)
    buy = state(now, "buy", 1, 1, "100", 1)
    execution = fill(buy, 1, 100, now + timedelta(seconds=1))
    rows, issues, _ = fill_results([buy], snapshot_for([buy], 1), [])
    assert not rows and issues
    with pytest.raises(AlpacaPaperError, match="duplicadas"):
        fill_results([buy], snapshot_for([buy], 1), [execution, execution])
    trial = SQLiteTrialStore(tmp_path / "trial.db")
    trial.append(
        "issuer", "alice", ACCOUNT_ID, "fill", execution.to_json(), key=stable_key("fill", execution.id)
    )
    with pytest.raises(AlpacaPaperError, match="distintos"):
        trial.append(
            "issuer",
            "alice",
            ACCOUNT_ID,
            "fill",
            replace(execution, price=Decimal(101)).to_json(),
            key=stable_key("fill", execution.id),
        )
    with pytest.raises(AlpacaPaperError, match="completa"):
        stored_fills(trial.load("issuer", "alice", ACCOUNT_ID))
    trial.append(
        "issuer",
        "alice",
        ACCOUNT_ID,
        "fills_sync",
        {"digest": fills_digest([execution]), "complete": True, "count": 1},
    )
    assert stored_fills(trial.load("issuer", "alice", ACCOUNT_ID)) == [execution]


def test_external_buy_consumed_first_does_not_credit_its_profit_to_an_app_entry():
    now = datetime.now(UTC)
    buy = state(now, "buy", 1, 1, "100", 1)
    external_buy = PaperFill("outside:buy", str(uuid4()), "SIM", "buy", Decimal(1), Decimal(90), now)
    external_sell = PaperFill(
        "outside:sell", str(uuid4()), "SIM", "sell", Decimal(1), Decimal(110), now + timedelta(seconds=2)
    )
    rows, issues, _ = fill_results(
        [buy],
        snapshot_for([buy], 1, price=120),
        [external_buy, fill(buy, 1, 100, now + timedelta(seconds=1)), external_sell],
    )
    assert not issues and rows[0]["Resultado cerrado · USD"] is None
    assert rows[0]["Resultado abierto · USD"] == Decimal(20)


def test_fill_api_uses_activity_id_pagination_and_rejects_a_repeated_page():
    server = FakePaper()
    after = datetime(2026, 10, 1, tzinfo=UTC)
    rows = [
        {
            "id": f"activity:{i}",
            "order_id": str(uuid4()),
            "activity_type": "FILL",
            "symbol": "SIM",
            "side": "buy",
            "qty": ".5",
            "price": "100",
            "transaction_time": "2026-10-28T15:00:00Z",
        }
        for i in range(100)
    ]
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == "paper-api.alpaca.markets"
        assert request.url.path == "/v2/account/activities"
        assert request.url.params["activity_types"] == "FILL"
        return httpx.Response(200, json=[] if "page_token" in request.url.params else rows)

    server.client._client._transport.handler = handler
    assert len(server.client.fetch_fills(after)) == 100
    assert requests[-1].url.params["page_token"] == "activity:99"
    server.client._client._transport.handler = lambda request: httpx.Response(200, json=rows)
    with pytest.raises(AlpacaPaperError, match="repitió"):
        server.client.fetch_fills(after)


def test_stop_target_and_signal_alerts_are_actionable_and_deduplicated(tmp_path):
    now = datetime.now(UTC)
    store = SQLiteTrialStore(tmp_path / "trial.db")
    plan = store.append(
        "issuer",
        "alice",
        ACCOUNT_ID,
        "plan",
        plan_payload("SIM", "100", "90", "120", (now + timedelta(days=20)).date(), "Plan de salida"),
    )
    snapshot = snapshot_for([], 1, price=89)
    old = {
        "symbol": "SIM",
        "session": "2026-10-27",
        "signal": "Compra",
        "reason": "Síntesis",
        "fetched_at": now.isoformat(),
        "strategy_version": "tendencias-confirmadas-v1",
        "currency": "USD",
    }
    event = store.append("issuer", "alice", ACCOUNT_ID, "observation", old, key=observation_key(old))
    current = {**old, "session": "2026-10-28", "signal": "Esperar"}
    first = active_alerts(snapshot, [plan, event], [current], now=now)
    second = active_alerts(snapshot, [plan, event], [current], now=now)
    assert {a["kind"] for a in first} == {"stop", "signal_change"}
    assert [a["key"] for a in first] == [a["key"] for a in second]
    at_target = replace(snapshot, positions=(replace(snapshot.positions[0], current_price=Decimal(121)),))
    assert "target" in {a["kind"] for a in active_alerts(at_target, [plan], [], now=now)}


def test_price_curves_share_initial_allocation_cash_costs_and_completed_daily_dates():
    now = datetime(2026, 10, 26, 15, tzinfo=UTC)
    rows = [
        {
            "Símbolo": "SIM",
            "Clasificación": "Coincide con la señal guardada",
            "ID de entrada": "entry",
            "Presupuesto de origen": "budget",
            "Capital de referencia · USD": Decimal(1000),
            "Cerrada": True,
            "Neto cerrado estimado · USD": Decimal("9.265"),
        }
    ]
    flows = [
        {
            "side": "buy",
            "entry_id": "entry",
            "timestamp": now,
            "quantity": Decimal(1),
            "net_cash": Decimal("-100.35"),
        },
        {
            "side": "sell",
            "entry_id": "entry",
            "timestamp": now + timedelta(days=1),
            "quantity": Decimal(1),
            "net_cash": Decimal("109.615"),
        },
    ]
    bars = pd.DataFrame({"Close": [100, 110, 90]}, index=pd.date_range("2026-10-26", periods=3))
    frame, stats = compare_to_hold(rows, flows, "SIM", bars, "budget", ".0035")
    assert frame.iloc[-1, 0] == pytest.approx(1009.265)
    assert frame.iloc[-1, 1] == pytest.approx(989.335)
    assert stats["max_drawdown"] == pytest.approx(-0.0007)
    summary = cohort_summary(rows)
    assert summary[0]["Cerradas"] == 1 and summary[0]["Ganadoras · %"] == 100
    assert summary[1]["Entradas"] == 0
