from datetime import UTC, datetime

from alpaca_order_fakes import ACCOUNT_ID, FakePaper
from streamlit.testing.v1 import AppTest

import alpaca_paper_ui
from alpaca_order_store import SQLiteOrderStore
from alpaca_paper import AlpacaPaperError


def open_orders(monkeypatch, tmp_path):
    server = FakePaper(datetime.now(UTC))
    allowed = {"value": True}

    def factory(issuer, subject):
        if not allowed["value"] or subject != "alice":
            raise AlpacaPaperError("La sesión no está autorizada.")
        return server.client

    monkeypatch.setattr(alpaca_paper_ui, "configured_alpaca_paper", factory)
    path = str(tmp_path / "watchlist.db")
    code = ("import streamlit as st\nfrom pathlib import Path\n"
            "from watchlist_store import WatchlistStore\n"
            "from alpaca_paper_ui import render_alpaca_paper\n"
            f"render_alpaca_paper('issuer', st.session_state.get('test_subject', 'alice'), "
            f"watchlist_store=WatchlistStore(Path({path!r})))")
    app = AppTest.from_string(code, default_timeout=60).run()
    app.button(key="technical_alpaca_refresh").click().run()
    return app, server, allowed


def proposal(app, quantity=1):
    app.text_input(key="technical_alpaca_order_symbol").set_value("SIM")
    app.number_input(key="technical_alpaca_order_quantity").set_value(quantity)
    app.number_input(key="technical_alpaca_order_price").set_value(100.0)
    app.button(key="technical_alpaca_order_prepare").click().run()
    assert not app.exception and not app.error


def confirm(app):
    checkbox = next(item for item in app.checkbox if item.key.startswith("technical_alpaca_order_confirm_"))
    checkbox.check().run()
    app.button(key="technical_alpaca_order_submit").click().run()


def tracking(app):
    return next(item.value for item in app.dataframe if "ID de intento" in item.value.columns)


def test_prepare_confirm_partial_fill_and_completion_are_separate_actions(monkeypatch, tmp_path):
    app, server, _ = open_orders(monkeypatch, tmp_path)
    proposal(app, quantity=2)
    assert not server.posts
    assert app.button(key="technical_alpaca_order_submit").disabled
    assert any("en cola" in item.value for item in app.info)
    confirm(app)
    assert not app.exception and not app.error
    assert len(server.posts) == 1
    assert tracking(app).loc[0, "Estado"] == "Pendiente"
    assert tracking(app).loc[0, "Ejecutados"] == 0
    row = next(iter(server.orders.values()))
    row.update(status="partially_filled", filled_qty="1", filled_avg_price="99")
    app.button(key="technical_alpaca_order_reconcile").click().run()
    assert not app.exception and tracking(app).loc[0, "Estado"] == "Ejecución parcial"
    row.update(status="filled", filled_qty="2", filled_avg_price="99.50")
    app.button(key="technical_alpaca_order_reconcile").click().run()
    assert not app.exception and tracking(app).loc[0, "Estado"] == "Ejecutada"
    assert tracking(app).loc[0, "Precio medio · USD"] == 99.5
    assert len(server.posts) == 1
    store = SQLiteOrderStore((tmp_path / "watchlist.db").with_suffix(".alpaca-orders.db"))
    assert len(store.load("issuer", "alice", ACCOUNT_ID)) == 4
    assert not store.load("issuer", "bob", ACCOUNT_ID)


def test_editing_proposal_clears_confirmation_and_expired_authorization_prevents_post(monkeypatch, tmp_path):
    app, server, allowed = open_orders(monkeypatch, tmp_path)
    proposal(app)
    app.number_input(key="technical_alpaca_order_price").set_value(101.0).run()
    assert not any(item.key == "technical_alpaca_order_submit" for item in app.button)
    proposal(app)
    checkbox = next(item for item in app.checkbox if item.key.startswith("technical_alpaca_order_confirm_"))
    checkbox.check().run()
    allowed["value"] = False
    app.button(key="technical_alpaca_order_submit").click().run()
    assert not app.exception and not server.posts
    assert not app.metric
    assert "_technical_alpaca_draft" not in app.session_state.filtered_state


def test_timeout_keeps_attempt_visible_and_blocks_another_proposal(monkeypatch, tmp_path):
    app, server, _ = open_orders(monkeypatch, tmp_path)
    proposal(app)
    server.mode = "timeout_no_accept"
    confirm(app)
    assert not app.exception
    assert tracking(app).loc[0, "Estado"] == "Sin confirmar"
    assert not any(item.key == "technical_alpaca_order_prepare" for item in app.button)
    assert app.button(key="technical_alpaca_order_reconcile")
    app.button(key="technical_alpaca_order_reconcile").click().run()
    assert not app.exception and len(server.posts) == 1
