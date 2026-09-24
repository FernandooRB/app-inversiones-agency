"""Local, privacy-preserving preflight for GBM statement PDFs and CFDI XML files.

This checks visible totals and quantities but does not export positions or transactions. It never prints file
names, account identifiers, names, tax IDs, monetary amounts, or security symbols.
The folder labels identify directories only; they are not verified account IDs.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

MAX_FILE_BYTES = 20_000_000
MAX_PDF_PAGES = 100
MAX_WRAPPER_BYTES = 512
MAX_REPORTO_TERM_DAYS = 366
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
    opening_categories: tuple[Decimal, ...]
    closing_categories: tuple[Decimal, ...]


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
        opening_categories=tuple(values[0] for values in category_values),
        closing_categories=tuple(values[1] for values in category_values),
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
            for closing, opening in zip(
                previous.closing_categories[:8], current.opening_categories[:8], strict=True,
            ):
                counts[f"common_category_continuity_{_difference_kind(closing - opening)}"] += 1
    blockers = (
        "parse_failures", "symlink_rejected", "exact_duplicates", "folders_with_multiple_contracts",
        "duplicate_contract_cuts", "nonadjacent_periods", "opening_over_cent", "closing_over_cent",
        "continuity_one_cent", "continuity_over_cent",
        "common_category_continuity_over_cent",
    )
    if not counts["documents_checked"] or any(counts[key] for key in blockers):
        status = "REVIEW_REQUIRED"
    elif (counts["opening_one_cent"] or counts["closing_one_cent"]
          or counts["common_category_continuity_one_cent"]):
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "cover_status": status,
        "summary_checks": dict(sorted(counts.items())),
        "caution": "Sólo comprueba la portada y continuidad de ocho categorías comunes entre cortes. "
                   "No concilia posiciones, "
                   "operaciones, efectivo desglosado ni CFDI.",
    }


DETAIL_TOTALS = {
    "debt": re.compile(r"^TOTAL:\s*DEUDA(?!\s+EN\s+REPORTO)(?:\s|$)", re.I),
    "equity": re.compile(r"^TOTAL:\s*RENTA VARIABLE(?:\s|$)", re.I),
    "cash": re.compile(r"^.*TOTAL.*EFECTIVO", re.I),
}
DETAIL_VALUE_COUNTS = {"debt": 3, "equity": 3, "cash": 2}
POSITION_NUMBER = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")


def _position_columns(line: str) -> list[Decimal]:
    """Read the ten numeric columns of the observed equity position layout."""
    tokens = line.split()[-10:]
    if len(tokens) != 10:
        raise IntakeError("La posición no tiene diez columnas numéricas.")
    values = []
    for token in tokens:
        negative = token.startswith("(") and token.endswith(")")
        number = token[1:-1] if negative else token
        if not POSITION_NUMBER.fullmatch(number):
            raise IntakeError("La posición tiene una columna numérica no reconocible.")
        value = Decimal(number.replace(",", ""))
        values.append(-value if negative else value)
    return values


def _detail_differences(raw: bytes, summary: _StatementSummary) -> tuple[dict[str, Decimal], Counter]:
    """Check visible category totals and equity position groups in one statement."""
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [
            line.lstrip() for page in reader.pages[1:]
            for line in (page.extract_text() or "").splitlines()
        ]
    except Exception as exc:
        raise IntakeError("No se pudo leer el detalle del PDF.") from exc
    expected = {
        "debt": summary.closing_categories[0],
        "equity": summary.closing_categories[1],
        "cash": summary.closing_categories[7],
    }
    differences: dict[str, Decimal] = {}
    counts = Counter()
    equity_end = None
    for kind, rule in DETAIL_TOTALS.items():
        candidates = [(index, line) for index, line in enumerate(lines) if rule.search(line)]
        if not candidates and kind != "cash" and expected[kind] == 0:
            counts[f"{kind}_zero_without_detail"] += 1
            continue
        if len(candidates) != 1:
            raise IntakeError("El detalle no tiene un total de categoría único.")
        index, line = candidates[0]
        amounts = _money_values(line)
        if len(amounts) != DETAIL_VALUE_COUNTS[kind]:
            raise IntakeError("El total del detalle tiene columnas inesperadas.")
        differences[kind] = amounts[0] - expected[kind]
        counts[f"{kind}_detail_present"] += 1
        if kind == "equity":
            equity_end = index
    if equity_end is not None:
        section_starts = [
            index for index, line in enumerate(lines[:equity_end])
            if line.upper().strip() == "RENTA VARIABLE"
        ]
        if len(section_starts) != 1:
            raise IntakeError("La sección de renta variable es ambigua.")
        positions: list[list[Decimal]] = []
        subtotals: list[Decimal] = []
        for line in lines[section_starts[0] + 1:equity_end]:
            amounts = _money_values(line)
            if line.upper().startswith("TOTAL:"):
                if len(amounts) != 3 or not positions:
                    raise IntakeError("Un grupo de posiciones no tiene subtotal válido.")
                subtotal = amounts[0]
                if sum((row[1] for row in positions), Decimal("0.00")) != subtotal:
                    raise IntakeError("Las posiciones no suman el subtotal del grupo.")
                counts["equity_groups_exact"] += 1
                counts["equity_positions_checked"] += len(positions)
                subtotals.append(subtotal)
                positions = []
            elif len(amounts) == 4:
                columns = _position_columns(line)
                if columns[7] != amounts[1]:
                    raise IntakeError("El valor de mercado no coincide con la columna esperada.")
                calculated = columns[1] * columns[5]
                if calculated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != columns[7]:
                    raise IntakeError("Cantidad y precio no reproducen el valor de mercado.")
                if calculated != columns[7]:
                    counts["equity_quantity_price_rounded"] += 1
                positions.append(amounts)
            elif amounts:
                raise IntakeError("Hay una fila monetaria de posiciones con columnas inesperadas.")
        if not subtotals or positions:
            raise IntakeError("Las posiciones no cierran con el total de renta variable.")
        equity_total = _money_values(lines[equity_end])[0]
        if sum(subtotals, Decimal("0.00")) != equity_total:
            raise IntakeError("Los subtotales no suman la renta variable.")
    return differences, counts


def check_statement_detail_totals(root: Path) -> dict[str, object]:
    """Check closing detail totals and visible equity positions, without exporting values."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
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
            summary = _statement_summary(raw)
            differences, document_counts = _detail_differences(raw, summary)
        except (OSError, IntakeError):
            counts["detail_review_required"] += 1
            continue
        counts["details_checked"] += 1
        counts.update(document_counts)
        for kind, difference in differences.items():
            counts[f"{kind}_{_difference_kind(difference)}"] += 1
    if not counts["details_checked"] or counts["detail_review_required"] or counts["symlink_rejected"] or any(
        counts[f"{kind}_over_cent"] for kind in DETAIL_TOTALS
    ):
        status = "REVIEW_REQUIRED"
    elif any(counts[f"{kind}_one_cent"] for kind in DETAIL_TOTALS):
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "detail_status": status,
        "detail_checks": dict(sorted(counts.items())),
        "caution": "Comprueba totales de cierre, subtotales y posiciones visibles de renta variable. "
                   "No concilia movimientos, cantidades/títulos, efectivo transaccional ni CFDI.",
    }


CASH_MOVEMENT_DAY_PAIR = re.compile(r"^\s*\d{2}/\d{2}\s")
MOVEMENT_DAY_GROUPS = re.compile(r"^\s*(\d{2})/(\d{2})\s")
MAX_PLAUSIBLE_DAY_LAG = 10


def _cash_direction(line: str) -> int:
    """Classify the sign of an observed GBM cash operation without exporting its text."""
    upper = "".join(
        character for character in unicodedata.normalize("NFD", line.upper())
        if unicodedata.category(character) != "Mn"
    )
    if ("COMPRA" in upper and "VENTA" in upper) or ("DEPOSITO" in upper and "RETIRO" in upper):
        raise IntakeError("La dirección de un movimiento es ambigua.")
    if "DIVIDENDO" in upper:
        return -1 if any(word in upper for word in ("RETENCI", "ISR", "IMPUESTO")) else 1
    if "COMPRA" in upper or "RETIRO" in upper or "COMISION" in upper:
        return -1
    if any(word in upper for word in ("VENTA", "DEPOSITO", "ABONO", "REPORTO", "INTERES")):
        return 1
    raise IntakeError("Un movimiento de efectivo tiene una dirección no reconocible.")


def _cash_ledger_counts(raw: bytes, summary: _StatementSummary) -> Counter:
    """Check the printed net amount and running balance of the observed cash ledger."""
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [
            line for page in reader.pages[1:]
            for line in (page.extract_text() or "").splitlines()
        ]
    except Exception as exc:
        raise IntakeError("No se pudo leer el libro de movimientos del PDF.") from exc
    headings = [index for index, line in enumerate(lines) if "MOVIMIENTOS" in line.upper()]
    if len(headings) != 2:
        raise IntakeError("El libro de movimientos no tiene límites reconocibles.")
    rows = []
    for line in lines[headings[0] + 1:headings[1]]:
        if not CASH_MOVEMENT_DAY_PAIR.match(line):
            continue
        amounts = _money_values(line)
        if len(amounts) not in {5, 6}:
            raise IntakeError("Una fila de movimientos tiene columnas inesperadas.")
        rows.append((line, amounts[-2], amounts[-1]))
    if not rows or "INICIAL" not in rows[0][0].upper() or "EFECTIVO" not in rows[0][0].upper():
        raise IntakeError("El libro de efectivo no tiene saldo inicial reconocible.")
    if rows[0][2] != summary.opening_categories[7] or rows[-1][2] != summary.closing_categories[7]:
        raise IntakeError("Los saldos del libro de efectivo no coinciden con la portada.")
    counts = Counter({"cash_ledgers_checked": 1, "cash_rows_checked": len(rows)})
    for (_, _, previous_balance), (line, net, current_balance) in zip(rows, rows[1:], strict=False):
        direction = _cash_direction(line)
        difference = previous_balance + direction * net - current_balance
        counts[f"cash_transition_{_difference_kind(difference)}"] += 1
        if direction == 1:
            counts["cash_credit_rows"] += 1
        else:
            counts["cash_debit_rows"] += 1
    return counts


def check_statement_cash_ledgers(root: Path) -> dict[str, object]:
    """Check movement running balances without returning operation or account values."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
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
            counts.update(_cash_ledger_counts(raw, _statement_summary(raw)))
        except (OSError, IntakeError):
            counts["cash_review_required"] += 1
    blockers = ("cash_review_required", "symlink_rejected", "cash_transition_over_cent")
    if not counts["cash_ledgers_checked"] or any(counts[key] for key in blockers):
        status = "REVIEW_REQUIRED"
    elif counts["cash_transition_one_cent"]:
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "cash_status": status,
        "cash_checks": dict(sorted(counts.items())),
        "caution": "Sólo comprueba importes netos y saldos corridos impresos. No prueba que el PDF "
                   "incluya todos los movimientos, ni concilia títulos, reportos o CFDI.",
    }


def _movement_date_details(
    raw: bytes, summary: _StatementSummary,
) -> tuple[list[str], list[date], Counter]:
    """Resolve printed day fragments for internal checks without asserting their meaning."""
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [line for page in reader.pages[1:]
                 for line in (page.extract_text() or "").splitlines()]
    except Exception as exc:
        raise IntakeError("No se pudo leer la tabla de fechas del PDF.") from exc
    headings = [index for index, line in enumerate(lines) if "MOVIMIENTOS" in line.upper()]
    if len(headings) != 2:
        raise IntakeError("La tabla de movimientos no tiene límites reconocibles.")
    rows = [line for line in lines[headings[0] + 1:headings[1]]
            if MOVEMENT_DAY_GROUPS.match(line)]
    if not rows or "INICIAL" not in rows[0].upper() or "EFECTIVO" not in rows[0].upper():
        raise IntakeError("La tabla de movimientos no tiene saldo inicial reconocible.")

    period_days = []
    day = summary.start + timedelta(days=1)
    while day <= summary.end:
        period_days.append(day)
        day += timedelta(days=1)
    candidate_days: list[list[date]] = []
    second_fragments: list[int] = []
    for row in rows[1:]:
        match = MOVEMENT_DAY_GROUPS.match(row)
        if match is None:
            raise IntakeError("Una fila no tiene dos días reconocibles.")
        first, second = int(match[1]), int(match[2])
        candidates = [item for item in period_days if item.day == first]
        if not candidates:
            raise IntakeError("Un día de movimiento queda fuera del periodo.")
        candidate_days.append(candidates)
        second_fragments.append(second)

    forward: list[set[date]] = []
    for candidates in candidate_days:
        viable = {item for item in candidates if not forward or
                  any(previous <= item for previous in forward[-1])}
        if not viable:
            raise IntakeError("Los días de movimiento no siguen el orden de la tabla.")
        forward.append(viable)
    backward: list[set[date]] = [set() for _ in candidate_days]
    for index in range(len(candidate_days) - 1, -1, -1):
        backward[index] = {item for item in candidate_days[index]
                           if index == len(candidate_days) - 1 or
                           any(item <= following for following in backward[index + 1])}
    counts = Counter({"date_documents_checked": 1, "movement_rows_checked": len(candidate_days)})
    resolved_dates = []
    for index, second in enumerate(second_fragments):
        possibilities = forward[index] & backward[index]
        if len(possibilities) != 1:
            raise IntakeError("Un día de movimiento tiene más de una fecha posible.")
        first_date = next(iter(possibilities))
        resolved_dates.append(first_date)
        if len(candidate_days[index]) > 1:
            counts["first_days_resolved_by_order"] += 1
        plausible = [lag for lag in range(MAX_PLAUSIBLE_DAY_LAG + 1)
                     if (first_date + timedelta(days=lag)).day == second]
        if len(plausible) != 1:
            raise IntakeError("El segundo día no sigue al primero en el plazo de revisión.")
        counts[f"observed_day_lag_{plausible[0]}"] += 1
    return rows[1:], resolved_dates, counts


def _movement_date_counts(raw: bytes, summary: _StatementSummary) -> Counter:
    """Check the two printed day fragments without asserting their business meaning."""
    return _movement_date_details(raw, summary)[2]


def check_statement_movement_dates(root: Path) -> dict[str, object]:
    """Report only aggregate plausibility of printed day pairs in statement movements."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
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
            counts.update(_movement_date_counts(raw, _statement_summary(raw)))
        except (OSError, IntakeError):
            counts["date_review_required"] += 1
    status = "REVIEW_REQUIRED" if (
        not counts["date_documents_checked"] or counts["date_review_required"] or
        counts["symlink_rejected"]
    ) else "STRUCTURALLY_PLAUSIBLE"
    return {
        "date_status": status,
        "date_checks": dict(sorted(counts.items())),
        "caution": "Los dos números impresos se validan sólo como días ordenados y con un "
                   "desfase máximo provisional de 10 días. No confirma cuál es la fecha de "
                   "operación o liquidación ni acredita integridad de movimientos.",
    }


def _equity_key(line: str) -> str:
    prefix = " ".join(line.split()[:-10]).replace("*", " ").upper()
    key = " ".join(prefix.split())
    if not key:
        raise IntakeError("Una posición no tiene identificador reconocible.")
    return key


def _trade_quantity(line: str) -> Decimal:
    tokens = line.split()
    if len(tokens) < 7:
        raise IntakeError("Una operación de títulos tiene columnas incompletas.")
    token = tokens[-7]
    negative = token.startswith("(") and token.endswith(")")
    number = token[1:-1] if negative else token
    if not POSITION_NUMBER.fullmatch(number):
        raise IntakeError("La cantidad de títulos no es reconocible.")
    quantity = Decimal(number.replace(",", ""))
    quantity = -quantity if negative else quantity
    if quantity <= 0:
        raise IntakeError("La cantidad de títulos debe ser positiva.")
    return quantity


def _is_equity_trade_row(line: str) -> bool:
    upper = line.upper()
    return (bool(CASH_MOVEMENT_DAY_PAIR.match(line))
            and ("COMPRA" in upper or "VENTA" in upper) and "REPORTO" not in upper)


def _equity_trade_cost_difference(line: str) -> tuple[Decimal, bool, bool]:
    """Compare the printed net with quantity, price, commission and tax."""
    upper = line.upper()
    if "COMPRA" in upper and "VENTA" in upper:
        raise IntakeError("Una compraventa tiene dirección ambigua.")
    is_buy = "COMPRA" in upper
    tokens = line.split()
    quantity = _trade_quantity(line)
    price_token = tokens[-6]
    if not POSITION_NUMBER.fullmatch(price_token):
        raise IntakeError("El precio de una compraventa no es reconocible.")
    price = Decimal(price_token.replace(",", ""))
    if price <= 0:
        raise IntakeError("El precio de una compraventa debe ser positivo.")
    amounts = _money_values(line)
    if len(amounts) != 5:
        raise IntakeError("Una compraventa tiene columnas monetarias inesperadas.")
    commission, interest, tax, net, _balance = amounts
    if interest != 0 or min(commission, tax, net) < 0:
        raise IntakeError("Una compraventa tiene cargos que requieren revisión manual.")
    gross = (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    expected = gross + commission + tax if is_buy else gross - commission - tax
    return expected - net, is_buy, commission > 0 or tax > 0


def _equity_trade_cost_counts(raw: bytes) -> Counter:
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [line for page in reader.pages[1:]
                 for line in (page.extract_text() or "").splitlines()]
    except Exception as exc:
        raise IntakeError("No se pudo leer la tabla de compraventas del PDF.") from exc
    headings = [index for index, line in enumerate(lines) if "MOVIMIENTOS" in line.upper()]
    if len(headings) != 2:
        raise IntakeError("La tabla de compraventas no tiene límites reconocibles.")
    counts = Counter({"trade_cost_documents_checked": 1})
    for line in lines[headings[0] + 1:headings[1]]:
        if not _is_equity_trade_row(line):
            continue
        difference, is_buy, has_charge = _equity_trade_cost_difference(line)
        counts["equity_buy_rows" if is_buy else "equity_sale_rows"] += 1
        counts[f"trade_cost_{_difference_kind(difference)}"] += 1
        if has_charge:
            counts["equity_trades_with_charge"] += 1
    return counts


def check_statement_equity_trade_costs(root: Path) -> dict[str, object]:
    """Reconcile visible equity trade net values without exporting any values."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
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
            _statement_summary(raw)
            counts.update(_equity_trade_cost_counts(raw))
        except (OSError, IntakeError):
            counts["trade_cost_review_required"] += 1
    trades = counts["equity_buy_rows"] + counts["equity_sale_rows"]
    if (not counts["trade_cost_documents_checked"] or counts["trade_cost_review_required"]
            or counts["symlink_rejected"] or counts["trade_cost_over_cent"]):
        status = "REVIEW_REQUIRED"
    elif not trades:
        status = "NO_EQUITY_TRADES"
    elif counts["trade_cost_one_cent"]:
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "trade_cost_status": status,
        "trade_cost_checks": dict(sorted(counts.items())),
        "caution": "Sólo compara compraventas visibles de renta variable con cantidad, precio, "
                   "comisión, impuesto y neto impresos. Un interés no nulo exige revisión. "
                   "No determina el tratamiento fiscal ni el costo total de la cartera.",
    }


def _reporto_net_difference(line: str) -> tuple[Decimal, bool, bool, bool]:
    """Check only the observed reporto row arithmetic, not accrued-interest economics."""
    upper = line.upper()
    is_buy = bool(re.search(r"\bCOMPRA\b", upper))
    is_maturity = bool(re.search(r"\bVENCIMIENTO\b", upper))
    if is_buy == is_maturity:
        raise IntakeError("Un reporto no identifica una compra o vencimiento únicos.")
    tokens = line.split()
    amounts = _money_values(line)
    if len(tokens) != 16 or len(amounts) != 6:
        raise IntakeError("Un reporto tiene columnas inesperadas.")
    quantity_token, price_token = tokens[-9], tokens[-8]
    if not POSITION_NUMBER.fullmatch(quantity_token) or not POSITION_NUMBER.fullmatch(price_token):
        raise IntakeError("La cantidad o precio de un reporto no es reconocible.")
    quantity = Decimal(quantity_token.replace(",", ""))
    price = Decimal(price_token.replace(",", ""))
    if quantity <= 0 or price <= 0 or price.as_tuple().exponent != -6:
        raise IntakeError("La cantidad o precisión del precio de un reporto requiere revisión.")
    _rate, commission, interest, tax, net, _balance = amounts
    if min(commission, interest, tax, net) < 0 or commission != 0:
        raise IntakeError("Un reporto tiene cargos que requieren revisión manual.")
    if is_buy and (interest != 0 or tax != 0):
        raise IntakeError("Una compra de reporto tiene cargos inesperados.")
    principal_from_printed_price = (quantity * price).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
    expected = principal_from_printed_price if is_buy else principal_from_printed_price - tax
    return expected - net, is_buy, interest > 0, tax > 0


def _reporto_net_counts(raw: bytes) -> Counter:
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [line for page in reader.pages[1:]
                 for line in (page.extract_text() or "").splitlines()]
    except Exception as exc:
        raise IntakeError("No se pudo leer la tabla de reportos del PDF.") from exc
    headings = [index for index, line in enumerate(lines) if "MOVIMIENTOS" in line.upper()]
    if len(headings) != 2:
        raise IntakeError("La tabla de reportos no tiene límites reconocibles.")
    counts = Counter({"reporto_documents_checked": 1})
    for line in lines[headings[0] + 1:headings[1]]:
        if not CASH_MOVEMENT_DAY_PAIR.match(line) or not re.search(r"\bREPORTO\b", line.upper()):
            continue
        difference, is_buy, has_interest, has_tax = _reporto_net_difference(line)
        counts["reporto_buy_rows" if is_buy else "reporto_maturity_rows"] += 1
        counts[f"reporto_net_{_difference_kind(difference)}"] += 1
        if has_interest:
            counts["reporto_rows_with_interest"] += 1
        if has_tax:
            counts["reporto_rows_with_tax"] += 1
    return counts


def check_statement_reporto_net(root: Path) -> dict[str, object]:
    """Reconcile observed reporto net rows without exposing their values."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
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
            _statement_summary(raw)
            counts.update(_reporto_net_counts(raw))
        except (OSError, IntakeError):
            counts["reporto_review_required"] += 1
    reportos = counts["reporto_buy_rows"] + counts["reporto_maturity_rows"]
    if (not counts["reporto_documents_checked"] or counts["reporto_review_required"]
            or counts["symlink_rejected"] or counts["reporto_net_over_cent"]):
        status = "REVIEW_REQUIRED"
    elif not reportos:
        status = "NO_REPORTO_ROWS"
    elif counts["reporto_net_one_cent"]:
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "reporto_status": status,
        "reporto_checks": dict(sorted(counts.items())),
        "caution": "Sólo compara netos de compras y vencimientos de reporto visibles con títulos "
                   "por precio y el impuesto impreso. No concilia por separado intereses, tasas, "
                   "plazos, emparejamiento compra-vencimiento ni tratamiento fiscal.",
    }


@dataclass(frozen=True, repr=False)
class _ReportoEntry:
    """Private working values for one visible reporto row; never serialized."""

    first_day: date
    key: tuple[str, ...]
    term_days: int
    net: Decimal
    interest: Decimal
    tax: Decimal
    is_buy: bool


def _reporto_pair_entries(
    raw: bytes, summary: _StatementSummary,
) -> tuple[list[_ReportoEntry], Counter]:
    rows, first_dates, _date_counts = _movement_date_details(raw, summary)
    counts = Counter({"pair_documents_checked": 1})
    entries = []
    for line, first_day in zip(rows, first_dates, strict=True):
        if not re.search(r"\bREPORTO\b", line.upper()):
            continue
        difference, is_buy, _has_interest, _has_tax = _reporto_net_difference(line)
        tokens = line.split()
        term_token = tokens[-6]
        if len(term_token) > 3 or not re.fullmatch(r"[1-9]\d*", term_token):
            raise IntakeError("El plazo de un reporto no es reconocible.")
        term_days = int(term_token)
        if term_days > MAX_REPORTO_TERM_DAYS:
            raise IntakeError("El plazo de un reporto excede el límite de revisión.")
        amounts = _money_values(line)
        key = tuple(tokens[index].upper() for index in (4, 5, 6, 7, 9, 10))
        entries.append(_ReportoEntry(
            first_day=first_day, key=key, term_days=term_days,
            net=amounts[-2], interest=amounts[-4], tax=amounts[-3], is_buy=is_buy,
        ))
        counts["pair_buy_rows" if is_buy else "pair_maturity_rows"] += 1
        counts[f"pair_row_net_{_difference_kind(difference)}"] += 1
    return entries, counts


def check_statement_reporto_pairs(root: Path) -> dict[str, object]:
    """Match visible reporto buys and maturities by private printed keys and order."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    counts = Counter()
    by_contract: dict[str, list[tuple[_StatementSummary, list[_ReportoEntry]]]] = defaultdict(list)
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
            summary = _statement_summary(raw)
            entries, document_counts = _reporto_pair_entries(raw, summary)
        except (OSError, IntakeError):
            counts["pair_review_required"] += 1
            continue
        counts.update(document_counts)
        by_contract[summary.contract].append((summary, entries))
    for statements in by_contract.values():
        ordered = sorted(statements, key=lambda item: item[0].end)
        if len({summary.end for summary, _ in ordered}) != len(ordered):
            counts["duplicate_contract_cuts"] += 1
            continue
        if any(previous.end != current.start for (previous, _), (current, _) in
               zip(ordered, ordered[1:], strict=False)):
            counts["nonadjacent_periods"] += 1
            continue
        open_buys: dict[tuple[str, ...], list[_ReportoEntry]] = defaultdict(list)
        for _summary, entries in ordered:
            for entry in entries:
                if entry.is_buy:
                    open_buys[entry.key].append(entry)
                    continue
                candidates = open_buys[entry.key]
                if not candidates:
                    counts["pair_missing_buy"] += 1
                    continue
                if len(candidates) != 1:
                    counts["pair_ambiguous_buy"] += 1
                    continue
                buy = candidates.pop()
                if buy.first_day + timedelta(days=buy.term_days) != entry.first_day:
                    counts["pair_term_day_mismatch"] += 1
                else:
                    counts["pair_term_day_plausible"] += 1
                difference = buy.net + entry.interest - entry.tax - entry.net
                counts[f"pair_interest_bridge_{_difference_kind(difference)}"] += 1
                counts["pairs_matched"] += 1
        counts["pair_open_buy_at_last_cut"] += sum(len(items) for items in open_buys.values())
    blockers = (
        "pair_review_required", "symlink_rejected", "duplicate_contract_cuts",
        "nonadjacent_periods", "pair_missing_buy", "pair_ambiguous_buy",
        "pair_term_day_mismatch", "pair_open_buy_at_last_cut",
        "pair_interest_bridge_over_cent", "pair_row_net_over_cent",
    )
    if not counts["pair_documents_checked"] or any(counts[name] for name in blockers):
        status = "REVIEW_REQUIRED"
    elif not counts["pair_buy_rows"] and not counts["pair_maturity_rows"]:
        status = "NO_REPORTO_ROWS"
    elif counts["pair_interest_bridge_one_cent"] or counts["pair_row_net_one_cent"]:
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "STRUCTURALLY_PLAUSIBLE"
    return {
        "pair_status": status,
        "pair_checks": dict(sorted(counts.items())),
        "caution": "Empareja reportos por contrato, clave impresa y orden; compara el plazo con "
                   "el primer día plausible de cada fila y el neto de compra más interés menos "
                   "impuesto con el neto del vencimiento. No confirma el significado de "
                   "las fechas ni el cálculo de interés o impuesto.",
    }


def _equity_quantity_bridge(
    raw: bytes, summary: _StatementSummary,
) -> tuple[dict[str, tuple[Decimal, Decimal]], Counter]:
    """Read private position quantities and reconcile visible equity buys/sales."""
    offset = raw.find(b"%PDF-")
    try:
        reader = PdfReader(BytesIO(raw[offset:]), strict=True)
        lines = [
            line.lstrip() for page in reader.pages[1:]
            for line in (page.extract_text() or "").splitlines()
        ]
    except Exception as exc:
        raise IntakeError("No se pudo leer la sección de títulos del PDF.") from exc
    positions: dict[str, tuple[Decimal, Decimal]] = {}
    equity_totals = [index for index, line in enumerate(lines) if DETAIL_TOTALS["equity"].search(line)]
    if equity_totals:
        if len(equity_totals) != 1:
            raise IntakeError("El total de renta variable es ambiguo.")
        starts = [
            index for index, line in enumerate(lines[:equity_totals[0]])
            if line.upper().strip() == "RENTA VARIABLE"
        ]
        if len(starts) != 1:
            raise IntakeError("La sección de posiciones es ambigua.")
        for line in lines[starts[0] + 1:equity_totals[0]]:
            if line.upper().startswith("TOTAL:"):
                continue
            amounts = _money_values(line)
            if not amounts:
                continue
            if len(amounts) != 4:
                raise IntakeError("Una posición tiene columnas monetarias inesperadas.")
            key = _equity_key(line)
            if key in positions:
                raise IntakeError("Una posición aparece duplicada en el corte.")
            columns = _position_columns(line)
            positions[key] = (columns[0], columns[1])
    elif summary.closing_categories[1] != 0:
        raise IntakeError("Falta el detalle de renta variable del corte.")
    headings = [index for index, line in enumerate(lines) if "MOVIMIENTOS" in line.upper()]
    if len(headings) != 2:
        raise IntakeError("El libro de movimientos no tiene límites reconocibles.")
    trades = [
        line for line in lines[headings[0] + 1:headings[1]]
        if _is_equity_trade_row(line)
    ]
    counts = Counter({"quantity_documents_checked": 1, "equity_position_rows": len(positions),
                      "equity_trade_rows": len(trades)})
    trade_changes: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for line in trades:
        if len(_money_values(line)) not in {5, 6}:
            raise IntakeError("Una compraventa tiene columnas monetarias inesperadas.")
        upper = " ".join(line.upper().replace("*", " ").split())
        if "COMPRA" in upper and "VENTA" in upper:
            raise IntakeError("Una operación de títulos tiene dirección ambigua.")
        matches = [
            key for key in positions
            if re.search(rf"(?<![A-Z0-9]){re.escape(key)}(?![A-Z0-9])", upper)
        ]
        if len(matches) != 1:
            raise IntakeError("Una operación no identifica una posición única al cierre.")
        direction = 1 if "COMPRA" in upper else -1
        trade_changes[matches[0]] += direction * _trade_quantity(line)
    for key, (opening, closing) in positions.items():
        if closing - opening != trade_changes[key]:
            raise IntakeError("Las operaciones no explican el cambio de títulos.")
        counts["equity_position_trade_exact"] += 1
    return positions, counts


def check_statement_equity_quantities(root: Path) -> dict[str, object]:
    """Check visible equity trades and quantities between adjacent cuts, without outputting keys."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    counts = Counter()
    by_contract: dict[
        str, list[tuple[_StatementSummary, dict[str, tuple[Decimal, Decimal]]]]
    ] = defaultdict(list)
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
            summary = _statement_summary(raw)
            positions, document_counts = _equity_quantity_bridge(raw, summary)
        except (OSError, IntakeError):
            counts["quantity_review_required"] += 1
            continue
        counts.update(document_counts)
        by_contract[summary.contract].append((summary, positions))
    for statements in by_contract.values():
        ordered = sorted(statements, key=lambda item: item[0].end)
        if len({summary.end for summary, _ in ordered}) != len(ordered):
            counts["duplicate_contract_cuts"] += 1
            continue
        for (previous, prior_positions), (current, current_positions) in zip(
            ordered, ordered[1:], strict=False,
        ):
            if previous.end != current.start:
                counts["nonadjacent_periods"] += 1
                continue
            if prior_positions or current_positions:
                counts["quantity_pairs_with_equity"] += 1
            for key, (opening, _) in current_positions.items():
                prior_closing = prior_positions.get(key, (Decimal("0"), Decimal("0")))[1]
                counts["equity_quantity_continuity_exact" if opening == prior_closing
                       else "equity_quantity_continuity_different"] += 1
            for key, (_, prior_closing) in prior_positions.items():
                if key not in current_positions and prior_closing != 0:
                    counts["equity_position_missing_next_cut"] += 1
    blockers = (
        "quantity_review_required", "symlink_rejected", "duplicate_contract_cuts",
        "nonadjacent_periods", "equity_quantity_continuity_different",
        "equity_position_missing_next_cut",
    )
    status = "REVIEW_REQUIRED" if not counts["quantity_documents_checked"] or any(
        counts[key] for key in blockers
    ) else "EXACT"
    return {
        "quantity_status": status,
        "quantity_checks": dict(sorted(counts.items())),
        "caution": "Sólo compara títulos visibles y compraventas identificables. No prueba operaciones "
                   "omitidas, eventos corporativos ni identidad definitiva de los instrumentos.",
    }


def inspect_xml(raw: bytes) -> dict[str, object]:
    """Classify CFDI XML without returning taxpayer or transaction content."""
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise IntakeError("El XML está vacío o excede el tamaño permitido.")
    if b"\x00" in raw:
        raise IntakeError("El XML usa una codificación no admitida.")
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


_CFDI_NUMBER = re.compile(r"\d{1,18}(?:\.\d{1,6})?")


def _cfdi_amount(node: ElementTree.Element, name: str, *, optional: bool = False) -> Decimal:
    value = node.get(name)
    if value is None and optional:
        return Decimal(0)
    if value is None or not _CFDI_NUMBER.fullmatch(value):
        raise IntakeError("El CFDI tiene un importe ausente o no reconocible.")
    return Decimal(value)


def _cfdi_amount_sum(nodes: list[ElementTree.Element], name: str) -> Decimal:
    return sum((_cfdi_amount(node, name) for node in nodes), Decimal(0))


def _cfdi_arithmetic(raw: bytes) -> Counter:
    """Check visible CFDI equations, keeping every monetary value private."""
    metadata = inspect_xml(raw)
    if (metadata["cfdi_type"] not in {"I", "E"} or metadata["currency"] != "MXN"
            or metadata["cfdi_version"] not in {"3.3", "4.0"}):
        raise IntakeError("El CFDI tiene un tipo, moneda o versión fuera del control aritmético.")
    root = ElementTree.fromstring(raw)
    namespace = root.tag.split("}", 1)[0] + "}"
    concepts_node = root.find(f"{namespace}Conceptos")
    concepts = [] if concepts_node is None else concepts_node.findall(f"{namespace}Concepto")
    if not concepts:
        raise IntakeError("El CFDI no tiene conceptos reconocibles.")
    taxes = root.find(f"{namespace}Impuestos")
    transfers = [] if taxes is None else [item for item in taxes.findall(
        f"{namespace}Traslados/{namespace}Traslado") if item.get("TipoFactor") != "Exento"]
    withholdings = [] if taxes is None else taxes.findall(
        f"{namespace}Retenciones/{namespace}Retencion")
    concept_transfers = [item for concept in concepts for item in concept.findall(
        f"{namespace}Impuestos/{namespace}Traslados/{namespace}Traslado")
        if item.get("TipoFactor") != "Exento"]
    concept_withholdings = [item for concept in concepts for item in concept.findall(
        f"{namespace}Impuestos/{namespace}Retenciones/{namespace}Retencion")]
    subtotal = _cfdi_amount(root, "SubTotal")
    discount = _cfdi_amount(root, "Descuento", optional=True)
    total = _cfdi_amount(root, "Total")
    transferred = (
        _cfdi_amount(taxes, "TotalImpuestosTrasladados", optional=True)
        if taxes is not None else Decimal(0)
    )
    withheld = (
        _cfdi_amount(taxes, "TotalImpuestosRetenidos", optional=True)
        if taxes is not None else Decimal(0)
    )
    concept_discount = sum(
        (_cfdi_amount(concept, "Descuento", optional=True) for concept in concepts), Decimal(0),
    )
    equations = {
        "subtotal": _cfdi_amount_sum(concepts, "Importe") - subtotal,
        "discount": concept_discount - discount,
        "transfers_global": _cfdi_amount_sum(transfers, "Importe") - transferred,
        "transfers_concepts": _cfdi_amount_sum(concept_transfers, "Importe") - transferred,
        "withholdings_global": _cfdi_amount_sum(withholdings, "Importe") - withheld,
        "withholdings_concepts": _cfdi_amount_sum(concept_withholdings, "Importe") - withheld,
        "total": subtotal - discount + transferred - withheld - total,
    }
    counts = Counter(f"{name}_{_difference_kind(value)}" for name, value in equations.items())
    counts["zero_total_documents" if total == 0 else "positive_total_documents"] += 1
    return counts


def check_cfdi_arithmetic(root: Path) -> dict[str, object]:
    """Summarize CFDI arithmetic without exposing amounts or identifiers."""
    if not root.is_dir() or root.is_symlink():
        raise IntakeError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    try:
        files = sorted(root.rglob("*"))
    except OSError as exc:
        raise IntakeError("No se pudo enumerar la carpeta local.") from exc
    counts = Counter()
    fingerprints: set[str] = set()
    for path in files:
        try:
            if path.is_symlink():
                counts["symlink_rejected"] += 1
                continue
            if not path.is_file() or path.suffix.lower() != ".xml":
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise IntakeError("El XML excede el tamaño permitido.")
            raw = path.read_bytes()
            digest = sha256(raw).hexdigest()
            if digest in fingerprints:
                counts["exact_duplicates"] += 1
                continue
            fingerprints.add(digest)
            checks = _cfdi_arithmetic(raw)
        except (OSError, IntakeError):
            counts["parse_failures"] += 1
            continue
        counts["documents_checked"] += 1
        counts.update(checks)
    if not counts["documents_checked"] or any(counts[key] for key in (
        "symlink_rejected", "exact_duplicates", "parse_failures",
    )) or any(key.endswith("_over_cent") and value for key, value in counts.items()):
        status = "REVIEW_REQUIRED"
    elif any(key.endswith("_one_cent") and value for key, value in counts.items()):
        status = "CENT_DIFFERENCES_NEED_REVIEW"
    else:
        status = "EXACT"
    return {
        "cfdi_arithmetic_status": status,
        "cfdi_checks": dict(sorted(counts.items())),
        "caution": "Sólo comprueba ecuaciones impresas en CFDI MXN de ingreso o egreso. "
                   "Un total cero no acredita un cargo en ese CFDI. No verifica timbrado, tratamiento "
                   "fiscal, vínculo con contrato ni cargos del PDF.",
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
    parser.add_argument(
        "--check-detail-totals", action="store_true",
        help="Comprueba totales de detalle y grupos de renta variable sin mostrar importes.",
    )
    parser.add_argument(
        "--check-cash-ledger", action="store_true",
        help="Comprueba saldos corridos del libro de efectivo sin mostrar operaciones.",
    )
    parser.add_argument(
        "--check-equity-quantities", action="store_true",
        help="Concilia cantidades visibles de renta variable entre posiciones, operaciones y cortes.",
    )
    parser.add_argument(
        "--check-movement-days", action="store_true",
        help="Revisa la plausibilidad de los dos días impresos en cada movimiento.",
    )
    parser.add_argument(
        "--check-equity-trade-costs", action="store_true",
        help="Concilia cantidad, precio, comisión, impuesto y neto de compraventas visibles.",
    )
    parser.add_argument(
        "--check-reporto-net", action="store_true",
        help="Concilia netos impresos de compras y vencimientos de reporto visibles.",
    )
    parser.add_argument(
        "--check-reporto-pairs", action="store_true",
        help="Empareja compras y vencimientos de reporto por contrato, clave y plazo impresos.",
    )
    parser.add_argument(
        "--check-cfdi-arithmetic", action="store_true",
        help="Comprueba subtotales, descuentos, impuestos y total impresos en CFDI MXN.",
    )
    arguments = parser.parse_args()
    check_reporto = arguments.check_reporto_net or arguments.check_reporto_pairs
    check_cash = (arguments.check_cash_ledger or arguments.check_equity_quantities
                  or arguments.check_movement_days or arguments.check_equity_trade_costs
                  or check_reporto)
    check_detail = arguments.check_detail_totals or check_cash
    check_cover = arguments.check_summaries or check_detail
    try:
        result = scan_folder(arguments.folder)
        if check_cover:
            result["cover_summary"] = check_statement_summaries(arguments.folder)
        if check_detail:
            result["detail_summary"] = check_statement_detail_totals(arguments.folder)
        if check_cash:
            result["cash_ledger"] = check_statement_cash_ledgers(arguments.folder)
        if arguments.check_equity_quantities:
            result["equity_quantities"] = check_statement_equity_quantities(arguments.folder)
        if arguments.check_movement_days:
            result["movement_days"] = check_statement_movement_dates(arguments.folder)
        if arguments.check_equity_trade_costs:
            result["equity_trade_costs"] = check_statement_equity_trade_costs(arguments.folder)
        if check_reporto:
            result["reporto_net"] = check_statement_reporto_net(arguments.folder)
        if arguments.check_reporto_pairs:
            result["reporto_pairs"] = check_statement_reporto_pairs(arguments.folder)
        if arguments.check_cfdi_arithmetic:
            result["cfdi_arithmetic"] = check_cfdi_arithmetic(arguments.folder)
    except IntakeError as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    cfdi_needs_review = (arguments.check_cfdi_arithmetic
                         and result["cfdi_arithmetic"]["cfdi_arithmetic_status"] != "EXACT")
    pdf_needs_review = check_cover and (
        result["cover_summary"]["cover_status"] != "EXACT" or result["failures"]
        or (check_detail and result["detail_summary"]["detail_status"] != "EXACT")
        or (check_cash and result["cash_ledger"]["cash_status"] != "EXACT")
        or (arguments.check_equity_quantities
            and result["equity_quantities"]["quantity_status"] != "EXACT")
        or (arguments.check_movement_days
            and result["movement_days"]["date_status"] != "STRUCTURALLY_PLAUSIBLE")
        or (arguments.check_equity_trade_costs
            and result["equity_trade_costs"]["trade_cost_status"] not in
            {"EXACT", "NO_EQUITY_TRADES"})
        or (check_reporto
            and result["reporto_net"]["reporto_status"] not in {"EXACT", "NO_REPORTO_ROWS"})
        or (arguments.check_reporto_pairs
            and result["reporto_pairs"]["pair_status"] not in
            {"STRUCTURALLY_PLAUSIBLE", "NO_REPORTO_ROWS"})
    )
    if cfdi_needs_review or pdf_needs_review:
        parser.exit(3)


if __name__ == "__main__":
    main()
