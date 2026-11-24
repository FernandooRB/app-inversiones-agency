"""Recovery describes what was saved without mutating the active financial review."""

from streamlit.testing.v1 import AppTest

from gbm_movement_review import read_movement_documents
from operations_recovery import movements_inventory
from operations_review import build_operations_review, read_operations_review
from scripts.gbm_review_fixture import fictional_statement


def test_draft_inventory_says_no_book_and_originals_must_be_reattached():
    draft = read_movement_documents([fictional_statement()])
    _, raw = build_operations_review({}, cutoff="2026-01-30", base="MXN", draft=draft)
    manifest, files = read_operations_review(raw)
    info = movements_inventory(manifest, files)
    assert info["stage"] == "Borrador sin libro"
    assert info["csv_count"] == 0 and info["originals_required"]
    assert {r["Contenido"]: r["Guardado"] for r in info["contents"]}["Libro de movimientos"] == "No incluido"


def test_proposal_without_book_has_its_own_next_step():
    from test_operations_proposal_portability import execution

    from operations_proposal import portable_proposal

    _, raw = build_operations_review(
        {}, cutoff="2026-01-30", base="MXN", proposal=portable_proposal(execution())
    )
    manifest, files = read_operations_review(raw)
    assert movements_inventory(manifest, files)["stage"] == "Propuesta sin libro"
    app = recovery_screen(raw)
    assert not app.exception
    assert any("Implementación" in c.value for c in app.caption)
    assert not any("completa la revisión del borrador" in c.value for c in app.caption)


def recovery_screen(raw):
    return AppTest.from_string(
        f"""
import streamlit as st
from io import BytesIO
from unittest.mock import patch
from operations_review_ui import open_review
st.session_state.setdefault("_ops_review_temporary", {{"token":"keep", "files":{{"ledger":b"keep"}}}})
st.session_state.setdefault("raw_confirmation_temporary_keep", True)
with patch.object(st,"file_uploader",return_value=BytesIO({raw!r})):
    open_review((None,None,None,None))
""",
        default_timeout=35,
    ).run()


def test_recovery_preview_inventory_and_guide_are_present_without_replacing_inputs():
    _, raw = build_operations_review({"ledger": b"fictitious"}, cutoff="2026-01-10", base="MXN")
    app = recovery_screen(raw)
    assert not app.error and not app.exception
    assert any("Libro incluido" in item.value for item in app.info)
    assert app.table
    assert any(
        item.proto.label == "Descargar guía de copias personales" for item in app.get("download_button")
    )
    assert app.session_state["_ops_review_temporary"]["files"] == {"ledger": b"keep"}
    assert app.session_state["raw_confirmation_temporary_keep"] is True
    assert any("PDF y TXT" in c.value for c in app.caption)


def test_draft_ui_preserves_pending_originals_and_rejected_zip_keeps_current_work():
    draft = read_movement_documents([fictional_statement()])
    _, raw = build_operations_review({}, cutoff="2026-01-30", base="MXN", draft=draft)
    app = recovery_screen(raw)
    assert not app.exception
    assert any("Borrador sin libro" in item.value for item in app.info)
    assert any("adjuntar" in item.value and "originales" in item.value for item in app.warning)
    rejected = recovery_screen(b"corrupt fictional ZIP")
    assert not rejected.exception and rejected.error
    assert rejected.session_state["_ops_review_temporary"]["files"] == {"ledger": b"keep"}
