"""Operational comparison must be explicit and isolated from the active book."""

from streamlit.testing.v1 import AppTest


def test_file_upload_is_only_offered_in_local_app():
    from operations_market_review_ui import _local_uploads

    assert _local_uploads("http://localhost:8501/")
    assert _local_uploads("http://127.0.0.1:8540/?demo=1")
    assert _local_uploads("http://[::1]:8501/")
    assert not _local_uploads("https://app-inversiones-agency.streamlit.app/")
    assert not _local_uploads("https://localhost.example.com/")
    assert not _local_uploads(None)


def test_practice_renders_only_after_request_and_never_updates_book():
    app = AppTest.from_string("""
import streamlit as st
from operations_ui import _feeds
st.session_state['_ops_context_key'] = 'account-a'
st.session_state.setdefault('_ops_review_account-a', {'files': {'ledger': b'fictional book'}})
_feeds((None, None, None, None))
""")
    app.session_state["market_panel_account-a"] = True
    app.run(timeout=30)
    assert not app.exception
    compare = next(b for b in app.button if b.label == "Cotejar observaciones")
    assert "_market_result_account-a" not in app.session_state
    compare.click().run(timeout=30)
    assert not app.exception
    result = app.session_state["_market_result_account-a"]["report"]
    assert result["counts"] == {"DIFERENCIA": 1, "NO_COMPARABLE": 2, "FALTA_REFERENCIA": 1, "DENTRO": 2}
    assert app.session_state["_ops_review_account-a"]["files"]["ledger"] == b"fictional book"
    next(w for w in app.number_input if w.label.startswith("Tipo de cambio")).set_value(25).run(timeout=30)
    assert "_market_result_account-a" not in app.session_state
    next(b for b in app.button if b.label == "Cotejar observaciones").click().run(timeout=30)
    assert "DIFERENCIA" not in app.session_state["_market_result_account-a"]["report"]["counts"]
    next(b for b in app.button if b.label == "Vaciar cotejo").click().run(timeout=30)
    assert "_market_result_account-a" not in app.session_state and not app.exception
