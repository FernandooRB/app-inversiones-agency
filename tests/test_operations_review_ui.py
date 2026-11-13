"""Restoring a draft must reset consent, preserve scope, and permit replacing recovered inputs."""

import pytest
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


@pytest.mark.parametrize("token", [None, "seed"])
def test_clearing_moves_discards_only_current_inputs_and_rotates_both_upload_generations(monkeypatch, token):
    from types import SimpleNamespace

    import operations_review_ui as ui

    state = {"_ops_context_key": "account-a", "_ops_review_account-a": {**RECOVERY, "token": token},
             "_ops_open_token_account-a": "prior-open", "_ops_review_account-b": RECOVERY.copy(),
             "_account_flow": {"keep": "analysis"}, "ops_docs_account-a": b"keep originals",
             "ops_catalogue_account-a": b"keep catalogue", "_execution_proposal": {"keep": True}}
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    names = (*ui.ROLE_WIDGETS, "ops_cutoff", "ops_base", "raw_confirmation", "flows_confirmation",
             "signature_raw_confirmation", "signature_flows_confirmation", "ops_review_save_panel",
             "ops_review_download", *("remove_" + role for role in ui.ROLE_LABELS))
    old_keys = {ui.review_key(name) for name in names}
    old_keys.update(ui._open_key(name) for name in (
        "ops_review_open_panel", "ops_review_zip", "ops_review_open"))
    old_keys.update(ui._context_key(name) for name in (
        "_ops_last_book", "_ops_book_signature", "_ops_status", "_ops_focus_step", "monitor_confirmation"))
    for key in old_keys:
        state[key] = b"discard current input"
    state["ops_ledger_account-a-other"] = b"keep another exact context"
    ui.clear_review()
    assert not old_keys.intersection(state)
    assert state["_ops_review_account-a"]["files"] == {}
    assert state["_ops_review_account-a"]["settings"] == {}
    assert state["_ops_review_account-a"]["token"] != token
    assert ui._open_key("ops_review_zip") not in old_keys
    assert state["_ops_review_account-b"] == RECOVERY
    assert state["_account_flow"] == {"keep": "analysis"}
    assert state["ops_docs_account-a"] == b"keep originals"
    assert state["ops_catalogue_account-a"] == b"keep catalogue"
    assert state["_execution_proposal"] == {"keep": True}
    assert state["ops_ledger_account-a-other"] == b"keep another exact context"


@pytest.mark.parametrize("ledger", [LEDGER, b"invalid ledger"])
def test_new_review_clears_valid_or_rejected_inputs_and_stays_empty_after_reruns(ledger):
    app = review_screen({**RECOVERY, "files": {"ledger": ledger, "nav": NAV}})
    assert not app.exception
    token_key = next(k for k in app.session_state.filtered_state if k.startswith("_ops_review_"))
    prior_token = app.session_state[token_key]["token"]
    if ledger == LEDGER:
        flow = next(c for c in app.checkbox if c.label.startswith("Concilié todos los flujos"))
        flow.check().run()
        assert app.metric
    app.button(key=next(b.key for b in app.button if b.label == "Vaciar movimientos y empezar")).click().run()
    assert not app.exception and not app.error and not app.metric and not app.date_input
    assert app.session_state[token_key]["token"] != prior_token
    assert app.session_state[token_key]["files"] == {} and app.session_state[token_key]["settings"] == {}
    assert any("Revisión de movimientos vacía" in item.value for item in app.success)
    assert not any("Revisión recuperada" in item.value for item in app.info)
    app.run()
    assert not app.metric and not app.date_input
    assert app.session_state[token_key]["files"] == {}


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


@pytest.mark.parametrize("base", ["MXN", "USD"])
def test_recovered_inputs_restore_date_currency_and_calendar_without_approval(base):
    app = screen(
        'st.session_state.setdefault("flows_confirmation_temporary",True)\n'
        f'st.session_state["_ops_review_temporary"]["settings"]["base"]={base!r}'
    )
    assert not app.error and not app.exception and not app.metric
    assert app.date_input[0].value.isoformat() == "2026-01-10"
    assert app.selectbox[0].value == base
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
    assert not app.exception and app.error
    assert not any(button.key == "ops_review_open_temporary" for button in app.button)
    assert app.session_state["_ops_review_temporary"]["token"] == "seed"
    assert app.session_state["_ops_last_book_temporary"]["book"]["cash"]["MXN"] == 150


@pytest.mark.parametrize("manual", [False, True])
def test_valid_package_preview_keeps_current_inputs_and_consent_until_explicit_replacement(manual):
    app = AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_review import build_operations_review
from operations_review_ui import open_review
st.session_state.setdefault("_ops_review_temporary", {{}} if {manual!r} else {RECOVERY!r})
st.session_state.setdefault("raw_confirmation_temporary_seed",True)
if not st.session_state.get("_preview_initialized"):
    st.session_state["_ops_last_book_temporary"]={{"unchanged":True}}
    st.session_state["_preview_initialized"]=True
if {manual!r}:
    st.session_state.setdefault("ops_ledger_temporary",BytesIO({LEDGER!r}))
currency=st.selectbox("Paquete de prueba",["USD","MXN"])
_,bundle=build_operations_review({{"ledger":{LEDGER!r}}},cutoff="2026-01-09",base=currency)
with patch.object(st,"file_uploader",return_value=BytesIO(bundle)):
    open_review((None,None,None,None))
''', default_timeout=40).run()
    assert not app.error and not app.exception
    assert app.button(key="ops_review_open_temporary").label == "Reemplazar revisión con este paquete"
    assert any("Moneda: USD" in item.value and "2026-01-09" in item.value for item in app.text)
    assert app.session_state["_ops_last_book_temporary"] == {"unchanged": True}
    if not manual:
        assert app.session_state["_ops_review_temporary"]["files"] == RECOVERY["files"]
    app.selectbox[0].select("MXN").run()
    assert not app.error and not app.exception
    assert any("Moneda: MXN" in item.value for item in app.text)
    assert app.session_state["raw_confirmation_temporary_seed"] is True
    assert app.session_state["_ops_last_book_temporary"] == {"unchanged": True}
    if not manual:
        assert app.session_state["_ops_review_temporary"]["token"] == "seed"
    app.button(key="ops_review_open_temporary").click().run()
    assert not app.error and not app.exception
    opened = app.session_state["_ops_review_temporary"]
    assert opened["settings"] == {"cutoff": "2026-01-09", "base": "MXN"}
    assert opened["files"] == {"ledger": LEDGER}
    assert "_ops_last_book_temporary" not in app.session_state


@pytest.mark.parametrize("nav", [NAV, b"Fecha,NAV\n2026-01-01,100\n2026-01-10,150\n"])
def test_save_shortcut_opens_download_without_confirming_even_an_incomplete_review(nav):
    recovery = {**RECOVERY, "files": {"ledger": LEDGER, "nav": nav}}
    app = review_screen(recovery)
    assert not app.error and not app.exception and not app.metric
    button = next(b for b in app.button if b.label == "Guardar para continuar después")
    button.click().run()
    assert not app.error and not app.exception and not app.metric
    assert all(not item.value for item in app.checkbox)
    assert any(e.label == "Guardar revisión de movimientos" and e.proto.expanded for e in app.expander)
    assert any("el TXT sólo resume" in c.value for c in app.caption)


@pytest.mark.parametrize("files", [{}, {"ledger": LEDGER, "nav": b"Fecha,NAV\ninvalid,100\n"}])
def test_missing_or_rejected_input_cannot_offer_a_stale_save_shortcut(files):
    app = review_screen(RECOVERY)
    assert any(b.label == "Guardar para continuar después" for b in app.button)
    key = next(k for k in app.session_state.filtered_state if k.startswith("_ops_review_"))
    app.session_state[key]["files"] = files
    app.run()
    assert not app.exception
    assert not any(b.label == "Guardar para continuar después" for b in app.button)
    assert not app.metric


def review_screen(recovery):
    return AppTest.from_string(f'''
from hashlib import sha256
from unittest.mock import patch
import streamlit as st
import operations_ui as ui
context_key=sha256(str((None,None,None)).encode()).hexdigest()[:16]
st.session_state.setdefault("_ops_review_"+context_key, {recovery!r})
with patch.object(st,"file_uploader",return_value=None), \
     patch.object(ui,"_context",return_value=(None,None,None,None)), \
     patch.object(ui,"_implementation"), patch.object(ui,"_feeds"), \
     patch.object(ui,"_wealth"), patch.object(ui,"_documents"):
    ui.render_account_operations()
''', default_timeout=40).run()
