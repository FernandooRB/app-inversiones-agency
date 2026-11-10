"""A bad draft must not hide independent tools, leak exceptions, or publish a stale book."""

import logging
import re

import pytest
from streamlit.testing.v1 import AppTest

AREAS = ["ledger", "implementation", "feeds", "wealth", "documents"]
PRIVATE = "PRIVATE_ACCOUNT_ABC_987"
LEDGER = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
    b"Referencia,MomentoFlujo,Interes\n"
    b"opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    b"shares,2026-01-01,2026-01-01,OPEN_POSITION,SIM-A,MXN,2,0,0,0,0,,UNKNOWN,0\n"
)
NAV = b"Fecha,NAV\n2026-01-01,120\n2026-01-10,120\n"
BAD_NAV = b"Fecha,NAV\nNaT,120\n2026-01-10,120\n"


def error_screen(area, exception, *, stage=False):
    return AppTest.from_string(f'''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
from case_workspace import WorkspaceError
from portfolio_core import PortfolioError
st.session_state["visited"]=[]
def fail():
    raise {exception}
def renderer(name):
    def render(context):
        st.session_state["visited"].append(name)
        if name=={area!r}:
            if {stage!r}: ui._checked_input("Valuaciones históricas",fail)
            else: fail()
        st.write("Disponible: "+name)
    return render
with patch.object(ui,"_context",return_value=(None,None,None,None)), \
     patch.object(ui,"_ledger",renderer("ledger")), \
     patch.object(ui,"_implementation",renderer("implementation")), \
     patch.object(ui,"_feeds",renderer("feeds")), \
     patch.object(ui,"_wealth",renderer("wealth")), \
     patch.object(ui,"_documents",renderer("documents")):
    ui.render_account_operations()
''', default_timeout=35).run()


@pytest.mark.parametrize("area", AREAS)
def test_validation_error_keeps_other_tabs_available(area):
    app = error_screen(area, 'PortfolioError("El CSV requiere Fecha y NAV.")')
    assert not app.exception and app.error
    assert app.session_state["visited"] == AREAS
    assert any(item.value == "El CSV requiere Fecha y NAV." for item in app.text)
    assert len([item for item in app.markdown if item.value.startswith("Disponible:")]) == 4


def test_expected_error_identifies_stage_and_is_plain_text(caplog):
    message = "Falta NAV: [dato](https://example.test)"
    app = error_screen("ledger", f"PortfolioError({message!r})", stage=True)
    assert not app.exception
    assert app.error[0].value == "Revisa Valuaciones históricas."
    assert app.text[0].value == message
    assert not any(message in item.value for item in app.markdown)
    assert not any(record.name == "operations_ui" for record in caplog.records)


@pytest.mark.parametrize("kind", ["ValueError", "KeyError", "RuntimeError"])
def test_unexpected_errors_show_a_reference_and_log_no_values_or_traceback(kind, caplog):
    caplog.set_level(logging.ERROR, logger="operations_ui")
    app = error_screen("ledger", f"{kind}({PRIVATE!r})", stage=True)
    assert not app.exception and app.error and not app.text
    assert app.session_state["visited"] == AREAS
    visible = "\n".join(item.value for item in [*app.error, *app.caption, *app.markdown])
    assert PRIVATE not in visible and PRIVATE not in caplog.text
    reference = re.search(r"referencia: ([0-9a-f]{12})", visible).group(1)
    assert f"type={kind}" in caplog.text and f"reference={reference}" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("area", ["ledger", "implementation", "feeds"])
def test_workspace_errors_stop_later_areas_without_exposing_details(area, caplog):
    app = error_screen(area, f"WorkspaceError({PRIVATE!r})", stage=True)
    assert not app.exception and app.error and not app.text
    assert app.session_state["visited"] == AREAS[:AREAS.index(area) + 1]
    assert "revisa tu acceso" in app.error[0].value
    assert PRIVATE not in app.error[0].value and PRIVATE not in caplog.text


def test_memory_failure_does_not_continue_with_other_calculations(caplog):
    app = error_screen("ledger", f"MemoryError({PRIVATE!r})", stage=True)
    assert not app.exception and app.error and not app.text
    assert app.session_state["visited"] == ["ledger"]
    assert PRIVATE not in caplog.text
    assert "type=MemoryError" in caplog.text


def test_context_failure_does_not_render_account_tools_or_private_details():
    app = AppTest.from_string(f'''
from unittest.mock import patch
import operations_ui as ui
from case_workspace import WorkspaceError
with patch.object(ui,"_context",side_effect=WorkspaceError({PRIVATE!r})):
    ui.render_account_operations()
''', default_timeout=30).run()
    assert not app.exception and app.error and not app.button
    assert PRIVATE not in app.error[0].value


def test_streamlit_rerun_keeps_its_control_flow():
    app = AppTest.from_string('''
import streamlit as st
from operations_ui import _render_operation_area
def render(context):
    if not st.session_state.get("reran"):
        st.session_state["reran"]=True
        st.rerun()
    st.write("Revisión retomada")
_render_operation_area(None,"ledger","Movimientos",render)
''', default_timeout=30).run()
    assert not app.exception and not app.error
    assert any(item.value == "Revisión retomada" for item in app.markdown)


def book_screen():
    recovery = {"token": "seed", "files": {"ledger": LEDGER, "nav": NAV},
                "settings": {"cutoff": "2026-01-10", "base": "MXN"}, "code_changed": False}
    return AppTest.from_string(f'''
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
st.session_state.setdefault("_ops_review_temporary",{recovery!r})
with patch.object(st,"file_uploader",return_value=None):
    ui._render_operation_area((None,None,None,None),"ledger","Movimientos",ui._ledger)
book=st.session_state.get(ui._key("_ops_last_book"))
st.session_state["book_available"]=bool(book)
if book:
    st.checkbox("Confirmé cantidades para seguimiento",key=ui._key("monitor_confirmation"))
else:
    st.info("Sin referencia para cantidades de seguimiento")
''', default_timeout=40).run()


@pytest.mark.parametrize("role,bad", [("ledger", b"bad\nrow\n"), ("nav", BAD_NAV)])
def test_bad_input_clears_book_reference_and_removes_previous_returns(role, bad):
    app = book_screen()
    app.checkbox(key="flows_confirmation_temporary_seed").check().run()
    app.checkbox(key="monitor_confirmation_temporary").check().run()
    assert app.session_state["book_available"] and app.metric
    app.session_state["_ops_review_temporary"]["files"][role] = bad
    app.run()
    assert not app.exception and app.error and not app.metric
    assert not app.session_state["book_available"]
    assert "_ops_last_book_temporary" not in app.session_state
    assert "_ops_book_signature_temporary" not in app.session_state
    app.session_state["_ops_review_temporary"]["files"][role] = LEDGER if role == "ledger" else NAV
    app.run()
    assert not app.exception and not app.error and app.session_state["book_available"]
    assert not app.checkbox(key="monitor_confirmation_temporary").value


def test_unchanged_book_preserves_explicit_monitor_confirmation():
    app = book_screen()
    app.checkbox(key="monitor_confirmation_temporary").check().run()
    assert not app.exception and not app.error
    assert app.checkbox(key="monitor_confirmation_temporary").value


@pytest.mark.parametrize("change", ["source", "cutoff", "review"])
def test_new_book_date_or_recovered_review_requires_new_monitor_confirmation(change):
    app = book_screen()
    app.checkbox(key="monitor_confirmation_temporary").check().run()
    if change == "source":
        changed = LEDGER.replace(b",MXN,2,0,", b",MXN,3,0,")
        app.session_state["_ops_review_temporary"]["files"]["ledger"] = changed
    elif change == "cutoff":
        from datetime import date

        app.date_input(key="ops_cutoff_temporary_seed").set_value(date(2026, 1, 11))
    else:
        app.session_state["_ops_review_temporary"]["token"] = "other-review"
    app.run()
    assert not app.exception and not app.error
    assert not app.checkbox(key="monitor_confirmation_temporary").value
