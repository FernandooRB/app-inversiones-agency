"""Review findings must preserve source differences, coverage limits and current-run isolation."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from ledger_reconciliation import ClosingControl, reconcile_book
from operations_status import OperationStatus, status_text
from realized_performance import Flow, valuation_requirements
from transaction_ledger import Event, book_at

CUT = date(2026, 1, 10)
START = date(2026, 1, 1)
LEDGER = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
    b"Referencia,MomentoFlujo,Interes\n"
    b"opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    b"flow,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n"
)
NAV = b"Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,150\n"
CONTROLS = (b"Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente\n"
            b"2026-01-10,CASH,,MXN,150.01,Comprobante ficticio\n")


def review():
    status = OperationStatus(cutoff=CUT.isoformat(), base="MXN")
    status.book = book_at([Event("open", START, START, "OPEN_CASH", amount=100)], CUT)
    status.input("ledger", BytesIO(LEDGER))
    return status


def test_difference_is_exact_and_does_not_change_the_book_or_approve_anything():
    status = review()
    status.reconciliation = reconcile_book(
        status.book, [ClosingControl(CUT, "CASH", "", "MXN", "100.01", "Statement")], cutoff=CUT,
    )
    row = next(row for row in status.issues() if row["id"].startswith("control:"))
    assert "-0.01 MXN" in row["reason"] and row["state"] == "Diferencia"
    assert status.book["cash"]["MXN"] == Decimal(100)
    snapshot = status.snapshot("Ficticia")
    assert snapshot["human_approval"] is None and snapshot["postings_created"] == 0
    assert snapshot["issue_count"] == len(snapshot["issues"])
    text = status_text(snapshot).decode()
    assert row["reason"] in text and row["evidence"] in text
    assert "sin sumar monedas" in text


def test_missing_control_is_unknown_even_for_zero_balance():
    status = review()
    status.book["cash"]["USD"] = Decimal(0)
    status.reconciliation = reconcile_book(
        status.book, [ClosingControl(CUT, "CASH", "", "MXN", 100, "Statement")], cutoff=CUT,
    )
    row = next(row for row in status.issues() if row["id"].startswith("control:"))
    assert row["state"] == "Falta dato" and "no se interpreta como cero" in row["reason"]
    assert "USD" in row["reason"]


def test_unknown_timing_and_conditional_date_never_become_confirmed_from_available_nav():
    status = review()
    status.events = [Event("transfer", date(2026, 1, 5), date(2026, 1, 5), "TRANSFER_IN", amount=50)]
    status.input("nav", BytesIO(NAV))
    status.calendar = valuation_requirements(START, CUT, [Flow(date(2026, 1, 5), 50)],
                                             available_dates=[START, date(2026, 1, 5), CUT])
    status.flows_confirmed = True
    issues = status.issues()
    assert next(row for row in issues if row["id"] == "date:2026-01-04")["state"] == "Condicional"
    assert any(row["id"] == "timing:transfer" for row in issues)
    assert any(row["id"] == "transfers" for row in issues)
    assert status.snapshot("Ficticia")["conditional_count"] == 1
    assert not status.calendar["twr_coverage_ready"]


@pytest.mark.parametrize("base,needs_fx", [("MXN", False), ("USD", True)])
def test_currency_controls_the_need_for_fx_without_relabeling_cash(base, needs_fx):
    status = review()
    status.base = base
    assert any(row["id"] == "fx" for row in status.issues()) == needs_fx
    assert status.snapshot("Ficticia")["balances"][0]["currency"] == "MXN"


def test_failed_ledger_retires_balances_and_results_but_preserves_rejection_evidence():
    status = review()
    status.valuation = {"nav": 100}
    status.returns = {"twr": 0, "xirr": 0}
    status.fail("ledger", "Valuaciones históricas", "Fecha inválida")
    snapshot = status.snapshot("Ficticia")
    assert snapshot["ledger_failed"] and not snapshot["balances"]
    assert snapshot["returns"] is None and snapshot["valuation"] is None
    assert snapshot["inputs"]["ledger"]["sha256"]
    assert snapshot["issues"][0]["reason"] == "Fecha inválida"


def screen():
    recovery = {"token": "status-fixture", "files": {"ledger": LEDGER, "nav": NAV, "controls": CONTROLS},
                "settings": {"cutoff": CUT.isoformat(), "base": "MXN"}, "code_changed": False}
    return AppTest.from_string(f'''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
from hashlib import sha256
scope=sha256(str((None,None,None)).encode()).hexdigest()[:16]
st.session_state.setdefault("_ops_review_"+scope,{recovery!r})
with patch.object(ui,"_context",return_value=(None,None,None,None)), \
     patch.object(st,"file_uploader",return_value=None):
    ui.render_account_operations()
''', default_timeout=40).run()


def snapshot_from(app):
    from hashlib import sha256

    scope = sha256(str((None, None, None)).encode()).hexdigest()[:16]
    return app.session_state["_ops_status_" + scope].snapshot("Ficticia"), scope


def test_panel_actions_select_the_real_tool_and_preserve_data_and_checks():
    app = screen()
    snapshot, scope = snapshot_from(app)
    assert not app.exception and not app.error
    assert snapshot["input_count"] == 3 and snapshot["issue_count"] == len(snapshot["issues"])
    assert "-0.01" in next(row["reason"] for row in snapshot["issues"] if row["state"] == "Diferencia")
    app.button(key="status_next_" + scope).click().run()
    assert not app.exception and not app.error
    assert app.session_state["operations_tabs"] == "Movimientos"
    assert app.session_state["_ops_focus_step_" + scope] == "controls"
    assert any(e.label == "Conciliar contra el estado de cuenta" and e.proto.expanded for e in app.expander)
    assert snapshot_from(app)[0]["inputs"] == snapshot["inputs"]
    assert not app.metric


def test_replacing_invalid_nav_refreshes_panel_without_stale_balances_or_return():
    app = screen()
    _, scope = snapshot_from(app)
    app.checkbox(key="flows_confirmation_" + scope + "_status-fixture").check().run()
    assert snapshot_from(app)[0]["returns"]["twr"] == 0
    app.session_state["_ops_review_" + scope]["files"]["nav"] = b"Fecha,NAV\nNaT,100\n2026-01-10,150\n"
    app.run()
    broken = snapshot_from(app)[0]
    assert not app.exception and broken["ledger_failed"] and broken["returns"] is None
    assert not broken["balances"] and not app.metric
    app.session_state["_ops_review_" + scope]["files"]["nav"] = NAV
    app.run()
    restored = snapshot_from(app)[0]
    assert not app.exception and not app.error and not restored["ledger_failed"]
    assert not restored["returns"] and restored["balances"]


def test_removing_a_file_drops_its_hash_and_other_account_has_no_previous_findings():
    app = screen()
    prior, scope = snapshot_from(app)
    app.session_state["_ops_review_" + scope]["files"].pop("controls")
    app.run()
    current, _ = snapshot_from(app)
    assert current["input_count"] == 2 and "controls" not in current["inputs"]
    assert any(row["id"] == "controls" for row in current["issues"])
    fresh = OperationStatus().snapshot("Otra cuenta")
    assert not fresh["inputs"] and not fresh["balances"]
    assert all(row["reason"] not in [r["reason"] for r in prior["issues"]] for row in fresh["issues"])


def test_document_findings_keep_source_and_do_not_link_the_original_to_the_ledger():
    status = review()
    status.documents = [{"name": "<script>.pdf", "sha256": "a" * 64, "notice": "Vincular original",
                         "differences": [{"Pagina": 2, "Fila": 3, "Diferencia": "-0.01"}]}]
    rows = [row for row in status.issues() if row["area"] == "Originales GBM"]
    assert len(rows) == 2 and all("<script>.pdf" in row["evidence"] for row in rows)
    assert rows[0]["state"] == "Diferencia" and "Página 2 · fila 3" in rows[0]["reason"]
    assert status.snapshot("Ficticia")["human_approval"] is None


def test_unexpected_error_values_are_absent_from_panel_and_download():
    app = AppTest.from_string('''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
from operations_status import OperationStatus, status_text
def broken(context):
    st.session_state[ui._key("_ops_status")]=OperationStatus()
    ui._checked_input("Libro de movimientos",lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE_SENTINEL")))
with patch.object(ui,"_context",return_value=(None,None,None,None)),patch.object(ui,"_ledger",broken):
    ui.render_account_operations()
status=st.session_state[ui._key("_ops_status")]
st.session_state["report"]=status_text(status.snapshot("Ficticia")).decode()
''', default_timeout=35).run()
    assert not app.exception and app.error
    assert "PRIVATE_SENTINEL" not in app.session_state["report"]
    assert "Referencia de soporte:" in app.session_state["report"]
    assert not any("PRIVATE_SENTINEL" in element.value for element in [*app.text, *app.caption])


def test_same_session_switching_account_does_not_reuse_previous_review_or_download():
    recovery = {"token": "scoped", "files": {"ledger": LEDGER, "nav": NAV},
                "settings": {"cutoff": CUT.isoformat(), "base": "MXN"}}
    app = AppTest.from_string(f'''
from unittest.mock import patch
from hashlib import sha256
import streamlit as st
import operations_ui as ui
st.session_state.setdefault("selected_account","A")
account=st.session_state["selected_account"]
state={{"id":"fictitious-case","alias":"Ficticia","accounts":[
    {{"id":account,"portfolio":account,"product":"Inversiones","currency":"MXN"}}]}}
scope=sha256(str((None,state["id"],"A")).encode()).hexdigest()[:16]
st.session_state.setdefault("_ops_review_"+scope,{recovery!r})
with patch.object(ui,"_context",return_value=(None,None,state,account)), \
     patch.object(st,"file_uploader",return_value=None):
    ui.render_account_operations()
st.session_state["current_snapshot"]=st.session_state[ui._key("_ops_status")].snapshot(account)
''', default_timeout=40).run()
    assert not app.exception and app.session_state["current_snapshot"]["input_count"] == 2
    app.session_state["selected_account"] = "B"
    app.run()
    snapshot = app.session_state["current_snapshot"]
    assert not app.exception and snapshot["scope"] == "B"
    assert snapshot["input_count"] == 0 and not snapshot["balances"] and not snapshot["returns"]
    assert len(snapshot["issues"]) == 1 and snapshot["issues"][0]["id"] == "ledger"
