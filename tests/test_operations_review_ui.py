"""Restoring a draft must reset consent, preserve scope, and permit replacing recovered inputs."""

from streamlit.testing.v1 import AppTest

LEDGER = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
    b"Referencia,MomentoFlujo,Interes\n"
    b"opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
    b"flow,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n"
)
NAV = b"Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,150\n"
RECOVERY = {"token": "seed", "files": {"ledger": LEDGER, "nav": NAV},
            "settings": {"cutoff": "2026-01-10", "base": "MXN"}, "code_changed": False}


def screen(extra=""):
    return AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_ui import _ledger
st.session_state.setdefault("_ops_review_temporary", {RECOVERY!r})
{extra}
with patch.object(st,"file_uploader",return_value=None):
    _ledger((None,None,None,None))
''', default_timeout=40).run()


def test_recovered_inputs_restore_date_currency_and_calendar_without_approval():
    app = screen('st.session_state.setdefault("flows_confirmation_temporary",True)')
    assert not app.error and not app.exception and not app.metric
    assert app.date_input[0].value.isoformat() == "2026-01-10"
    assert all(not item.value for item in app.checkbox)
    assert any("Revisión recuperada" in item.value for item in app.info)
    assert any(item.proto.label == "Descargar paquete de movimientos" for item in app.get("download_button"))
    assert any("se renuevan las confirmaciones" in item.value for item in app.caption)


def test_currency_change_invalidates_both_confirmations_and_old_return_metrics():
    app = screen()
    app.checkbox(key="raw_confirmation_temporary_seed").check().run()
    app.checkbox(key="flows_confirmation_temporary_seed").check().run()
    assert not app.error and not app.exception
    assert next(item.value for item in app.metric if item.label == "TWR del periodo") == "0.00%"
    app.selectbox(key="ops_base_temporary_seed").select("USD").run()
    assert not app.error and not app.exception and not app.metric
    assert all(not item.value for item in app.checkbox)


def test_changed_nav_requires_a_new_flow_confirmation():
    app = screen()
    app.checkbox(key="flows_confirmation_temporary_seed").check().run()
    assert any(item.label == "TWR del periodo" for item in app.metric)
    changed = NAV.replace(b"2026-01-10,150", b"2026-01-10,160")
    app.session_state["_ops_review_temporary"]["files"]["nav"] = changed
    app.run()
    assert not app.error and not app.exception and not app.metric
    assert not app.checkbox(key="flows_confirmation_temporary_seed").value


def test_removing_recovered_ledger_clears_the_book_used_by_other_operations():
    app = screen()
    assert "_ops_last_book_temporary" in app.session_state
    app.button(key="remove_ledger_temporary_seed").click().run()
    assert not app.error and not app.exception and not app.metric
    assert "_ops_last_book_temporary" not in app.session_state
    assert any("Importa el libro" in item.value for item in app.info)


def test_other_context_does_not_see_recovered_files():
    app = screen('st.session_state.setdefault("_ops_context_key","other-account")')
    assert not app.error and not app.exception and not app.metric and not app.date_input
    assert not any("Recuperado:" in item.value for item in app.caption)
    assert any("Importa el libro" in item.value for item in app.info)


def test_replacement_does_not_resurrect_recovered_file_when_upload_is_removed():
    app = AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_review_ui import review_upload
st.session_state.setdefault("_ops_review_temporary", {RECOVERY!r})
replace=st.checkbox("Usar reemplazo",value=True)
with patch.object(st,"file_uploader",return_value=BytesIO(b"replacement") if replace else None):
    source=review_upload("Libro", "ledger", key="ops_ledger")
st.write(source.getvalue().decode() if source else "Sin libro")
''', default_timeout=30).run()
    assert not app.error and not app.exception
    assert "ledger" not in app.session_state["_ops_review_temporary"]["files"]
    app.checkbox[0].uncheck().run()
    assert not app.error and not app.exception
    assert any(item.value == "Sin libro" for item in app.markdown)


def test_opening_a_zip_replaces_a_review_and_resets_confirmations():
    app = AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_review import build_operations_review
from operations_ui import _ledger
st.session_state.setdefault("_ops_review_temporary", {RECOVERY!r})
_,bundle=build_operations_review({{"ledger":{LEDGER!r},"nav":{NAV!r}}},cutoff="2026-01-10",base="MXN")
def uploaded(label,**kwargs):
    return BytesIO(bundle) if label=="Paquete de movimientos ZIP" else None
with patch.object(st,"file_uploader",side_effect=uploaded):
    _ledger((None,None,None,None))
''', default_timeout=40).run()
    app.checkbox(key="flows_confirmation_temporary_seed").check().run()
    assert app.metric
    app.button(key="ops_review_open_temporary").click().run()
    assert not app.error and not app.exception and not app.metric
    assert app.session_state["_ops_review_temporary"]["token"] != "seed"
    assert all(not item.value for item in app.checkbox)


def test_bad_zip_does_not_replace_the_current_review_or_book():
    app = AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_ui import _ledger
st.session_state.setdefault("_ops_review_temporary", {RECOVERY!r})
def uploaded(label,**kwargs):
    return BytesIO(b"not a ZIP") if label=="Paquete de movimientos ZIP" else None
with patch.object(st,"file_uploader",side_effect=uploaded):
    _ledger((None,None,None,None))
''', default_timeout=40).run()
    app.button(key="ops_review_open_temporary").click().run()
    assert not app.exception and app.error
    assert app.session_state["_ops_review_temporary"]["token"] == "seed"
    assert app.session_state["_ops_last_book_temporary"]["book"]["cash"]["MXN"] == 150
