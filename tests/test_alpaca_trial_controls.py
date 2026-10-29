import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from alpaca_order_fakes import ACCOUNT_ID, FakePaper

from alpaca_order_store import SQLiteOrderStore
from alpaca_orders import prepare_order, submit_order
from alpaca_paper import AlpacaPaperError
from alpaca_results_sync import refresh_results
from alpaca_risk import plan_payload, settings_payload, usable_plan
from alpaca_trial_store import SQLiteTrialStore, exit_plans, stable_key


def controls(tmp_path, *, capital=1000, max_loss=100):
    now = datetime.now(UTC) + timedelta(seconds=1)
    server = FakePaper(now)
    orders = SQLiteOrderStore(tmp_path / "trial.db")
    trial = SQLiteTrialStore(orders.path)
    cfg = trial.append(
        "issuer",
        "alice",
        ACCOUNT_ID,
        "settings",
        settings_payload(capital, max_loss, capital, max_loss, "0.0035"),
    )
    plan = trial.append(
        "issuer",
        "alice",
        ACCOUNT_ID,
        "plan",
        plan_payload(
            "SIM", "100", "90", "120", (now + timedelta(days=20)).date(), "Salida sintética", now=now
        ),
    )
    return now, server, orders, trial, cfg, plan


def proposal(now, server, orders, trial, *, quantity=1):
    return prepare_order(
        server.client, orders, "issuer", "alice", "SIM", "buy", quantity, "100", now=now, trial_store=trial
    )


@pytest.mark.parametrize(
    "values", [(0, 10, 100, 10), (100, 101, 100, 10), (100, 10, 101, 10), (100, 10, 50, 11)]
)
def test_budgets_require_explicit_positive_consistent_amounts(values):
    with pytest.raises(AlpacaPaperError):
        settings_payload(*values, ".0035")


def test_budget_and_plan_are_saved_before_review_and_reserved_before_post(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path)
    draft = proposal(now, server, orders, trial)
    context = json.loads(draft.trial_json)
    assert Decimal(context["order_cost"]) == Decimal("100.3500")
    assert Decimal(context["order_loss"]) == Decimal("10.6650")
    assert context["max_quantity"] == 9
    assert not server.posts
    result = submit_order(
        server.client, orders, "issuer", "alice", draft, confirmed=True, now=now, trial_store=trial
    )
    assert result.draft.trial_json and len(server.posts) == 1
    assert "trial_context" not in json.loads(server.posts[0].content)
    assert not trial.load("issuer", "bob", ACCOUNT_ID)


def test_missing_budget_plan_or_oversize_blocks_before_post(tmp_path):
    now, server, orders, trial, cfg, _ = controls(tmp_path, capital=150)
    with pytest.raises(AlpacaPaperError, match="capital"):
        proposal(now, server, orders, trial, quantity=2)
    empty = SQLiteTrialStore(tmp_path / "empty.db")
    with pytest.raises(AlpacaPaperError, match="Configura"):
        proposal(now, server, orders, empty)
    empty.append("issuer", "alice", ACCOUNT_ID, "settings", cfg.payload)
    with pytest.raises(AlpacaPaperError, match="plan"):
        proposal(now, server, orders, empty)
    assert not server.posts


def test_revised_settings_invalidate_a_reviewed_proposal(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path)
    draft = proposal(now, server, orders, trial)
    trial.append("issuer", "alice", ACCOUNT_ID, "settings", settings_payload(900, 90, 800, 80, ".0035"))
    with pytest.raises(AlpacaPaperError, match="cambiaron"):
        submit_order(
            server.client, orders, "issuer", "alice", draft, confirmed=True, now=now, trial_store=trial
        )
    assert not server.posts


def test_two_distinct_concurrent_orders_cannot_spend_the_same_trial_capital(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path, capital=150)
    drafts = [proposal(now, server, orders, trial) for _ in range(2)]
    barrier = Barrier(2)
    original = server.client.fetch_open_orders

    def synchronized_open_orders():
        result = original()
        barrier.wait(timeout=10)
        return result

    server.client.fetch_open_orders = synchronized_open_orders

    def send(draft):
        try:
            return submit_order(
                server.client, orders, "issuer", "alice", draft, confirmed=True, now=now, trial_store=trial
            ).status
        except AlpacaPaperError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(send, drafts))
    assert len(server.posts) == 1
    assert sum("capital" in value for value in results) == 1
    assert sum(e.kind == "intent" for e in orders.load("issuer", "alice", ACCOUNT_ID)) == 1


def test_pending_buy_uses_trial_budget_and_unplanned_position_blocks_new_buy(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path, capital=150)
    draft = proposal(now, server, orders, trial)
    submit_order(server.client, orders, "issuer", "alice", draft, confirmed=True, now=now, trial_store=trial)
    with pytest.raises(AlpacaPaperError, match="capital"):
        proposal(now, server, orders, trial)
    server.positions = [
        {
            "symbol": "OTHER",
            "asset_class": "us_equity",
            "side": "long",
            "qty": "1",
            "avg_entry_price": "10",
            "current_price": "10",
            "market_value": "10",
            "unrealized_pl": "0",
        }
    ]
    with pytest.raises(AlpacaPaperError, match="OTHER"):
        proposal(now, server, orders, trial)


def test_expiry_uses_exchange_date_not_utc_midnight(tmp_path):
    now = datetime(2026, 10, 30, 1, tzinfo=UTC)
    trial = SQLiteTrialStore(tmp_path / "trial.db")
    event = trial.append(
        "issuer",
        "alice",
        ACCOUNT_ID,
        "plan",
        plan_payload("SIM", "100.1234", "90", "120", "2026-10-29", "Revisar hoy", now=now),
    )
    assert usable_plan(exit_plans([event]), "SIM", now).key == event.key


def test_alert_dedup_preserves_first_observation_and_other_users_are_isolated(tmp_path):
    trial = SQLiteTrialStore(tmp_path / "trial.db")
    key = stable_key("alert", "stop-SIM-day")
    first = trial.append("issuer", "alice", ACCOUNT_ID, "alert", {"message": "Primer precio"}, key=key)
    again = trial.append("issuer", "alice", ACCOUNT_ID, "alert", {"message": "Otro precio"}, key=key)
    assert again == first and len(trial.load("issuer", "alice", ACCOUNT_ID)) == 1
    assert not trial.load("issuer", "bob", ACCOUNT_ID)


def test_first_use_ui_requires_budget_before_buying(monkeypatch, tmp_path):
    from test_alpaca_orders_ui import open_orders

    app, server, _ = open_orders(monkeypatch, tmp_path, configured=False)
    app.text_input(key="technical_alpaca_order_symbol").set_value("SIM")
    app.number_input(key="technical_alpaca_order_price").set_value(100.0)
    app.button(key="technical_alpaca_order_prepare").click().run()
    assert not app.exception and any("Configura los límites" in e.value for e in app.error)
    assert not server.posts


def test_closed_loss_consumes_trial_budget_and_sales_remain_available(tmp_path):
    now, server, orders, trial, _, _ = controls(tmp_path, max_loss=20)
    buy = proposal(now, server, orders, trial)
    submit_order(server.client, orders, "issuer", "alice", buy, confirmed=True, now=now, trial_store=trial)
    row = server.orders[buy.client_order_id]
    row.update(status="filled", filled_qty="1", filled_avg_price="100",
               filled_at=(now + timedelta(seconds=5)).isoformat())
    server.positions = [{"symbol": "SIM", "asset_class": "us_equity", "side": "long", "qty": "1",
                         "qty_available": "1", "avg_entry_price": "100", "current_price": "90",
                         "market_value": "90", "unrealized_pl": "-10"}]
    sell = prepare_order(server.client, orders, "issuer", "alice", "SIM", "sell", 1, "90",
                          now=now + timedelta(seconds=10), trial_store=trial)
    submit_order(server.client, orders, "issuer", "alice", sell, confirmed=True,
                  now=now + timedelta(seconds=10), trial_store=trial)
    server.orders[sell.client_order_id].update(status="filled", filled_qty="1", filled_avg_price="90",
        filled_at=(now + timedelta(seconds=15)).isoformat())
    server.positions = []
    refresh_results(server.client, orders, "issuer", "alice", ACCOUNT_ID, trial_store=trial)
    with pytest.raises(AlpacaPaperError, match="pérdida prevista"):
        proposal(now + timedelta(seconds=20), server, orders, trial)
    assert len(server.posts) == 2


def test_user_can_configure_budget_and_exit_plan_through_the_ui(monkeypatch, tmp_path):
    from test_alpaca_orders_ui import open_orders
    from test_alpaca_orders_ui import proposal as ui_proposal

    app, server, _ = open_orders(monkeypatch, tmp_path, configured=False)
    for key, value in (("capital", 1000.0), ("loss", 100.0), ("position", 300.0), ("order_loss", 20.0)):
        app.number_input(key="technical_alpaca_order_budget_" + key).set_value(value)
    next(b for b in app.button if b.label == "Guardar límites de la prueba").click().run()
    assert not app.exception and not app.error
    app.text_input(key="technical_alpaca_order_plan_custom").set_value("SIM").run()
    app.number_input(key="technical_alpaca_order_plan_reference_SIM").set_value(100.0)
    app.number_input(key="technical_alpaca_order_plan_stop_SIM").set_value(90.0)
    app.number_input(key="technical_alpaca_order_plan_target_SIM").set_value(120.0)
    app.text_area(key="technical_alpaca_order_plan_reason_SIM").set_value("Revisión del plan de salida")
    next(b for b in app.button if b.label == "Guardar plan de salida").click().run()
    assert not app.exception and not app.error
    ui_proposal(app)
    assert not server.posts
    assert any("Pérdida prevista al stop" in item.value for item in app.markdown)
