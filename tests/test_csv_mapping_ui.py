"""Candidate editing must not change an active book until explicit replacement."""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from test_csv_mapping_portable import proposal

import operations_review_ui as review_ui


def test_csv_replacement_clears_only_this_account_and_renews_consent(monkeypatch):
    origin, ledger = proposal()
    origin["scope"] = {"case_id": "c", "account_id": "a"}
    state = {
        "_ops_context_key": "a",
        "_ops_review_a": {"token": "old", "files": {"nav": b"old"}},
        "_ops_review_b": {"files": {"ledger": b"other"}},
        "_account_flow": {"keep": True},
        "_ops_last_book_a": {"stale": True},
        "_ops_status_a": {"stale": True},
    }
    monkeypatch.setattr(review_ui, "st", SimpleNamespace(session_state=state))
    assert hasattr(review_ui, "set_csv_import"), "Missing CSV replacement"
    review_ui.set_csv_import(origin, ledger=ledger, cutoff=date(2026, 1, 10), base="MXN")
    current = state["_ops_review_a"]
    assert current["files"] == {"ledger": ledger} and current["token"] != "old"
    assert current["csv_import"]["applied_ledger_sha256"]
    assert "_ops_last_book_a" not in state and "_ops_status_a" not in state
    assert state["_ops_review_b"]["files"] == {"ledger": b"other"} and state["_account_flow"] == {
        "keep": True
    }


def test_clear_review_removes_csv_source_preview_and_package_for_only_the_active_account(monkeypatch):
    memo_names = ("csv_source", "csv_preview", "operations_zip")
    state = {"_ops_context_key": "a", "_csv_working_a": {"source": b"synthetic-A"}}
    for name in memo_names:
        state[f"_analysis_memo_{name}_a"] = {"data": b"synthetic-A"}
        state[f"_analysis_memo_{name}_b"] = {"data": b"synthetic-B"}
    monkeypatch.setattr(review_ui, "st", SimpleNamespace(session_state=state))
    review_ui.clear_review()
    assert "_csv_working_a" not in state
    for name in memo_names:
        assert f"_analysis_memo_{name}_a" not in state
        assert state[f"_analysis_memo_{name}_b"] == {"data": b"synthetic-B"}


def test_completing_nav_preserves_pending_csv_edits(monkeypatch):
    import csv_mapping_ui as ui

    state = {"_ops_context_key": "a", "_ops_review_a": {"token": "first", "files": {}}}
    streamlit = SimpleNamespace(session_state=state)
    monkeypatch.setattr(review_ui, "st", streamlit)
    monkeypatch.setattr(ui, "st", streamlit)
    _, candidate = ui._working()
    candidate["source"] = b"fictional.csv"
    review_ui.save_review_input("nav", b"fictional valuations")
    assert ui._working()[1]["source"] == b"fictional.csv"
    assert state["_ops_review_a"]["token"] != "first"


def test_old_mapped_book_with_net_amount_reopens_as_source_pending_financial_review():
    from hashlib import sha256

    from test_csv_mapping import RAW, mapping

    from csv_mapping import preview
    from operations_review import build_operations_review, read_operations_review

    raw = RAW.replace(b",2,10,20,0.2", b",2,10,20.01,0.01")
    config = mapping()
    historical = preview(raw, config, {})["normalized_candidate"]
    origin, _ = proposal()
    origin.update(source=raw, mapping=config, applied_ledger_sha256=sha256(historical).hexdigest())
    _, package = build_operations_review(
        {"ledger": historical}, cutoff="2026-01-10", base="MXN", csv_import=origin
    )
    manifest, files = read_operations_review(package)
    assert files["ledger"] == historical
    active_files, restored_origin, pending = review_ui._restore_csv_book(manifest, files)
    assert pending and "ledger" not in active_files
    assert restored_origin["source"] == raw and restored_origin["applied_ledger_sha256"] is None
    assert files["ledger"] == historical


def screen():
    app = AppTest.from_string("""
import streamlit as st
from csv_mapping_ui import render_csv_mapping
render_csv_mapping(None)
""")
    return app.run(timeout=30)


def test_closed_panel_does_no_parsing_or_financial_work(monkeypatch):
    import csv_mapping_ui

    monkeypatch.setattr(csv_mapping_ui, "preview", lambda *a: pytest.fail("closed panel computed"))
    app = screen()
    assert not app.exception
    assert any(e.label == "Preparar desde CSV con otras columnas" for e in app.expander)


def test_restored_draft_is_candidate_and_save_is_explicit():
    origin, _ = proposal()
    app = AppTest.from_string("""
import streamlit as st
from csv_mapping_ui import render_csv_mapping
render_csv_mapping(None)
""")
    app.session_state["_ops_review_temporary"] = {
        "token": "seed",
        "files": {"ledger": b"old"},
        "csv_import": origin,
    }
    app.session_state["csv_mapping_panel_temporary_seed"] = True
    app.run(timeout=30)
    assert not app.exception
    assert app.session_state["_ops_review_temporary"]["files"]["ledger"] == b"old"
    use = next(b for b in app.button if b.label == "Usar movimientos del CSV")
    assert use.disabled
    next(c for c in app.checkbox if c.label.startswith("Revisé cuenta")).check().run(timeout=30)
    next(b for b in app.button if b.label == "Usar movimientos del CSV").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["_ops_review_temporary"]["files"]["ledger"] != b"old"
    assert not next(c for c in app.checkbox if c.label.startswith("Revisé cuenta")).value


def test_decision_callback_reads_current_values_not_render_time(monkeypatch):
    import csv_mapping_ui as ui

    state = {
        "working": {"decisions": {}},
        "row": 2,
        "action": "exclude",
        "reason": "Cotejado",
        "source": "Comprobante ficticio",
    }
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    assert hasattr(ui, "_save_decision"), "Missing live decision callback"
    ui._save_decision("working", {"row": "row", "action": "action", "reason": "reason", "source": "source"})
    assert state["working"]["decisions"]["2"] == {
        "action": "exclude",
        "reason": "Cotejado",
        "source": "Comprobante ficticio",
    }
    before = deepcopy(state["working"]["decisions"])
    state["reason"] = ""
    ui._save_decision("working", {"row": "row", "action": "action", "reason": "reason", "source": "source"})
    assert state["working"]["decisions"] == before and state["working"].get("decision_error")
