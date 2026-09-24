"""Local, metadata-only preflight for GBM statement PDFs and CFDI XML files.

This deliberately does not import positions or transactions. It never prints file
names, account identifiers, names, tax IDs, monetary amounts, or security symbols.
The folder labels identify directories only; they are not verified account IDs.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

MAX_FILE_BYTES = 20_000_000
MAX_PDF_PAGES = 100
MAX_WRAPPER_BYTES = 512
PERIOD = re.compile(rb"\b(\d{2})-(ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)-(\d{2})\b")
MONTHS = {month: index for index, month in enumerate(
    (b"ENE", b"FEB", b"MAR", b"ABR", b"MAY", b"JUN", b"JUL", b"AGO", b"SEP", b"OCT", b"NOV", b"DIC"),
    start=1,
)}


class IntakeError(ValueError):
    """A document cannot be safely classified; message omits private values."""


def _period_date(match: re.Match[bytes]) -> date:
    try:
        return date(2000 + int(match[3]), MONTHS[match[2]], int(match[1]))
    except ValueError as exc:
        raise IntakeError("El PDF contiene una fecha de corte inválida.") from exc


def inspect_pdf(raw: bytes) -> dict[str, object]:
    """Read only statement period and layout metadata from one PDF."""
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise IntakeError("El PDF está vacío o excede el tamaño permitido.")
    offset = raw.find(b"%PDF-")
    if offset == -1 or offset > MAX_WRAPPER_BYTES:
        raise IntakeError("No se encontró un encabezado PDF válido al inicio.")
    if offset and not raw.startswith(b"^{doc_title"):
        raise IntakeError("El PDF tiene un prefijo desconocido.")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        pages = len(reader.pages)
        if not 1 <= pages <= MAX_PDF_PAGES:
            raise IntakeError("El PDF tiene un número de páginas fuera del límite.")
        first_page = (reader.pages[0].extract_text() or "").encode("utf-8")
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("No se pudo leer la estructura del PDF.") from exc
    dates = [_period_date(match) for match in PERIOD.finditer(first_page.upper())]
    if len(dates) != 2 or dates[0] >= dates[1]:
        raise IntakeError("El PDF no tiene un periodo de dos cortes reconocible.")
    return {
        "type": "statement_pdf",
        "period_start": dates[0].isoformat(),
        "period_end": dates[1].isoformat(),
        "pages": pages,
        "wrapper_bytes": offset,
    }


def inspect_xml(raw: bytes) -> dict[str, object]:
    """Classify CFDI XML without returning taxpayer or transaction content."""
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise IntakeError("El XML está vacío o excede el tamaño permitido.")
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise IntakeError("El XML contiene entidades o DTD no permitidos.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise IntakeError("No se pudo leer la estructura del XML.") from exc
    if root.tag not in {
        "{http://www.sat.gob.mx/cfd/4}Comprobante",
        "{http://www.sat.gob.mx/cfd/3}Comprobante",
    }:
        raise IntakeError("El XML no es un comprobante CFDI reconocible.")
    kind = root.attrib.get("TipoDeComprobante", "")
    currency = root.attrib.get("Moneda", "")
    version = root.attrib.get("Version", "")
    issue_date = root.attrib.get("Fecha", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", issue_date):
        raise IntakeError("El CFDI no tiene una fecha de emisión reconocible.")
    try:
        date.fromisoformat(issue_date[:10])
    except ValueError as exc:
        raise IntakeError("El CFDI tiene una fecha de emisión inválida.") from exc
    addenda = sum(node.tag.rsplit("}", 1)[-1] == "Movimientos" for node in root.iter())
    return {
        "type": "cfdi_xml",
        "issue_month": issue_date[:7],
        "cfdi_type": kind if kind in {"I", "E", "T", "N", "P"} else "otro",
        "cfdi_version": version if version in {"3.3", "4.0"} else "otra",
        "currency": currency if currency in {"MXN", "USD", "XXX"} else "otra",
        "movement_addenda": bool(addenda),
    }


def scan_folder(root: Path) -> dict[str, object]:
    """Summarize one private folder without exposing its paths or file content."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    files = sorted(path for path in root.rglob("*") if path.is_file() or path.is_symlink())
    parent_labels: dict[Path, str] = {}
    rows: list[dict[str, object]] = []
    fingerprints: set[str] = set()
    duplicates = 0
    failures = Counter()
    for path in files:
        if path.is_symlink():
            failures["enlace_simbólico"] += 1
            continue
        if path.suffix.lower() not in {".pdf", ".xml"}:
            failures["tipo_no_admitido"] += 1
            continue
        parent = path.parent
        if parent not in parent_labels:
            parent_labels[parent] = f"carpeta_{len(parent_labels) + 1}"
        try:
            raw = path.read_bytes()
            digest = sha256(raw).hexdigest()
            if digest in fingerprints:
                duplicates += 1
                continue
            fingerprints.add(digest)
            result = inspect_pdf(raw) if path.suffix.lower() == ".pdf" else inspect_xml(raw)
            rows.append({"folder": parent_labels[parent], **result})
        except (OSError, IntakeError):
            failures["no_clasificado"] += 1
    periods = Counter(row["period_end"] for row in rows if row["type"] == "statement_pdf")
    issues = Counter(row["issue_month"] for row in rows if row["type"] == "cfdi_xml")
    cfdi_versions = Counter(row["cfdi_version"] for row in rows if row["type"] == "cfdi_xml")
    by_folder = defaultdict(lambda: {"pdf": 0, "xml": 0, "period_ends": []})
    for row in rows:
        group = by_folder[row["folder"]]
        if row["type"] == "statement_pdf":
            group["pdf"] += 1
            group["period_ends"].append(row["period_end"])
        else:
            group["xml"] += 1
    return {
        "pdf_count": sum(row["type"] == "statement_pdf" for row in rows),
        "cfdi_xml_count": sum(row["type"] == "cfdi_xml" for row in rows),
        "cfdi_income_count": sum(row["type"] == "cfdi_xml" and row["cfdi_type"] == "I" for row in rows),
        "cfdi_movement_addenda_count": sum(
            row["type"] == "cfdi_xml" and row["movement_addenda"] for row in rows
        ),
        "pdf_wrapper_bytes": dict(sorted(Counter(
            str(row["wrapper_bytes"]) for row in rows if row["type"] == "statement_pdf"
        ).items())),
        "pdf_period_ends": dict(sorted(periods.items())),
        "cfdi_issue_months": dict(sorted(issues.items())),
        "cfdi_versions": dict(sorted(cfdi_versions.items())),
        "folders": {
            label: {"pdf": group["pdf"], "xml": group["xml"],
                    "period_ends": sorted(group["period_ends"])}
            for label, group in by_folder.items()
        },
        "exact_duplicate_files": duplicates,
        "failures": dict(sorted(failures.items())),
        "caution": "Las etiquetas de carpeta no verifican la identidad de una cuenta. "
                   "Este inventario no concilia posiciones, movimientos ni CFDI.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventario local GBM sin revelar datos privados.")
    parser.add_argument("folder", type=Path, help="Carpeta local que contiene PDF y XML.")
    arguments = parser.parse_args()
    try:
        result = scan_folder(arguments.folder)
    except IntakeError as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
