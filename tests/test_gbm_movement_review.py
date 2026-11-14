"""Fictional end-to-end evidence, continuity, tampering and independently specified money checks."""

import json
from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from test_gbm_intake import _gbm_cash_pdf, _gbm_quantity_pdf, _gbm_reporto_pdf

from gbm_documents import read_statement
from gbm_movement_review import (
    add_manual_row,
    correct_row,
    draft_issues,
    make_draft,
    materialize_draft,
    original_rows_match,
    read_movement_documents,
    validate_draft,
)
from operations_input_forms import upsert_input
from operations_report import explain_performance, performance_pdf
from operations_review import build_operations_review, read_operations_review
from portfolio_core import PortfolioError
from realized_performance import Flow, performance
from transaction_ledger import Event, book_at, read_ledger


def cash_detail(raw, closing):
    extra = BytesIO()
    page = canvas.Canvas(extra)
    page.drawString(30, 750, f"TOTAL EFECTIVO {closing} {closing}")
    page.save()
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(raw)))
    writer.append(PdfReader(BytesIO(extra.getvalue())))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def cash_pdf(**kwargs):
    return cash_detail(
        _gbm_cash_pdf(
            closing=Decimal("150"),
            movement_rows=["05/05 1 DEPOSITO EFECTIVO 0.00 0.00 0.00 50.00 150.00"],
            **kwargs,
        ),
        "150.00",
    )


def ready_draft(raw=None):
    draft = read_movement_documents([raw or cash_pdf()])
    row = draft["rows"][1]
    proposal = {**row["proposal"], "Tipo": "DEPOSIT", "MomentoFlujo": "EOD"}
    return correct_row(
        draft, row["id"], proposal, reason="Aportación revisada", source="Comprobante ficticio"
    )


def test_duplicate_pdf_is_idempotent_and_opening_is_unique():
    raw = cash_pdf()
    draft = read_movement_documents([raw, raw])
    assert len(draft["documents"]) == 1 and len(draft["rows"]) == 2
    assert draft["rows"][1]["proposal"]["MomentoFlujo"] == "UNKNOWN"
    assert draft_issues(draft)  # A deposit description does not establish the transfer counterparty.


def test_unknown_movement_survives_without_inventing_amount_or_direction():
    raw = cash_detail(
        _gbm_cash_pdf(movement_rows=["05/05 1 MOVIMIENTO RESERVADO 0.00 0.00 0.00 10.00 110.00"]), "110.00"
    )
    with pytest.raises(ValueError):
        read_statement(raw)
    draft = read_movement_documents([raw])
    assert draft["rows"][1]["proposal"]["Tipo"] == ""
    assert draft_issues(draft)
    assert "MOVIMIENTO RESERVADO" in draft["rows"][1]["text"]


def test_correction_keeps_source_and_records_before_after_and_reason():
    raw = cash_pdf()
    draft = ready_draft(raw)
    row = draft["rows"][1]
    assert row["suggested"]["Tipo"] == "TRANSFER_IN" and row["proposal"]["Tipo"] == "DEPOSIT"
    assert row["changes"][0]["before"] == row["suggested"]
    assert row["changes"][0]["after"] == row["proposal"]
    assert original_rows_match(draft, [raw])
    assert not original_rows_match(draft, [raw + b"\n"])
    with pytest.raises(PortfolioError, match="motivo"):
        correct_row(draft, row["id"], row["proposal"], reason="", source="source")


def test_reviewed_deposit_produces_fifty_cash_and_zero_profit():
    draft = ready_draft()
    assert not draft_issues(draft)
    events = read_ledger(materialize_draft(draft))
    assert book_at(events, date(2026, 1, 30))["cash"]["MXN"] == 150
    nav = pd.Series([100, 150, 150], index=pd.to_datetime(["2025-12-31", "2026-01-05", "2026-01-30"]))
    flows = [Flow(date(2026, 1, 5), 50, "EOD")]
    result = performance(nav, flows)
    explained = explain_performance(events, nav, result, flows, base="MXN")
    assert explained["gain"] == 0 and explained["twr"] == 0
    assert explained["contributions"] == 50 and explained["withdrawals"] == 0


def test_adjacent_states_use_one_opening_and_next_opening_as_control():
    first = read_statement(cash_pdf(), movement_review=True)
    second = deepcopy(first)
    second.update(
        sha256="b" * 64,
        start=first["end"],
        end="2026-02-27",
        opening_cash="150",
        opening_total="150",
        closing_total="150",
        cash="150",
    )
    second["cash_review"] = [dict(first["cash_review"][0], ID="c" * 64)]
    draft = make_draft([second, first])
    assert sum(row["control"] for row in draft["rows"]) == 1
    assert sum(row["proposal"]["Tipo"] == "OPEN_CASH" and not row["control"] for row in draft["rows"]) == 1
    second["start"] = "2026-02-01"
    assert any("discontinuos" in i["reason"] for i in draft_issues(make_draft([first, second])))
    second["contract"] = "ANOTHER-FICTIONAL"
    with pytest.raises(PortfolioError, match="contratos"):
        make_draft([first, second])


def test_forged_source_row_or_omitted_row_does_not_match_reattached_original():
    raw = cash_pdf()
    draft = read_movement_documents([raw])
    assert original_rows_match(draft, [raw])
    forged = deepcopy(draft)
    forged["rows"].pop()
    assert not original_rows_match(forged, [raw])
    with pytest.raises(PortfolioError):
        forged["rows"][0]["text"] = "changed source"
        validate_draft(forged)


def test_v2_preserves_partial_draft_without_ledger_and_v1_still_reads():
    draft = read_movement_documents([cash_pdf()])
    manifest, raw = build_operations_review({}, cutoff="2026-01-30", base="MXN", draft=draft)
    recovered, files = read_operations_review(raw)
    assert manifest["schema"] == 2 and files == {} and recovered["draft_data"] == draft
    assert recovered["review_state"] == "PENDING_REVIEW"
    with ZipFile(BytesIO(raw)) as archive:
        assert set(archive.namelist()) == {"review.json", "draft/gbm.json"}
    _, legacy = build_operations_review(
        {"ledger": materialize_draft(ready_draft())}, cutoff="2026-01-30", base="MXN"
    )
    assert read_operations_review(legacy)[0]["schema"] == 1


def test_altered_draft_and_unknown_fields_are_rejected():
    draft = ready_draft()
    _, raw = build_operations_review({}, cutoff="2026-01-30", base="MXN", draft=draft)
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            target.writestr(name, content + b" " if name == "draft/gbm.json" else content)
    with pytest.raises(PortfolioError):
        read_operations_review(output.getvalue())
    draft["confirmations"] = {"approved": True}
    with pytest.raises(PortfolioError):
        validate_draft(draft)


def test_equity_trade_uses_gross_and_charges_without_double_counting():
    raw = _gbm_quantity_pdf(
        trade_commission=Decimal("1"), trade_tax=Decimal("0.16"), closing_cash=Decimal("58.84")
    )
    draft = read_movement_documents([raw])
    events = read_ledger(materialize_draft(draft))
    assert events[1].kind == "BUY" and events[1].amount == 40
    assert book_at(events, date(2026, 1, 30))["cash"]["MXN"] == Decimal("58.84")


def test_reporto_reference_is_not_inferred_from_a_folio():
    # The fixture's printed price already includes interest; test a documented zero-interest pair.
    draft = read_movement_documents([cash_detail(_gbm_reporto_pdf(maturity_interest=Decimal("0")), "99.99")])
    assert {row["proposal"]["Tipo"] for row in draft["rows"]} >= {"REPO_START", "REPO_MATURITY"}
    assert draft_issues(draft)
    for row in list(draft["rows"]):
        if row["proposal"]["Tipo"].startswith("REPO_"):
            draft = correct_row(
                draft,
                row["id"],
                {**row["proposal"], "Referencia": "repo-ficticio"},
                reason="Pareja documentada",
                source="Comprobante ficticio",
            )
    events = read_ledger(materialize_draft(draft))
    assert book_at(events, date(2026, 1, 30))["cash"]["MXN"] == Decimal("99.99")


def test_cent_difference_survives_and_never_changes_imported_cash():
    raw = cash_detail(
        _gbm_cash_pdf(
            closing=Decimal("150.01"), movement_rows=["05/05 1 DEPOSITO EFECTIVO 0.00 0.00 0.00 50.00 150.01"]
        ),
        "150.01",
    )
    draft = read_movement_documents([raw])
    row = draft["rows"][1]
    draft = correct_row(
        draft, row["id"], {**row["proposal"], "Tipo": "DEPOSIT"}, reason="Revisión", source="Ficticia"
    )
    assert book_at(read_ledger(materialize_draft(draft)), date(2026, 1, 30))["cash"]["MXN"] == 150
    assert draft["documents"][0]["cash"] == "150.01"


def test_form_upsert_keeps_other_dates_and_requires_source():
    raw = b"Fecha,NAV\n2026-01-01,100\n2026-01-30,150\n"
    entry = {"Fecha": "2026-01-05", "NAV": "150", "Fuente": "Estado ficticio, p2"}
    updated = upsert_input("nav", raw, entry)
    assert b"2026-01-01,100" in updated and b"2026-01-30,150" in updated
    assert updated.count(b"2026-01-05") == 1
    assert upsert_input("nav", updated, entry).count(b"2026-01-05") == 1
    with pytest.raises(PortfolioError, match="fuente"):
        upsert_input("nav", raw, {**entry, "Fuente": ""})


def test_unknown_timing_keeps_twr_pending_but_does_not_zero_xirr():
    nav = pd.Series([100, 150, 150], index=pd.to_datetime(["2025-12-31", "2026-01-05", "2026-01-30"]))
    flows = [Flow(date(2026, 1, 5), 50)]
    summary = explain_performance([], nav, performance(nav, flows), flows, base="MXN")
    assert summary["twr"] is None and summary["xirr"] == pytest.approx(0, abs=1e-8)


def test_income_charges_and_unattributed_variation_reproduce_gain():
    day = date(2026, 1, 5)
    events = [Event("d", day, day, "DIVIDEND", amount=10, tax=1), Event("f", day, day, "FEE", amount=2)]
    nav = pd.Series([100, 112], index=pd.to_datetime(["2026-01-01", "2026-01-30"]))
    summary = explain_performance(events, nav, performance(nav, []), [], base="MXN")
    assert summary["income"] == 10 and summary["tax"] == 1 and summary["fees"] == 2
    assert summary["unexplained"] == 5
    assert summary["income"] - summary["tax"] - summary["fees"] + summary["unexplained"] == summary["gain"]


def test_pdf_contains_same_figures_and_is_two_pages_with_bounded_long_pending_text():
    summary = explain_performance([], None, None, [], base="MXN")
    snapshot = {
        "performance_summary": summary,
        "scope": "Cuenta ficticia <script>",
        "issues": [{"title": "Pendiente " + "largo " * 30, "reason": "dato " * 200}] * 30,
        "inputs": {},
        "base": "MXN",
    }
    raw = performance_pdf(snapshot)
    reader = PdfReader(BytesIO(raw))
    assert len(reader.pages) == 2
    assert "Pendiente" in reader.pages[0].extract_text()
    assert "Otros 22 pendientes" in reader.pages[1].extract_text()
    assert b"<script>" not in raw
    json.dumps(snapshot, allow_nan=False)


def test_source_period_and_opening_cannot_be_reclassified_as_later_flows():
    draft = ready_draft()
    row = draft["rows"][1]
    changed = correct_row(
        draft,
        row["id"],
        {**row["proposal"], "Fecha": "2026-02-01", "Liquidacion": "2026-02-01"},
        reason="Revisión pendiente",
        source="Ficticia",
    )
    assert draft_issues(changed)
    opening = draft["rows"][0]
    changed = correct_row(
        draft,
        opening["id"],
        {**opening["proposal"], "Tipo": "DEPOSIT"},
        reason="No confirmado",
        source="Ficticia",
    )
    assert draft_issues(changed)


def test_unsupported_trade_interest_stays_unclassified():
    draft = read_movement_documents([_gbm_quantity_pdf(trade_interest=Decimal("1"))])
    assert draft_issues(draft)
    assert not draft["rows"][1]["proposal"]["Tipo"]


def test_explicit_withdrawal_reduces_nav_without_creating_loss():
    nav = pd.Series([100, 80, 80], index=pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-30"]))
    flows = [Flow(date(2026, 1, 5), -20, "EOD")]
    summary = explain_performance([], nav, performance(nav, flows), flows, base="MXN")
    assert summary["withdrawals"] == 20 and summary["contributions"] == 0
    assert summary["gain"] == 0 and summary["twr"] == 0


def test_foreign_income_does_not_claim_an_undocumented_conversion():
    nav = pd.Series([100, 110], index=pd.to_datetime(["2026-01-01", "2026-01-30"]))
    day = date(2026, 1, 5)
    summary = explain_performance(
        [Event("income", day, day, "DIVIDEND", currency="USD", amount=10)],
        nav,
        performance(nav, []),
        [],
        base="MXN",
    )
    assert summary["gain"] == 10 and summary["income"] is None and summary["unexplained"] is None


def test_spreadsheet_formula_identifier_is_not_exported_to_ledger():
    draft = ready_draft()
    row = draft["rows"][1]
    draft = correct_row(
        draft,
        row["id"],
        {**row["proposal"], "Referencia": "=UNTRUSTED()"},
        reason="Dato no confiable",
        source="Ficticia",
    )
    assert draft_issues(draft)


def test_documented_manual_opening_position_preserves_source_coverage():
    raw = cash_pdf()
    draft = ready_draft(raw)
    opening = {
        **draft["rows"][0]["proposal"],
        "Tipo": "OPEN_POSITION",
        "Instrumento": "SIM-MANUAL",
        "Cantidad": "2",
        "Importe": "0",
    }
    draft = add_manual_row(
        draft, opening, reason="Posición inicial documentada", source="Comprobante ficticio de apertura"
    )
    assert original_rows_match(draft, [raw]) and draft["rows"][-1]["manual"]
    positions = book_at(read_ledger(materialize_draft(draft)), date(2026, 1, 30))["positions"]
    assert positions[("SIM-MANUAL", "MXN")] == 2
    duplicate = add_manual_row(draft, opening, reason="Duplicado por revisar", source="Ficticia")
    with pytest.raises(PortfolioError, match="duplicadas"):
        materialize_draft(duplicate)


def test_v2_keeps_full_summary_as_bounded_evidence_without_restoring_it_as_approval():
    summary = b"Borrador. Diferencia -0.01 MXN. Confirmaciones pendientes."
    _, raw = build_operations_review(
        {}, cutoff="2026-01-30", base="MXN", draft=ready_draft(), summary=summary
    )
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.read("evidence/review.txt") == summary
    manifest, _ = read_operations_review(raw)
    assert manifest["review_state"] == "PENDING_REVIEW" and "returns" not in manifest


def test_use_reviewed_draft_inside_rendered_tabs_does_not_mutate_instantiated_tab_widget():
    from streamlit.testing.v1 import AppTest

    raw = cash_pdf()
    draft = ready_draft(raw)
    app = AppTest.from_string(
        f"""
from io import BytesIO
from hashlib import sha256
from unittest.mock import patch
import streamlit as st
from operations_ui import render_account_operations
key=sha256(str((None,None,None)).encode()).hexdigest()[:16]
st.session_state.setdefault("_ops_review_"+key, {{"token":"test-source", "files":{{}}, "draft":{draft!r}}})
st.session_state.setdefault("_gbm_attached_"+key, [BytesIO({raw!r})])
with patch("operations_ui._context",return_value=(None,None,None,None)):
    render_account_operations()
""",
        default_timeout=40,
    ).run()
    confirmation = next(item for item in app.checkbox if item.label.startswith("Cotejé cuenta"))
    confirmation.check().run()
    next(item for item in app.button if item.label == "Usar movimientos revisados").click().run()
    assert not app.error and not app.exception
    assert any(item.value == "Recuperado: Libro de movimientos." for item in app.caption)
