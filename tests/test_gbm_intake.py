"""Structural tests use generated documents, never a real statement."""

import json
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from scripts.inspect_gbm_intake import IntakeError, inspect_pdf, inspect_xml, scan_folder


def _pdf(*, start="31-DIC-25", end="30-ENE-26", private_text="CLIENTE RESERVADO"):
    stream = BytesIO()
    page = canvas.Canvas(stream)
    page.drawString(30, 750, f"ESTADO DE CUENTA {private_text}")
    page.drawString(30, 720, f"PERIODO {start} AL {end}")
    page.showPage()
    page.save()
    return stream.getvalue()


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
    class MemoryFile:
        suffix = ".pdf"
        parent = "cuenta confidencial"

        def __init__(self, order, contents):
            self.order = order
            self.contents = contents

        def __lt__(self, other):
            return self.order < other.order

        def is_file(self):
            return True

        def is_symlink(self):
            return False

        def read_bytes(self):
            return self.contents

    class MemoryFolder:
        def is_dir(self):
            return True

        def is_symlink(self):
            return False

        def rglob(self, _pattern):
            pdf = _pdf(private_text="NOMBRE CONFIDENCIAL 987654321")
            return [MemoryFile(1, pdf), MemoryFile(2, pdf)]

    result = scan_folder(MemoryFolder())
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["pdf_count"] == 1
    assert result["exact_duplicate_files"] == 1
    assert "NOMBRE" not in serialized
    assert "987654321" not in serialized
    assert "cuenta confidencial" not in serialized
