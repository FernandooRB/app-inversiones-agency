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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}"
MONEY = re.compile(rf"(?<![\d,])(?:\({NUMBER}\)|-?{NUMBER})(?![\d,])")
SHORT_LABELS = (
    "DEUDA ", "RENTA VARIABLE ", "VALORES EN CORTO", "FONDO DE FONDOS ",
    "GARANT", "OTRAS INVERSIONES ", "CREDITOS DE MARGEN ", "EFECTIVO ", "DERIVADOS ",
)
LONG_LABELS = SHORT_LABELS[:8] + (
    "DERIVADOS MERCADOS RECONOCIDOS ", "DERIVADOS MERCADOS EXTRABURSATILES ",
    "EFECTIVO MARGEN INICIAL",
)


class IntakeError(ValueError):
    """A document cannot be safely classified; message omits private values."""


@dataclass(frozen=True, repr=False)
class _StatementSummary:
    """Private working values, never serialized to the CLI output."""

    contract: str
    start: date
    end: date
    opening_total: Decimal
    closing_total: Decimal
    opening_difference: Decimal
    closing_difference: Decimal
    category_count: int


def _period_date(match: re.Match[bytes]) -> date:
    try:
        return date(2000 + int(match[3]), MONTHS[match[2]], int(match[1]))
    except ValueError as exc:
        raise IntakeError("El PDF contiene una fecha de corte inválida.") from exc


def _pdf_first_page(raw: bytes) -> tuple[str, int, int]:
    """Normalize the known GBM wrapper and read one page, without logging its text."""
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
        first_page = reader.pages[0].extract_text() or ""
    except IntakeError:
        raise
    except Exception as exc:
        raise IntakeError("No se pudo leer la estructura del PDF.") from exc
    return first_page, pages, offset


def inspect_pdf(raw: bytes) -> dict[str, object]:
    """Read only statement period and layout metadata from one PDF."""
    first_page, pages, offset = _pdf_first_page(raw)
    dates = [_period_date(match) for match in PERIOD.finditer(first_page.upper().encode("utf-8"))]
    if len(dates) != 2 or dates[0] >= dates[1]:
        raise IntakeError("El PDF no tiene un periodo de dos cortes reconocible.")
    return {
        "type": "statement_pdf",
        "period_start": dates[0].isoformat(),
        "period_end": dates[1].isoformat(),
        "pages": pages,
        "wrapper_bytes": offset,
    }


def _money_values(line: str) -> list[Decimal]:
    values = []
    for token in MONEY.findall(line):
        negative = token.startswith("(") and token.endswith(")")
        number = token[1:-1] if negative else token
        value = Decimal(number.replace(",", ""))
        values.append(-value if negative else value)
    return values


def _statement_summary(raw: bytes) -> _StatementSummary:
    """Parse only the first-page totals of the observed GBM layout."""
    first_page, _, _ = _pdf_first_page(raw)
    lines = first_page.splitlines()
    dates = [_period_date(match) for match in PERIOD.finditer(first_page.upper().encode("utf-8"))]
    if len(dates) != 2 or dates[0] >= dates[1]:
        raise IntakeError("El resumen no tiene dos fechas de corte válidas.")
    period_rows = [
        index for index, line in enumerate(lines)
        if len(PERIOD.findall(line.upper().encode("utf-8"))) == 2
    ]
    total_rows = [
        index for index, line in enumerate(lines) if line.lstrip().startswith("VALOR DEL PORTAFOLIO")
    ]
    if len(period_rows) != 1 or len(total_rows) != 1 or total_rows[0] <= period_rows[0]:
        raise IntakeError("El resumen GBM no tiene una estructura reconocible.")
    contract_tokens = {
        token.upper() for token in re.findall(r"Contrato:\s*([A-Z0-9]+)", first_page, flags=re.IGNORECASE)
    }
    if len(contract_tokens) != 1:
        raise IntakeError("El resumen no identifica un contrato único.")
    category_lines = [
        line.lstrip() for line in lines[period_rows[0] + 1:total_rows[0]]
        if len(MONEY.findall(line)) >= 3
    ]
    labels = SHORT_LABELS if len(category_lines) == len(SHORT_LABELS) else LONG_LABELS
    if len(category_lines) != len(labels) or any(
        not line.startswith(label) for line, label in zip(category_lines, labels, strict=True)
    ):
        raise IntakeError("Las categorías del resumen GBM no coinciden con un diseño conocido.")
    category_values = [_money_values(line) for line in category_lines]
    totals = _money_values(lines[total_rows[0]])
    if len(totals) < 2 or any(len(values) < 3 for values in category_values):
        raise IntakeError("El resumen GBM carece de importes completos.")
    opening = sum((values[0] for values in category_values), Decimal("0.00"))
    closing = sum((values[1] for values in category_values), Decimal("0.00"))
    return _StatementSummary(
        contract=next(iter(contract_tokens)),
        start=dates[0],
        end=dates[1],
        opening_total=totals[0],
        closing_total=totals[1],
        opening_difference=opening - totals[0],
        closing_difference=closing - totals[1],
        category_count=len(category_lines),
    )


def _difference_kind(value: Decimal) -> str:
    if value == 0:
        return "exact"
    if abs(value) <= Decimal("0.01"):
        return "one_cent"
    return "over_cent"


def check_statement_summaries(root: Path) -> dict[str, object]:
    """Check GBM cover arithmetic and consecutive cuts without exporting private values."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    by_contract: dict[str, list[_StatementSummary]] = defaultdict(list)
    by_folder: dict[Path, set[str]] = defaultdict(set)
    fingerprints: set[str] = set()
    counts = Counter()
    try:
        files = sorted(root.rglob("*"))
    except OSError as exc:
        raise IntakeError("No se pudo enumerar la carpeta local.") from exc
    for path in files:
        try:
            if path.is_symlink():
                counts["symlink_rejected"] += 1
                continue
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise IntakeError("El PDF excede el tamaño permitido.")
            raw = path.read_bytes()
            digest = sha256(raw).hexdigest()
            if digest in fingerprints:
                counts["exact_duplicates"] += 1
                continue
            fingerprints.add(digest)
            statement = _statement_summary(raw)
        except (OSError, IntakeError):
            counts["parse_failures"] += 1
            continue
        counts["documents_checked"] += 1
        counts[f"layout_{statement.category_count}_categories"] += 1
        counts[f"opening_{_difference_kind(statement.opening_difference)}"] += 1
        counts[f"closing_{_difference_kind(statement.closing_difference)}"] += 1
        by_contract[statement.contract].append(statement)
        by_folder[path.parent].add(statement.contract)
    counts["contracts_detected"] = len(by_contract)
    counts["folders_with_multiple_contracts"] = sum(len(contracts) > 1 for contracts in by_folder.values())
    for statements in by_contract.values():
        endings = Counter(statement.end for statement in statements)
        duplicates = sum(count - 1 for count in endings.values() if count > 1)
        if duplicates:
            counts["duplicate_contract_cuts"] += duplicates
            continue
        ordered = sorted(statements, key=lambda item: item.end)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end != current.start:
                counts["nonadjacent_periods"] += 1
                continue
            counts["adjacent_pairs"] += 1
            counts[f"continuity_{_difference_kind(previous.closing_total - current.opening_total)}"] += 1
    blockers = (
        "parse_failures", "symlink_rejected", "exact_duplicates", "folders_with_multiple_contracts",
        "duplicate_contract_cuts", "nonadjacent_periods", "opening_over_cent", "closing_over_cent",
        "continuity_one_cent", "continuity_over_cent",
    )
    if not counts["documents_checked"] or any(counts[key] for key in blockers):
        status = "REVIEW_REQUIRED"
    elif counts["opening_one_cent"] or counts["closing_one_cent"]:
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "cover_status": status,
        "summary_checks": dict(sorted(counts.items())),
        "caution": "Sólo comprueba la portada y continuidad de cortes. No concilia posiciones, "
                   "operaciones, efectivo desglosado ni CFDI.",
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
    try:
        files = sorted(root.rglob("*"))
    except OSError as exc:
        raise IntakeError("No se pudo enumerar la carpeta local.") from exc
    parent_labels: dict[Path, str] = {}
    rows: list[dict[str, object]] = []
    fingerprints: set[str] = set()
    duplicates = 0
    failures = Counter()
    for path in files:
        try:
            if path.is_symlink():
                failures["enlace_simbólico"] += 1
                continue
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".pdf", ".xml"}:
                failures["tipo_no_admitido"] += 1
                continue
            parent = path.parent
            if parent not in parent_labels:
                parent_labels[parent] = f"carpeta_{len(parent_labels) + 1}"
            if path.stat().st_size > MAX_FILE_BYTES:
                raise IntakeError("El archivo excede el tamaño permitido.")
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
    parser.add_argument(
        "--check-summaries", action="store_true",
        help="Comprueba portada y continuidad de estados PDF sin mostrar importes ni contratos.",
    )
    arguments = parser.parse_args()
    try:
        result = scan_folder(arguments.folder)
        if arguments.check_summaries:
            result["cover_summary"] = check_statement_summaries(arguments.folder)
    except IntakeError as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if arguments.check_summaries and (
        result["cover_summary"]["cover_status"] != "EXACT" or result["failures"]
    ):
        parser.exit(3)


if __name__ == "__main__":
    main()
