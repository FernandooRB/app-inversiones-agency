"""Structural tests use generated documents, never a real statement."""

import json
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from scripts.inspect_gbm_intake import (
    IntakeError,
    _money_values,
    _statement_summary,
    check_statement_detail_totals,
    check_statement_summaries,
    inspect_pdf,
    inspect_xml,
    scan_folder,
)


def _pdf(*, start="31-DIC-25", end="30-ENE-26", private_text="CLIENTE RESERVADO"):
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 750, f"ESTADO DE CUENTA {private_text}")
    page.drawString(30, 720, f"PERIODO {start} AL {end}")
    page.showPage()
    page.save()
    return stream.getvalue()


def _gbm_summary_pdf(
    *, contract="SYNTH12345", start="31-DIC-25", end="30-ENE-26",
    opening=Decimal("100.00"), closing=Decimal("110.00"),
    closing_categories=None, detailed=False, unknown_label=False, include_contract=True,
):
    labels = [
        "DEUDA", "RENTA VARIABLE", "VALORES EN CORTO / PRESTAMO DE VALORES",
        "FONDO DE FONDOS", "GARANTIAS", "OTRAS INVERSIONES",
        "CREDITOS DE MARGEN", "EFECTIVO",
    ]
    labels += (["DERIVADOS MERCADOS RECONOCIDOS", "DERIVADOS MERCADOS EXTRABURSATILES",
                "EFECTIVO MARGEN INICIAL Y VARIACION"] if detailed else ["DERIVADOS"])
    if unknown_label:
        labels[-1] = "CATEGORIA DESCONOCIDA"
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 800, "ESTADO DE CUENTA DE PERSONA FICTICIA")
    page.drawString(30, 780, f"PORTAFOLIO AL {start} AL {end}")
    for index, label in enumerate(labels):
        row_opening = opening if label == "EFECTIVO" else Decimal("0.00")
        row_closing = (
            closing if closing_categories is None else closing_categories
        ) if label == "EFECTIVO" else Decimal("0.00")
        page.drawString(30, 760 - 20 * index, f"{label}  {row_opening:.2f}  {row_closing:.2f}  0.00")
    page.drawString(30, 760 - 20 * len(labels), f"VALOR DEL PORTAFOLIO {opening:.2f} {closing:.2f} 100.00")
    if include_contract:
        page.drawString(30, 500, f"Titular: PERSONA FICTICIA Contrato: {contract} RFC: ABC010101AAA")
    page.showPage()
    page.save()
    return stream.getvalue()


def _gbm_detail_pdf(*, equity_cover=Decimal("100.00"), detail_total=Decimal("100.00"),
                    second_position=Decimal("60.00"), second_price=Decimal("20.0000"),
                    include_cash=True, incomplete_row=False):
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 800, "ESTADO DE CUENTA DE PERSONA FICTICIA")
    page.drawString(30, 780, "PORTAFOLIO AL 31-DIC-25 AL 30-ENE-26")
    labels = [
        "DEUDA", "RENTA VARIABLE", "VALORES EN CORTO", "FONDO DE FONDOS",
        "GARANTIAS", "OTRAS INVERSIONES", "CREDITOS DE MARGEN", "EFECTIVO", "DERIVADOS",
    ]
    for index, label in enumerate(labels):
        opening = Decimal("110.00") if label == "EFECTIVO" else Decimal("0.00")
        closing = equity_cover if label == "RENTA VARIABLE" else (
            Decimal("10.00") if label == "EFECTIVO" else Decimal("0.00")
        )
        page.drawString(30, 760 - 20 * index, f"{label} {opening:.2f} {closing:.2f} 0.00")
    page.drawString(30, 580, f"VALOR DEL PORTAFOLIO 110.00 {equity_cover + 10:.2f} 100.00")
    page.drawString(30, 540, "Titular: PERSONA FICTICIA Contrato: SYNTH12345 RFC: ABC010101AAA")
    page.showPage()
    detail = [
        "RENTA VARIABLE", "SIMBOLO_A 0 2 0 0 40.00 20.0000 19.0000 40.00 0.00 0.00",
        f"SIMBOLO_B 0 3 0 0 60.00 {second_price:.4f} 19.0000 {second_position:.2f} 0.00 0.00",
        f"TOTAL: ACCIONES {detail_total:.2f} 0.00 {detail_total:.2f}",
        f"TOTAL: RENTA VARIABLE {detail_total:.2f} 0.00 {detail_total:.2f}",
    ]
    if incomplete_row:
        detail.insert(2, "SIMBOLO_INCOMPLETO 1.00 0.00 0.00")
    if include_cash:
        detail.append("TOTAL EFECTIVO 10.00 10.00")
    for index, line in enumerate(detail):
        page.drawString(30, 750 - 20 * index, line)
    page.showPage()
    page.save()
    return stream.getvalue()


class _MemoryFile:
    suffix = ".pdf"

    def __init__(self, order, contents, parent="carpeta confidencial"):
        self.order = order
        self.contents = contents
        self.parent = parent

    def __lt__(self, other):
        return self.order < other.order

    def is_file(self):
        return True

    def is_symlink(self):
        return False

    def read_bytes(self):
        return self.contents

    def stat(self):
        return SimpleNamespace(st_size=len(self.contents))


class _MemoryFolder:
    def __init__(self, files):
        self.files = files

    def is_dir(self):
        return True

    def is_symlink(self):
        return False

    def rglob(self, _pattern):
        return self.files


def test_gbm_wrapper_is_stripped_and_period_detected():
    prefix = b"^{doc_title".ljust(105, b"X")
    result = inspect_pdf(prefix + _pdf())
    assert result == {
        "type": "statement_pdf", "period_start": "2025-12-31",
        "period_end": "2026-01-30", "pages": 1, "wrapper_bytes": 105,
    }


def test_rejects_unknown_pdf_wrapper_and_ambiguous_period():
    with pytest.raises(IntakeError, match="prefijo desconocido"):
        inspect_pdf(b"private-metadata" + _pdf())
    with pytest.raises(IntakeError, match="dos cortes"):
        inspect_pdf(_pdf(start="30-ENE-26", end="30-ENE-26"))


def test_rejects_xml_entities_and_does_not_return_taxpayer_fields():
    with pytest.raises(IntakeError, match="DTD"):
        inspect_xml(b'<!DOCTYPE c [<!ENTITY x "abc">]><Comprobante>&x;</Comprobante>')
    document = (
        b'<Comprobante xmlns="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        b'TipoDeComprobante="I" Moneda="MXN" Fecha="2026-04-03T10:20:30">'
        b'<Receptor Nombre="CLIENTE RESERVADO" Rfc="ABC010101AAA"/>'
        b'<Addenda><Movimientos>texto privado</Movimientos></Addenda></Comprobante>'
    )
    result = inspect_xml(document)
    assert result["issue_month"] == "2026-04"
    assert result["movement_addenda"] is True
    assert "CLIENTE" not in json.dumps(result)
    assert "ABC010101AAA" not in json.dumps(result)


def test_scan_deduplicates_and_never_prints_private_text():
    pdf = _pdf(private_text="NOMBRE CONFIDENCIAL 987654321")
    result = scan_folder(_MemoryFolder([_MemoryFile(1, pdf), _MemoryFile(2, pdf)]))
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["pdf_count"] == 1
    assert result["exact_duplicate_files"] == 1
    assert "NOMBRE" not in serialized
    assert "987654321" not in serialized
    assert "carpeta confidencial" not in serialized


def test_summary_checks_contiguous_cuts_and_never_returns_identifiers_or_amounts():
    january = b"^{doc_title".ljust(105, b"X") + _gbm_summary_pdf(
        closing_categories=Decimal("109.99"),
    )
    february = _gbm_summary_pdf(
        start="30-ENE-26", end="27-FEB-26", opening=Decimal("110.00"),
        closing=Decimal("120.00"), detailed=True,
    )
    result = check_statement_summaries(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, february),
    ]))
    checks = result["summary_checks"]
    assert result["cover_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert checks["contracts_detected"] == 1
    assert checks["documents_checked"] == 2
    assert checks["closing_one_cent"] == 1
    assert checks["adjacent_pairs"] == checks["continuity_exact"] == 1
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "109.99", "120.00"):
        assert secret not in serialized


def test_summary_rejects_unknown_layout_and_flags_material_discrepancy():
    with pytest.raises(IntakeError, match="diseño conocido"):
        _statement_summary(_gbm_summary_pdf(unknown_label=True))
    with pytest.raises(IntakeError, match="contrato único"):
        _statement_summary(_gbm_summary_pdf(include_contract=False))
    bad_total = _gbm_summary_pdf(closing_categories=Decimal("109.90"))
    result = check_statement_summaries(_MemoryFolder([_MemoryFile(1, bad_total)]))
    assert result["cover_status"] == "REVIEW_REQUIRED"
    assert result["summary_checks"]["closing_over_cent"] == 1


def test_summary_flags_nonadjacent_periods_for_same_contract():
    january = _gbm_summary_pdf()
    march = _gbm_summary_pdf(start="27-FEB-26", end="31-MAR-26", opening=Decimal("110.00"))
    result = check_statement_summaries(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, march),
    ]))
    assert result["cover_status"] == "REVIEW_REQUIRED"
    assert result["summary_checks"]["nonadjacent_periods"] == 1


def test_summary_flags_duplicate_cut_and_mixed_contract_folder():
    result = check_statement_summaries(_MemoryFolder([
        _MemoryFile(1, _gbm_summary_pdf(contract="SYNTH1")),
        _MemoryFile(2, _gbm_summary_pdf(contract="SYNTH1", closing=Decimal("111.00"))),
        _MemoryFile(3, _gbm_summary_pdf(contract="SYNTH2")),
    ]))
    assert result["cover_status"] == "REVIEW_REQUIRED"
    assert result["summary_checks"]["duplicate_contract_cuts"] == 1
    assert result["summary_checks"]["folders_with_multiple_contracts"] == 1


def test_summary_money_parser_preserves_sign_and_thousands():
    assert _money_values("DEUDA 1,234.56 (4.00) -10.01") == [
        Decimal("1234.56"), Decimal("-4.00"), Decimal("-10.01"),
    ]


def test_detail_totals_reconcile_equity_positions_and_cash_without_private_output():
    result = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf()),
    ]))
    assert result["detail_status"] == "EXACT"
    checks = result["detail_checks"]
    assert checks["details_checked"] == 1
    assert checks["equity_positions_checked"] == 2
    assert checks["equity_groups_exact"] == 1
    assert checks["cash_exact"] == checks["equity_exact"] == 1
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "SIMBOLO_A", "100.00"):
        assert secret not in serialized


def test_detail_totals_separate_cent_difference_from_position_error():
    cent = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(equity_cover=Decimal("99.99"))),
    ]))
    assert cent["detail_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert cent["detail_checks"]["equity_one_cent"] == 1
    mismatch = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(second_position=Decimal("59.90"))),
    ]))
    assert mismatch["detail_status"] == "REVIEW_REQUIRED"
    assert mismatch["detail_checks"]["detail_review_required"] == 1


def test_detail_totals_require_cash_total_even_when_positions_exist():
    result = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(include_cash=False)),
    ]))
    assert result["detail_status"] == "REVIEW_REQUIRED"
    assert result["detail_checks"]["detail_review_required"] == 1


def test_detail_totals_reject_price_quantity_mismatch_even_when_subtotals_match():
    result = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(second_price=Decimal("20.1000"))),
    ]))
    assert result["detail_status"] == "REVIEW_REQUIRED"
    assert result["detail_checks"]["detail_review_required"] == 1


def test_detail_totals_accept_cent_rounding_of_quantity_times_price():
    result = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(
            equity_cover=Decimal("100.01"), detail_total=Decimal("100.01"),
            second_position=Decimal("60.01"), second_price=Decimal("20.0033"),
        )),
    ]))
    assert result["detail_status"] == "EXACT"
    assert result["detail_checks"]["equity_quantity_price_rounded"] == 1


def test_detail_totals_reject_unrecognized_monetary_position_line():
    result = check_statement_detail_totals(_MemoryFolder([
        _MemoryFile(1, _gbm_detail_pdf(incomplete_row=True)),
    ]))
    assert result["detail_status"] == "REVIEW_REQUIRED"
    assert result["detail_checks"]["detail_review_required"] == 1
