"""Structural tests use generated documents, never a real statement."""

import json
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import pytest
from reportlab.pdfgen import canvas

from scripts.inspect_gbm_intake import (
    IntakeError,
    _cash_direction,
    _money_values,
    _statement_summary,
    check_cfdi_arithmetic,
    check_statement_cash_ledgers,
    check_statement_detail_totals,
    check_statement_equity_quantities,
    check_statement_equity_trade_costs,
    check_statement_movement_dates,
    check_statement_reporto_net,
    check_statement_reporto_pairs,
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
    closing_categories=None, opening_equity=Decimal("0.00"),
    closing_equity=Decimal("0.00"), detailed=False, unknown_label=False, include_contract=True,
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
        row_opening = (opening - opening_equity) if label == "EFECTIVO" else (
            opening_equity if label == "RENTA VARIABLE" else Decimal("0.00")
        )
        row_closing = (
            (closing - closing_equity) if closing_categories is None else closing_categories
        ) if label == "EFECTIVO" else (
            closing_equity if label == "RENTA VARIABLE" else Decimal("0.00")
        )
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


def _gbm_cash_pdf(*, opening=Decimal("100.00"), closing=Decimal("110.00"),
                  last_operation="COMPRA REPORTO",
                  include_opening=True, split_pages=False, start="31-DIC-25",
                  end="30-ENE-26", first_day="15/15", second_day="20/20",
                  movement_rows=None):
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 800, "ESTADO DE CUENTA DE PERSONA FICTICIA")
    page.drawString(30, 780, f"PORTAFOLIO AL {start} AL {end}")
    labels = [
        "DEUDA", "RENTA VARIABLE", "VALORES EN CORTO", "FONDO DE FONDOS",
        "GARANTIAS", "OTRAS INVERSIONES", "CREDITOS DE MARGEN", "EFECTIVO", "DERIVADOS",
    ]
    for index, label in enumerate(labels):
        row_opening = opening if label == "EFECTIVO" else Decimal("0.00")
        final = closing if label == "EFECTIVO" else Decimal("0.00")
        page.drawString(30, 760 - 20 * index, f"{label} {row_opening:.2f} {final:.2f} 0.00")
    page.drawString(30, 580, f"VALOR DEL PORTAFOLIO {opening:.2f} {closing:.2f} 100.00")
    page.drawString(30, 540, "Titular: PERSONA FICTICIA Contrato: SYNTH12345 RFC: ABC010101AAA")
    page.showPage()
    lines = ["MOVIMIENTOS DE OPERACIONES", "FECHA DESCRIPCION IMPORTE NETO SALDO"]
    if include_opening:
        lines.append(f"31/12 0 EFECTIVO INICIAL 0.00 0.00 0.00 {opening:.2f} {opening:.2f}")
    if movement_rows is None:
        movement_rows = [
            f"{first_day} 1 DEPOSITO EFECTIVO 0.00 0.00 0.00 20.00 120.00",
            f"{second_day} 2 {last_operation} 0.00 0.00 0.00 10.00 {closing:.2f}",
        ]
    lines += [*movement_rows, "MOVIMIENTOS DOCUMENTALES"]
    for index, line in enumerate(lines):
        y_index = index
        if split_pages and index == len(lines) - 2:
            page.showPage()
        if split_pages and index >= len(lines) - 2:
            y_index = index - (len(lines) - 2)
        page.drawString(30, 750 - 20 * y_index, line)
    page.showPage()
    page.save()
    return stream.getvalue()


def _gbm_quantity_pdf(
    *, start="31-DIC-25", end="30-ENE-26", opening_cash=Decimal("100.00"),
    opening_equity=Decimal("0.00"), closing_cash=Decimal("60.00"),
    closing_equity=Decimal("40.00"), opening_qty=Decimal("0"), closing_qty=Decimal("2"),
    trade_qty=Decimal("2"), symbol="SYMA", trade_symbol="SYMA",
    trade_action="COMPRA", trade_price=Decimal("20.0000"),
    trade_commission=Decimal("0.00"), trade_interest=Decimal("0.00"),
    trade_tax=Decimal("0.00"), trade_net_adjustment=Decimal("0.00"),
):
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 800, "ESTADO DE CUENTA DE PERSONA FICTICIA")
    page.drawString(30, 780, f"PORTAFOLIO AL {start} AL {end}")
    labels = [
        "DEUDA", "RENTA VARIABLE", "VALORES EN CORTO", "FONDO DE FONDOS",
        "GARANTIAS", "OTRAS INVERSIONES", "CREDITOS DE MARGEN", "EFECTIVO", "DERIVADOS",
    ]
    for index, label in enumerate(labels):
        opening = opening_equity if label == "RENTA VARIABLE" else (
            opening_cash if label == "EFECTIVO" else Decimal("0.00")
        )
        closing = closing_equity if label == "RENTA VARIABLE" else (
            closing_cash if label == "EFECTIVO" else Decimal("0.00")
        )
        page.drawString(30, 760 - 20 * index, f"{label} {opening:.2f} {closing:.2f} 0.00")
    page.drawString(
        30, 580,
        f"VALOR DEL PORTAFOLIO {opening_cash + opening_equity:.2f} "
        f"{closing_cash + closing_equity:.2f} 100.00",
    )
    page.drawString(30, 540, "Titular: PERSONA FICTICIA Contrato: SYNTH12345 RFC: ABC010101AAA")
    page.showPage()
    lines = []
    if closing_equity:
        lines += [
            "RENTA VARIABLE",
            f"{symbol} {opening_qty} {closing_qty} 0 0 {closing_equity:.2f} "
            f"20.0000 19.0000 {closing_equity:.2f} 0.00 0.00",
            f"TOTAL: ACCIONES {closing_equity:.2f} 0.00 {closing_equity:.2f}",
            f"TOTAL: RENTA VARIABLE {closing_equity:.2f} 0.00 {closing_equity:.2f}",
        ]
    lines += [
        f"TOTAL EFECTIVO {closing_cash:.2f} {closing_cash:.2f}",
        "MOVIMIENTOS DE OPERACIONES",
        f"01/01 0 EFECTIVO INICIAL 0.00 0.00 0.00 {opening_cash:.2f} {opening_cash:.2f}",
    ]
    if trade_qty:
        gross = trade_qty * trade_price
        sign = 1 if trade_action == "COMPRA" else -1
        net = gross + sign * (trade_commission + trade_tax) + trade_net_adjustment
        lines.append(
            f"10/10 1 {trade_action} {trade_symbol} {trade_qty} {trade_price:.4f} "
            f"{trade_commission:.2f} {trade_interest:.2f} {trade_tax:.2f} "
            f"{net:.2f} {closing_cash:.2f}"
        )
    lines.append("MOVIMIENTOS DOCUMENTALES")
    for index, line in enumerate(lines):
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


def _synthetic_cfdi(*, total="110.00", discount="10.00", transfer="20.00",
                    concept_transfer="20.00", concept_discount="10.00"):
    return (
        f'<Comprobante xmlns="http://www.sat.gob.mx/cfd/4" Version="4.0" '
        f'TipoDeComprobante="I" Moneda="MXN" Fecha="2026-04-03T10:20:30" '
        f'SubTotal="100.00" Descuento="{discount}" Total="{total}">'
        f'<Conceptos><Concepto Importe="100.00" Descuento="{concept_discount}">'
        f'<Impuestos><Traslados><Traslado Importe="{concept_transfer}"/>'
        f'</Traslados></Impuestos></Concepto></Conceptos>'
        f'<Impuestos TotalImpuestosTrasladados="{transfer}">'
        f'<Traslados><Traslado Importe="{transfer}"/></Traslados></Impuestos>'
        f'<Receptor Nombre="CLIENTE RESERVADO" Rfc="ABC010101AAA"/>'
        f'</Comprobante>'
    ).encode()


def _xml_folder(*documents):
    files = []
    for index, document in enumerate(documents):
        file = _MemoryFile(index, document)
        file.suffix = ".xml"
        files.append(file)
    return _MemoryFolder(files)


@pytest.mark.parametrize("original,replacement,error", [
    (b'Fecha="2026-04-03T10:20:30"', b'Fecha="2026-04-03T25:20:30"', "fecha u hora"),
    (b'Version="4.0"', b'Version="3.3"', "versión y el espacio"),
])
def test_cfdi_rejects_invalid_time_or_namespace_version(original, replacement, error):
    document = _synthetic_cfdi().replace(original, replacement)
    with pytest.raises(IntakeError, match=error):
        inspect_xml(document)
    result = check_cfdi_arithmetic(_xml_folder(document))
    assert result["cfdi_arithmetic_status"] == "REVIEW_REQUIRED"
    assert result["cfdi_checks"]["parse_failures"] == 1


def test_cfdi_accepts_matching_version_33_namespace():
    document = (_synthetic_cfdi().replace(b"/cfd/4", b"/cfd/3")
                .replace(b'Version="4.0"', b'Version="3.3"'))
    result = check_cfdi_arithmetic(_xml_folder(document))
    assert result["cfdi_arithmetic_status"] == "EXACT"


def test_cfdi_arithmetic_checks_equations_without_exporting_values():
    result = check_cfdi_arithmetic(_xml_folder(_synthetic_cfdi()))
    assert result["cfdi_arithmetic_status"] == "EXACT"
    assert result["cfdi_checks"]["documents_checked"] == 1
    assert result["cfdi_checks"]["total_exact"] == 1
    assert result["cfdi_checks"]["positive_total_documents"] == 1
    serialized = json.dumps(result)
    assert "CLIENTE RESERVADO" not in serialized
    assert "ABC010101AAA" not in serialized
    assert "110.00" not in serialized


@pytest.mark.parametrize("changes,expected", [
    ({"total": "110.01"}, "CENT_DIFFERENCES_NEED_REVIEW"),
    ({"total": "112.00"}, "REVIEW_REQUIRED"),
    ({"concept_transfer": "19.00"}, "REVIEW_REQUIRED"),
    ({"concept_discount": "9.00"}, "REVIEW_REQUIRED"),
])
def test_cfdi_arithmetic_requires_review_for_mismatches(changes, expected):
    result = check_cfdi_arithmetic(_xml_folder(_synthetic_cfdi(**changes)))
    assert result["cfdi_arithmetic_status"] == expected


def test_cfdi_arithmetic_distinguishes_zero_total_from_charged_cfdi():
    zero = _synthetic_cfdi(total="0.00", discount="100.00", transfer="0.00",
                           concept_transfer="0.00", concept_discount="100.00")
    result = check_cfdi_arithmetic(_xml_folder(zero, _synthetic_cfdi()))
    assert result["cfdi_arithmetic_status"] == "EXACT"
    assert result["cfdi_checks"]["zero_total_documents"] == 1
    assert result["cfdi_checks"]["positive_total_documents"] == 1


def test_cfdi_arithmetic_rejects_duplicate_and_unsafe_xml():
    document = _synthetic_cfdi()
    duplicated = check_cfdi_arithmetic(_xml_folder(document, document))
    assert duplicated["cfdi_arithmetic_status"] == "REVIEW_REQUIRED"
    assert duplicated["cfdi_checks"]["exact_duplicates"] == 1
    unsafe = check_cfdi_arithmetic(_xml_folder(b'<!DOCTYPE c [<!ENTITY x "private">]><Comprobante/>'))
    assert unsafe["cfdi_arithmetic_status"] == "REVIEW_REQUIRED"
    assert unsafe["cfdi_checks"]["parse_failures"] == 1
    with pytest.raises(IntakeError, match="codificación"):
        inspect_xml('<?xml version="1.0"?><!DOCTYPE c><Comprobante/>'.encode("utf-16"))


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
    assert checks["common_category_continuity_exact"] == 7
    assert checks["common_category_continuity_one_cent"] == 1
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


def test_summary_flags_category_shift_even_when_portfolio_total_is_continuous():
    january = _gbm_summary_pdf(closing=Decimal("110.00"), closing_equity=Decimal("10.00"))
    february = _gbm_summary_pdf(
        start="30-ENE-26", end="27-FEB-26", opening=Decimal("110.00"),
        closing=Decimal("120.00"),
    )
    result = check_statement_summaries(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, february),
    ]))
    assert result["cover_status"] == "REVIEW_REQUIRED"
    checks = result["summary_checks"]
    assert checks["continuity_exact"] == 1
    assert checks["common_category_continuity_over_cent"] == 2


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


def test_cash_ledger_reconciles_signed_movements_without_private_output():
    result = check_statement_cash_ledgers(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf()),
    ]))
    assert result["cash_status"] == "EXACT"
    checks = result["cash_checks"]
    assert checks["cash_ledgers_checked"] == 1
    assert checks["cash_rows_checked"] == 3
    assert checks["cash_transition_exact"] == 2
    assert checks["cash_credit_rows"] == checks["cash_debit_rows"] == 1
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "110.00"):
        assert secret not in serialized


def test_cash_ledger_tracks_running_balance_across_pdf_page_break():
    result = check_statement_cash_ledgers(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(split_pages=True)),
    ]))
    assert result["cash_status"] == "EXACT"
    assert result["cash_checks"]["cash_rows_checked"] == 3


def test_cash_ledger_flags_cent_rounding_and_wrong_operation_direction():
    cent = check_statement_cash_ledgers(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(closing=Decimal("110.01"))),
    ]))
    assert cent["cash_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert cent["cash_checks"]["cash_transition_one_cent"] == 1
    wrong_direction = check_statement_cash_ledgers(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(last_operation="VENTA")),
    ]))
    assert wrong_direction["cash_status"] == "REVIEW_REQUIRED"
    assert wrong_direction["cash_checks"]["cash_transition_over_cent"] == 1


def test_cash_ledger_requires_opening_row():
    result = check_statement_cash_ledgers(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(include_opening=False)),
    ]))
    assert result["cash_status"] == "REVIEW_REQUIRED"
    assert result["cash_checks"]["cash_review_required"] == 1


def test_cash_direction_distinguishes_dividend_credit_and_withholding():
    assert _cash_direction("15/01 2 PAGO DIVIDENDO") == 1
    assert _cash_direction("15/01 3 RETENCION ISR DIVIDENDO") == -1
    assert _cash_direction("15/01 4 DEPÓSITO EN EFECTIVO") == 1
    assert _cash_direction("15/01 5 RETENCIÓN DE DIVIDENDO") == -1
    with pytest.raises(IntakeError, match="no reconocible"):
        _cash_direction("15/01 6 OPERACION DESCONOCIDA")


def test_movement_days_resolve_repeated_day_by_order_without_private_output():
    ordinary = _gbm_cash_pdf(first_day="15/16", second_day="20/20")
    month_rollover = _gbm_cash_pdf(
        start="30-ENE-26", end="27-FEB-26", first_day="31/01", second_day="03/03",
    )
    long_cut = _gbm_cash_pdf(
        start="29-MAY-26", end="30-JUN-26", first_day="29/29", second_day="30/30",
    )
    result = check_statement_movement_dates(_MemoryFolder([
        _MemoryFile(1, ordinary), _MemoryFile(2, month_rollover), _MemoryFile(3, long_cut),
    ]))
    assert result["date_status"] == "STRUCTURALLY_PLAUSIBLE"
    checks = result["date_checks"]
    assert checks["date_documents_checked"] == 3
    assert checks["movement_rows_checked"] == 6
    assert checks["first_days_resolved_by_order"] == 1
    assert checks["observed_day_lag_1"] == 2
    assert checks["observed_day_lag_0"] == 4
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "110.00"):
        assert secret not in serialized


@pytest.mark.parametrize("first_day,second_day", [
    ("31/31", "20/20"),  # No first-day match inside the statement period.
    ("20/20", "15/15"),  # Printed rows go backwards.
    ("15/14", "20/20"),  # The second fragment is before the first.
    ("01/15", "20/20"),  # The second fragment exceeds the provisional lag.
])
def test_movement_days_require_plausible_order_and_second_fragment(first_day, second_day):
    result = check_statement_movement_dates(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(first_day=first_day, second_day=second_day)),
    ]))
    assert result["date_status"] == "REVIEW_REQUIRED"
    assert result["date_checks"]["date_review_required"] == 1


def test_movement_days_leave_unresolved_repeated_days_for_review():
    result = check_statement_movement_dates(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(
            start="29-MAY-26", end="30-JUN-26", first_day="30/30", second_day="30/30",
        )),
    ]))
    assert result["date_status"] == "REVIEW_REQUIRED"
    assert result["date_checks"]["date_review_required"] == 1


def test_equity_quantities_reconcile_trades_and_adjacent_cuts_without_private_output():
    january = _gbm_quantity_pdf()
    february = _gbm_quantity_pdf(
        start="30-ENE-26", end="27-FEB-26", opening_cash=Decimal("60.00"),
        opening_equity=Decimal("40.00"), opening_qty=Decimal("2"),
        closing_qty=Decimal("2"), trade_qty=Decimal("0"),
    )
    result = check_statement_equity_quantities(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, february),
    ]))
    assert result["quantity_status"] == "EXACT"
    checks = result["quantity_checks"]
    assert checks["equity_position_rows"] == 2
    assert checks["equity_trade_rows"] == 1
    assert checks["equity_position_trade_exact"] == 2
    assert checks["equity_quantity_continuity_exact"] == 1
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "SYMA", "40.00"):
        assert secret not in serialized


def test_equity_quantities_reject_unmatched_trade_and_inconsistent_cut():
    unmatched = check_statement_equity_quantities(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(trade_symbol="SYMB")),
    ]))
    assert unmatched["quantity_status"] == "REVIEW_REQUIRED"
    assert unmatched["quantity_checks"]["quantity_review_required"] == 1
    wrong_quantity = check_statement_equity_quantities(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(trade_qty=Decimal("1"))),
    ]))
    assert wrong_quantity["quantity_status"] == "REVIEW_REQUIRED"
    assert wrong_quantity["quantity_checks"]["quantity_review_required"] == 1
    january = _gbm_quantity_pdf()
    inconsistent_february = _gbm_quantity_pdf(
        start="30-ENE-26", end="27-FEB-26", opening_cash=Decimal("60.00"),
        opening_equity=Decimal("40.00"), opening_qty=Decimal("1"),
        closing_qty=Decimal("1"), trade_qty=Decimal("0"),
    )
    result = check_statement_equity_quantities(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, inconsistent_february),
    ]))
    assert result["quantity_status"] == "REVIEW_REQUIRED"
    assert result["quantity_checks"]["equity_quantity_continuity_different"] == 1


def test_equity_trade_costs_reconcile_buy_and_sale_without_private_output():
    buy = _gbm_quantity_pdf(
        trade_commission=Decimal("1.00"), trade_tax=Decimal("0.16"),
        closing_cash=Decimal("58.84"),
    )
    sale = _gbm_quantity_pdf(
        trade_action="VENTA", trade_qty=Decimal("1"), opening_qty=Decimal("2"),
        closing_qty=Decimal("1"), opening_equity=Decimal("40.00"),
        closing_equity=Decimal("20.00"), closing_cash=Decimal("118.84"),
        trade_commission=Decimal("1.00"), trade_tax=Decimal("0.16"),
    )
    result = check_statement_equity_trade_costs(_MemoryFolder([
        _MemoryFile(1, buy), _MemoryFile(2, sale),
    ]))
    assert result["trade_cost_status"] == "EXACT"
    checks = result["trade_cost_checks"]
    assert checks["trade_cost_documents_checked"] == 2
    assert checks["equity_buy_rows"] == checks["equity_sale_rows"] == 1
    assert checks["equity_trades_with_charge"] == 2
    assert checks["trade_cost_exact"] == 2
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "SYMA", "118.84"):
        assert secret not in serialized


def test_equity_trade_costs_separate_cent_rounding_and_unknown_interest():
    cent = check_statement_equity_trade_costs(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(trade_net_adjustment=Decimal("0.01"))),
    ]))
    assert cent["trade_cost_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert cent["trade_cost_checks"]["trade_cost_one_cent"] == 1
    material = check_statement_equity_trade_costs(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(trade_net_adjustment=Decimal("0.02"))),
    ]))
    assert material["trade_cost_status"] == "REVIEW_REQUIRED"
    assert material["trade_cost_checks"]["trade_cost_over_cent"] == 1
    interest = check_statement_equity_trade_costs(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(trade_interest=Decimal("1.00"))),
    ]))
    assert interest["trade_cost_status"] == "REVIEW_REQUIRED"
    assert interest["trade_cost_checks"]["trade_cost_review_required"] == 1


def test_equity_trade_costs_report_no_visible_trades_separately():
    result = check_statement_equity_trade_costs(_MemoryFolder([
        _MemoryFile(1, _gbm_quantity_pdf(
            closing_cash=Decimal("100.00"), closing_equity=Decimal("0.00"),
            trade_qty=Decimal("0"),
        )),
    ]))
    assert result["trade_cost_status"] == "NO_EQUITY_TRADES"
    assert result["trade_cost_checks"]["trade_cost_documents_checked"] == 1


def _gbm_reporto_line(day, folio, label, term, net, balance, *,
                     commission=Decimal("0.00"), interest=Decimal("0.00"),
                     tax=Decimal("0.00"), unit_price="1.234567"):
    return (f"{day} {folio} {label} EMISORA SERIE 0 20 {unit_price} 8.50 {term} "
            f"{commission:.2f} {interest:.2f} {tax:.2f} {net:.2f} {balance:.2f}")


def _gbm_reporto_pdf(*, maturity_net=Decimal("24.68"),
                     maturity_commission=Decimal("0.00"), maturity_label="VENCIMIENTO REPORTO",
                     maturity_interest=Decimal("0.20"), unit_price="1.234567"):
    closing = Decimal("75.31") + maturity_net
    return _gbm_cash_pdf(closing=closing, movement_rows=[
        _gbm_reporto_line("10/10", 1, "COMPRA REPORTO", 1, Decimal("24.69"),
                          Decimal("75.31"), unit_price=unit_price),
        _gbm_reporto_line("11/11", 2, maturity_label, 1, maturity_net, closing,
                          commission=maturity_commission, interest=maturity_interest,
                          tax=Decimal("0.01"), unit_price=unit_price),
    ])


def test_reporto_net_reconciles_purchase_and_maturity_without_private_output():
    result = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf()),
    ]))
    assert result["reporto_status"] == "EXACT"
    checks = result["reporto_checks"]
    assert checks["reporto_documents_checked"] == 1
    assert checks["reporto_buy_rows"] == checks["reporto_maturity_rows"] == 1
    assert checks["reporto_net_exact"] == 2
    assert checks["reporto_rows_with_interest"] == checks["reporto_rows_with_tax"] == 1
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "EMISORA", "99.99"):
        assert secret not in serialized


def test_reporto_net_flags_cent_material_and_unknown_charge():
    cent = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(maturity_net=Decimal("24.69"))),
    ]))
    assert cent["reporto_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert cent["reporto_checks"]["reporto_net_one_cent"] == 1
    material = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(maturity_net=Decimal("24.70"))),
    ]))
    assert material["reporto_status"] == "REVIEW_REQUIRED"
    assert material["reporto_checks"]["reporto_net_over_cent"] == 1
    commission = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(maturity_commission=Decimal("1.00"))),
    ]))
    assert commission["reporto_status"] == "REVIEW_REQUIRED"
    assert commission["reporto_checks"]["reporto_review_required"] == 1
    changed_precision = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(unit_price="1.23456")),
    ]))
    assert changed_precision["reporto_status"] == "REVIEW_REQUIRED"
    assert changed_precision["reporto_checks"]["reporto_review_required"] == 1


def test_reporto_net_reports_no_rows_and_unknown_operation_separately():
    no_reporto = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_cash_pdf(movement_rows=[
            "15/15 1 DEPOSITO EFECTIVO 0.00 0.00 0.00 10.00 110.00",
        ])),
    ]))
    assert no_reporto["reporto_status"] == "NO_REPORTO_ROWS"
    unknown = check_statement_reporto_net(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(maturity_label="MOVIMIENTO REPORTO")),
    ]))
    assert unknown["reporto_status"] == "REVIEW_REQUIRED"
    assert unknown["reporto_checks"]["reporto_review_required"] == 1


def test_reporto_pairs_match_across_adjacent_cuts_without_private_output():
    january = _gbm_cash_pdf(closing=Decimal("75.31"), movement_rows=[
        _gbm_reporto_line("30/30", 1, "COMPRA REPORTO", 3,
                          Decimal("24.69"), Decimal("75.31")),
    ])
    february = _gbm_cash_pdf(
        start="30-ENE-26", end="27-FEB-26", opening=Decimal("75.31"),
        closing=Decimal("100.19"), movement_rows=[
            _gbm_reporto_line("02/02", 2, "VENCIMIENTO REPORTO", 3,
                              Decimal("24.88"), Decimal("100.19"),
                              interest=Decimal("0.20"), tax=Decimal("0.01"),
                              unit_price="1.244500"),
        ],
    )
    result = check_statement_reporto_pairs(_MemoryFolder([
        _MemoryFile(1, january), _MemoryFile(2, february),
    ]))
    assert result["pair_status"] == "STRUCTURALLY_PLAUSIBLE"
    checks = result["pair_checks"]
    assert checks["pair_documents_checked"] == 2
    assert checks["pairs_matched"] == checks["pair_term_day_plausible"] == 1
    assert checks["pair_interest_bridge_exact"] == 1
    assert checks["pair_open_buy_at_last_cut"] == 0
    serialized = json.dumps(result)
    for secret in ("SYNTH12345", "PERSONA FICTICIA", "ABC010101AAA", "EMISORA", "100.19"):
        assert secret not in serialized


def test_reporto_pairs_keep_cent_interest_bridge_for_review():
    result = check_statement_reporto_pairs(_MemoryFolder([
        _MemoryFile(1, _gbm_reporto_pdf(maturity_interest=Decimal("0.01"))),
    ]))
    assert result["pair_status"] == "CENT_DIFFERENCES_NEED_REVIEW"
    assert result["pair_checks"]["pair_interest_bridge_one_cent"] == 1


def test_reporto_pairs_reject_ambiguous_buy_and_wrong_term_day():
    ambiguous = _gbm_cash_pdf(closing=Decimal("75.30"), movement_rows=[
        _gbm_reporto_line("10/10", 1, "COMPRA REPORTO", 1,
                          Decimal("24.69"), Decimal("75.31")),
        _gbm_reporto_line("10/10", 2, "COMPRA REPORTO", 1,
                          Decimal("24.69"), Decimal("50.62")),
        _gbm_reporto_line("11/11", 3, "VENCIMIENTO REPORTO", 1,
                          Decimal("24.68"), Decimal("75.30"),
                          interest=Decimal("0.20"), tax=Decimal("0.01")),
    ])
    result = check_statement_reporto_pairs(_MemoryFolder([_MemoryFile(1, ambiguous)]))
    assert result["pair_status"] == "REVIEW_REQUIRED"
    assert result["pair_checks"]["pair_ambiguous_buy"] == 1

    wrong_day = _gbm_cash_pdf(closing=Decimal("99.99"), movement_rows=[
        _gbm_reporto_line("10/10", 1, "COMPRA REPORTO", 1,
                          Decimal("24.69"), Decimal("75.31")),
        _gbm_reporto_line("12/12", 2, "VENCIMIENTO REPORTO", 1,
                          Decimal("24.68"), Decimal("99.99"),
                          interest=Decimal("0.20"), tax=Decimal("0.01")),
    ])
    result = check_statement_reporto_pairs(_MemoryFolder([_MemoryFile(1, wrong_day)]))
    assert result["pair_status"] == "REVIEW_REQUIRED"
    assert result["pair_checks"]["pair_term_day_mismatch"] == 1


def test_reporto_pairs_require_complete_buy_and_maturity_history():
    maturity_only = _gbm_cash_pdf(closing=Decimal("124.68"), movement_rows=[
        _gbm_reporto_line("11/11", 2, "VENCIMIENTO REPORTO", 1,
                          Decimal("24.68"), Decimal("124.68"),
                          interest=Decimal("0.20"), tax=Decimal("0.01")),
    ])
    result = check_statement_reporto_pairs(_MemoryFolder([_MemoryFile(1, maturity_only)]))
    assert result["pair_status"] == "REVIEW_REQUIRED"
    assert result["pair_checks"]["pair_missing_buy"] == 1

    buy_only = _gbm_cash_pdf(closing=Decimal("75.31"), movement_rows=[
        _gbm_reporto_line("10/10", 1, "COMPRA REPORTO", 1,
                          Decimal("24.69"), Decimal("75.31")),
    ])
    result = check_statement_reporto_pairs(_MemoryFolder([_MemoryFile(1, buy_only)]))
    assert result["pair_status"] == "REVIEW_REQUIRED"
    assert result["pair_checks"]["pair_open_buy_at_last_cut"] == 1

    excessive_term = _gbm_cash_pdf(closing=Decimal("75.31"), movement_rows=[
        _gbm_reporto_line("10/10", 1, "COMPRA REPORTO", 367,
                          Decimal("24.69"), Decimal("75.31")),
    ])
    result = check_statement_reporto_pairs(_MemoryFolder([_MemoryFile(1, excessive_term)]))
    assert result["pair_status"] == "REVIEW_REQUIRED"
    assert result["pair_checks"]["pair_review_required"] == 1
