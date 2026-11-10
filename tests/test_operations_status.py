"""Review findings must preserve source differences, coverage limits and current-run isolation."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from ledger_reconciliation import ClosingControl, reconcile_book
from operations_status import OperationStatus, status_text
from realized_performance import Flow, valuation_requirements
from transaction_ledger import book_at, read_ledger

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
    status.book = book_at(read_ledger(LEDGER), CUT)
    status.input("ledger", BytesIO(LEDGER))
    return status


def test_difference_is_exact_and_does_not_change_the_book_or_approve_anything():
    status = review()
    status.reconciliation = reconcile_book(
        status.book, [ClosingControl(CUT, "CASH", "", "MXN", "150.01", "Statement")], cutoff=CUT,
    )
    row = next(row for row in status.issues() if row["id"].startswith("control:"))
    assert "-0.01 MXN" in row["reason"] and row["state"] == "Diferencia"
    assert status.book["cash"]["MXN"] == Decimal(150)
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
        status.book, [ClosingControl(CUT, "CASH", "", "MXN", 150, "Statement")], cutoff=CUT,
    )
    row = next(row for row in status.issues() if row["id"].startswith("control:"))
    assert row["state"] == "Falta dato" and "no se interpreta como cero" in row["reason"]
    assert "USD" in row["reason"]


def test_unknown_timing_and_conditional_date_never_become_confirmed_from_available_nav():
    status = review()
    changed = LEDGER.replace(b",DEPOSIT,", b",TRANSFER_IN,").replace(b",,EOD,0", b",Ficticia,UNKNOWN,0")
    status.input("ledger", BytesIO(changed))
    status.book = book_at(read_ledger(changed), CUT)
    status.events = [event for event in read_ledger(changed) if event.kind == "TRANSFER_IN"]
    status.input("nav", BytesIO(NAV))
    status.calendar = valuation_requirements(START, CUT, [Flow(date(2026, 1, 5), 50)],
                                             available_dates=[START, date(2026, 1, 5), CUT])
    status.flows_confirmed = True
    issues = status.issues()
    assert next(row for row in issues if row["id"] == "date:2026-01-04")["state"] == "Condicional"
    assert any(row["id"] == "timing:flow" for row in issues)
    assert any(row["id"] == "transfers" for row in issues)
    assert status.snapshot("Ficticia")["conditional_count"] == 1
    assert not status.calendar["twr_coverage_ready"]
    assert status.guidance()["step"] == "calendar"
    assert status.guidance()["states"]["calendar"] == "Pendiente"


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
def uploaded(*args,**kwargs):
    return [] if kwargs.get("accept_multiple_files") else None
with patch.object(ui,"_context",return_value=(None,None,None,None)), \
     patch.object(st,"file_uploader",side_effect=uploaded):
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
    next(button for button in app.button if button.label == "Ver revisión de flujos").click().run()
    assert not app.exception and not app.error
    assert app.session_state["_ops_focus_step_" + scope] == "flows"
    assert any(e.label == "Revisión de flujos y resultado" and e.proto.expanded for e in app.expander)


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
    status.documents.append({**status.documents[0], "name": "Mismos bytes con otro nombre.pdf"})
    rows = [row for row in status.issues() if row["area"] == "Originales GBM"]
    assert len(rows) == 2 and all("<script>.pdf" in row["evidence"] for row in rows)
    assert len({row["id"] for row in status.issues()}) == len(status.issues())
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
def uploaded(*args,**kwargs):
    return [] if kwargs.get("accept_multiple_files") else None
with patch.object(ui,"_context",return_value=(None,None,state,account)), \
     patch.object(st,"file_uploader",side_effect=uploaded):
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


def test_zero_return_and_missing_xirr_are_distinct_in_the_readable_summary():
    status = review()
    status.returns = {"gain": 0, "twr": 0, "xirr": None, "twr_status": "CALCULADA",
                      "xirr_status": "SIN_RAIZ_EN_RANGO"}
    text = status_text(status.snapshot("Ficticia")).decode()
    assert "TWR del periodo: 0.00%" in text
    assert "XIRR anualizada: Pendiente" in text


def test_large_queue_is_bounded_and_a_smaller_replacement_clamps_the_page():
    app = AppTest.from_string('''
import streamlit as st
import operations_ui as ui
from operations_status import OperationStatus
status=OperationStatus(inputs={"ledger":{"label":"Libro","sha256":"a"*64,"bytes":1}})
for i in range(st.session_state.get("count",35)):
    status.fail("documents","Originales GBM","Fila ficticia "+str(i))
st.session_state[ui._key("_ops_status")]=status
ui._status_panel((None,None,None,None))
''', default_timeout=30).run()
    app.checkbox(key="status_show_all_temporary").check().run()
    app.number_input(key="status_page_temporary").set_value(4).run()
    assert not app.exception and app.number_input[0].value == 4
    assert len([row for row in app.text if row.value.startswith("Fila ficticia")]) == 5
    app.session_state["count"] = 11
    app.run()
    assert not app.exception and app.number_input[0].value == 2
    assert len([row for row in app.text if row.value.startswith("Fila ficticia")]) == 1


def test_complete_dates_do_not_confirm_flows_or_hide_a_difference_and_zero_is_a_result():
    status = review()
    status.input("nav", BytesIO(NAV))
    status.reconciliation = reconcile_book(
        status.book, [ClosingControl(CUT, "CASH", "", "MXN", "150.01", "Statement")], cutoff=CUT,
    )
    status.calendar = valuation_requirements(START, CUT, [Flow(date(2026, 1, 5), 50, "EOD")],
                                             available_dates=[START, date(2026, 1, 5), CUT])
    guidance = status.snapshot("Ficticia")["guidance"]
    assert guidance["step"] == "flows" and guidance["states"]["calendar"] == "Completo"
    assert guidance["states"]["flows"] == "Por confirmar"
    assert guidance["states"]["returns"] == "Pendiente"
    assert not status.flows_confirmed and not status.raw_confirmed
    status.flows_confirmed = True
    assert status.guidance()["step"] == "flows"  # An acknowledgement alone is not a calculation.
    status.returns = {"gain": 0, "twr": 0, "xirr": 0, "twr_status": "CALCULADA", "xirr_status": "CALCULADA"}
    snapshot = status.snapshot("Ficticia")
    assert snapshot["guidance"]["step"] == "summary"
    assert snapshot["guidance"]["states"]["returns"] == "Calculado"
    assert snapshot["issue_count"] == 2 and "-0.01" in snapshot["issues"][0]["reason"]
    assert snapshot["human_approval"] is None and snapshot["postings_created"] == 0
    text = status_text(snapshot).decode()
    assert "Siguiente paso: Guardar el resumen de revisión" in text
    assert "Flujos: Confirmación registrada" in text and "TWR: Calculado" in text


@pytest.mark.parametrize("scenario,step", [("empty", "ledger"), ("no_nav", "calendar"),
                                           ("rejected", "ledger")])
def test_guidance_handles_empty_missing_and_rejected_inputs_without_previous_success(scenario, step):
    status = OperationStatus() if scenario == "empty" else review()
    if scenario == "rejected":
        status.calendar = {"twr_coverage_ready": True}
        status.flows_confirmed = True
        status.returns = {"twr": 0}
        status.fail("ledger", "Valuaciones históricas", "Fecha inválida")
    guidance = status.guidance()
    assert guidance["step"] == step
    assert guidance["states"]["calendar"] != "Completo"
    assert guidance["states"]["returns"] != "Calculado"
    assert status.returns is None


def test_primary_guide_opens_flows_and_summary_without_granting_or_removing_confirmation():
    app = screen()
    before, scope = snapshot_from(app)
    key = "flows_confirmation_" + scope + "_status-fixture"
    app.button(key="guidance_next_" + scope).click().run()
    assert not app.exception and not app.error
    assert app.session_state["_ops_focus_step_" + scope] == "flows"
    assert not app.checkbox(key=key).value and not app.metric
    assert snapshot_from(app)[0]["inputs"] == before["inputs"]
    assert any(e.label == "Revisión de flujos y resultado" and e.proto.expanded for e in app.expander)
    app.checkbox(key=key).check().run()
    assert app.button(key="guidance_next_" + scope).label == "Abrir resumen descargable"
    app.button(key="guidance_next_" + scope).click().run()
    after, _ = snapshot_from(app)
    assert not app.exception and not app.error and app.checkbox(key=key).value
    assert any(e.label == "Archivos y resumen descargable" and e.proto.expanded for e in app.expander)
    assert after["returns"]["twr"] == 0 and after["inputs"] == before["inputs"]
    assert after["issue_count"] == 2 and after["human_approval"] is None
