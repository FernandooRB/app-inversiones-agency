"""Fictional practice must be reproducible, isolated, and unable to access real account tools."""

from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ledger_reconciliation import read_closing_controls, reconcile_book
from operations_demo import DEMO_CONTEXT, DEMO_NAV_COMPLETE, demo_operations, demo_url
from realized_performance import Flow, performance
from transaction_ledger import book_at, read_ledger


def demo_screen():
    return AppTest.from_string('''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
st.session_state.setdefault("_account_flow",{"private":"PRIVATE_ANALYSIS"})
st.session_state.setdefault("_execution_proposal",{"private":"PRIVATE_PROPOSAL"})
st.session_state.setdefault("_ops_review_real",{"files":{"ledger":b"PRIVATE_LEDGER"},"token":"real"})
with patch.object(ui,"_context",side_effect=AssertionError("Workspace read")), \
     patch.object(ui,"_implementation",side_effect=AssertionError("Real implementation")), \
     patch.object(ui,"_feeds",side_effect=AssertionError("Real feeds")), \
     patch.object(ui,"_wealth",side_effect=AssertionError("Real wealth")), \
     patch.object(ui,"_documents",side_effect=AssertionError("Real documents")):
    ui.render_account_operations(demo=True)
''', default_timeout=40).run()


def test_fictional_inputs_reproduce_the_exact_cent_and_flow_coverage_without_adjustments():
    files, settings = demo_operations()
    events = read_ledger(files["ledger"])
    cutoff = date.fromisoformat(settings["cutoff"])
    book = book_at(events, cutoff)
    reconciliation = reconcile_book(book, read_closing_controls(files["controls"], cutoff), cutoff=cutoff)
    assert str(book["cash"]["MXN"]) == "150"
    assert str(reconciliation["rows"][0]["Diferencia"]) == "-0.01"
    assert reconciliation["human_approval"] is None and reconciliation["postings_created"] == 0
    flows = [Flow(e.settled, float(e.amount), e.timing) for e in events if e.kind == "DEPOSIT"]
    nav = pd.read_csv(BytesIO(files["nav"]), index_col="Fecha")["NAV"]
    assert performance(nav, flows)["twr"] is None
    complete = pd.read_csv(BytesIO(DEMO_NAV_COMPLETE), index_col="Fecha")["NAV"]
    result = performance(complete, flows)
    assert result["gain"] == 0 and result["twr"] == 0 and result["net_flow"] == 50
    files["nav"] = b"replaced"
    settings["base"] = "USD"
    fresh_files, fresh_settings = demo_operations()
    assert fresh_files["nav"] != files["nav"] and fresh_settings["base"] == "MXN"


@pytest.mark.parametrize("url,expected", [
    ("https://app.example/", "https://app.example/?demo_operacion=1"),
    ("https://app.example/prefix/?cuenta=private#archivo", "https://app.example/prefix/?demo_operacion=1"),
    ("http://127.0.0.1:8540/?other=1", "http://127.0.0.1:8540/?demo_operacion=1"),
    (None, "?demo_operacion=1"),
])
def test_demo_link_keeps_origin_and_path_without_forwarding_account_queries(url, expected):
    assert demo_url(url) == expected


def test_one_click_seed_has_no_imported_consent_and_never_reads_other_account_tools():
    app = demo_screen()
    assert not app.exception and not app.error
    assert app.title[0].value == "Demo de revisión"
    assert app.session_state["_ops_context_key"] == DEMO_CONTEXT
    status = app.session_state["_ops_status_" + DEMO_CONTEXT]
    assert status.calendar["missing_required_dates"] == ["2026-01-05"]
    assert len(status.inputs) == 3 and len(status.issues()) == 4
    assert not status.flows_confirmed and not status.raw_confirmed and not app.metric
    assert app.session_state["_account_flow"] == {"private": "PRIVATE_ANALYSIS"}
    assert app.session_state["_execution_proposal"] == {"private": "PRIVATE_PROPOSAL"}
    assert app.session_state["_ops_review_real"]["files"]["ledger"] == b"PRIVATE_LEDGER"
    visible = "\n".join(e.value for e in [*app.text, *app.markdown, *app.caption])
    assert "DEMO" in visible and "PRIVATE" not in visible
    labels = [item.proto.label for item in app.get("download_button")]
    assert "Descargar paquete de movimientos" not in labels
    assert not any(button.label == "Guardar para continuar después" for button in app.button)
    assert not any(button.label.startswith("Conservar ") for button in app.button)
    assert not any(expander.label == "Abrir paquete de movimientos" for expander in app.expander)


def test_practice_requires_actual_csv_correction_and_new_confirmation_before_zero_twr():
    app = demo_screen()
    assert app.button(key="guidance_next_" + DEMO_CONTEXT).label == "Abrir calendario de valuaciones"
    app.button(key="guidance_next_" + DEMO_CONTEXT).click().run()
    assert any(e.label == "Valuaciones necesarias para TWR" and e.proto.expanded for e in app.expander)
    token = app.session_state["_ops_review_" + DEMO_CONTEXT]["token"]
    key = "flows_confirmation_" + DEMO_CONTEXT + "_" + token
    app.checkbox(key=key).check().run()
    assert not app.exception and not app.error
    assert next(m.value for m in app.metric if m.label == "TWR del periodo") == "Pendiente"
    app.session_state["_ops_review_" + DEMO_CONTEXT]["files"]["nav"] = DEMO_NAV_COMPLETE
    app.run()
    assert not app.exception and not app.error and not app.metric
    assert not app.checkbox(key=key).value
    assert app.button(key="guidance_next_" + DEMO_CONTEXT).label == "Abrir revisión de flujos"
    app.button(key="guidance_next_" + DEMO_CONTEXT).click().run()
    assert not app.checkbox(key=key).value and not app.metric
    app.checkbox(key=key).check().run()
    assert not app.exception and not app.error
    assert next(m.value for m in app.metric if m.label == "TWR del periodo") == "0.00%"
    status = app.session_state["_ops_status_" + DEMO_CONTEXT]
    assert str(status.reconciliation["rows"][0]["Diferencia"]) == "-0.01"
    assert status.snapshot("DEMO")["human_approval"] is None
    assert app.button(key="guidance_next_" + DEMO_CONTEXT).label == "Abrir resumen descargable"


def test_reset_restores_only_demo_bytes_and_requires_confirmation_again():
    app = demo_screen()
    recovery = app.session_state["_ops_review_" + DEMO_CONTEXT]
    old_token = recovery["token"]
    recovery["files"]["nav"] = DEMO_NAV_COMPLETE
    app.run()
    app.checkbox(key="flows_confirmation_" + DEMO_CONTEXT + "_" + old_token).check().run()
    assert app.metric
    app.button(key="demo_reset").click().run()
    fresh = app.session_state["_ops_review_" + DEMO_CONTEXT]
    assert not app.exception and not app.error and not app.metric
    assert fresh["token"] != old_token and fresh["files"] == demo_operations()[0]
    assert app.button(key="guidance_next_" + DEMO_CONTEXT).label == "Abrir calendario de valuaciones"
    assert not app.checkbox(key="flows_confirmation_" + DEMO_CONTEXT + "_" + fresh["token"]).value
    assert app.session_state["_ops_review_real"] == {"files": {"ledger": b"PRIVATE_LEDGER"}, "token": "real"}
    assert app.session_state["_execution_proposal"] == {"private": "PRIVATE_PROPOSAL"}


def test_demo_download_is_labeled_and_never_uses_a_real_account_scope():
    app = AppTest.from_string('''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
def download(label,data,*args,**kwargs):
    if label=="Descargar resumen de revisión":
        st.session_state["summary"]=data.decode()
        st.session_state["summary_filename"]=args[0]
    return False
with patch.object(st,"download_button",side_effect=download):
    ui.render_account_operations(demo=True)
''', default_timeout=40).run()
    assert not app.exception and not app.error
    assert app.session_state["summary"].startswith("DEMO · Resumen de práctica de Operación")
    assert "Alcance: DEMO · datos de práctica SIG · sin cuenta vinculada" in app.session_state["summary"]
    assert "operations_demo.py" in app.session_state["summary"]
    assert app.session_state["summary_filename"].startswith("demo_resumen_revision_")


def test_demo_deep_link_routes_after_the_existing_access_check(monkeypatch):
    import access
    import operations_ui

    calls = []
    monkeypatch.setattr(access, "require_access", lambda: calls.append("access"))
    monkeypatch.setattr(operations_ui, "_context", lambda: pytest.fail("Read real workspace"))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=40)
    app.query_params["demo_operacion"] = "1"
    app.run()
    assert not app.exception and not app.error and calls == ["access"]
    assert app.title[0].value == "Demo de revisión" and not app.text_input


def test_demo_deep_link_cannot_skip_access_when_access_stops_the_app(monkeypatch):
    import streamlit as st

    import access

    monkeypatch.setattr(access, "require_access", st.stop)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=40)
    app.query_params["demo_operacion"] = "1"
    app.run()
    assert not app.exception and not app.title
    assert "_ops_review_" + DEMO_CONTEXT not in app.session_state
