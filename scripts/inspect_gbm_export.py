"""Privacy-preserving structural preflight for the observed GBM movement CSV format.

Only counts and SHA-256 fingerprints leave this module. It does not reconcile or import operations.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter
from datetime import date, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
from pathlib import Path

MAX_CSV_BYTES = 20_000_000
MONTHS = {name: number for number, name in enumerate(
    ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"), 1,
)}
HEADER_TERMS = (
    "emisora", "fecha", "hora", "descripcion", "titulos", "precio", "tasa", "plazo",
    "interes", "impuesto", "comision", "importe", "saldo",
)
NUMBER = re.compile(r"\$?(?:-?\d{1,3}(?:,\d{3})+|-?\d+)(?:\.\d+)?\Z")
DATE = re.compile(r"(\d{2})/([A-Z]{3})/(\d{4})\Z")
TIME = re.compile(r"\d{2}:\d{2}:\d{2}\Z")


class ExportError(ValueError):
    """A structural error; its message must not contain source values."""


def _fold(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKD", value.lower())
                   if not unicodedata.combining(character))


def _number(value: str) -> Decimal:
    token = value.strip()
    if not NUMBER.fullmatch(token):
        raise ExportError("Una columna numérica tiene un formato no reconocido.")
    try:
        return Decimal(token.replace("$", "").replace(",", ""))
    except InvalidOperation as exc:
        raise ExportError("Una columna numérica no es válida.") from exc


def _day(value: str) -> date:
    match = DATE.fullmatch(value.strip().upper())
    if not match or match[2] not in MONTHS:
        raise ExportError("Una fecha tiene un formato no reconocido.")
    try:
        return date(int(match[3]), MONTHS[match[2]], int(match[1]))
    except ValueError as exc:
        raise ExportError("Una fecha no es válida.") from exc


def _kind(value: str) -> str:
    text = _fold(value)
    buy = "compra" in text
    sale = "venta" in text
    maturity = "vencimiento" in text
    if sum((buy, sale, maturity)) != 1:
        raise ExportError("Una descripción de operación es desconocida o ambigua.")
    if "reporto" in text:
        if sale:
            raise ExportError("Una operación de reporto tiene tipo no reconocido.")
        return "reporto_buy" if buy else "reporto_maturity"
    if maturity:
        raise ExportError("Un vencimiento sin reporto requiere revisión.")
    return "equity_buy" if buy else "equity_sale"


def inspect_export(raw: bytes) -> dict[str, object]:
    """Validate one observed 13-column CSV without returning private rows or values."""
    if not 0 < len(raw) <= MAX_CSV_BYTES:
        raise ExportError("El CSV está vacío o excede el tamaño permitido.")
    try:
        content = raw.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(content), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ExportError("El CSV no se pudo leer como UTF-8 válido.") from exc
    if not rows or len(rows[0]) != len(HEADER_TERMS) or any(
        term not in _fold(value) for term, value in zip(HEADER_TERMS, rows[0], strict=True)
    ):
        raise ExportError("Los encabezados no corresponden al diseño GBM observado.")
    counts = Counter()
    for row in rows[1:]:
        if len(row) == 1:
            counts["section_rows"] += 1
            continue
        if len(row) != len(HEADER_TERMS):
            raise ExportError("Una fila tiene un número de columnas inesperado.")
        if not row[1].strip():
            if any(value.strip() for value in row[1:]):
                raise ExportError("Una fila sin fecha contiene valores de operación.")
            counts["summary_rows"] += 1
            continue
        _day(row[1])
        if not TIME.fullmatch(row[2].strip()):
            raise ExportError("Una hora tiene un formato no reconocido.")
        try:
            time.fromisoformat(row[2].strip())
        except ValueError as exc:
            raise ExportError("Una hora no es válida.") from exc
        kind = _kind(row[3])
        values = [_number(value) for value in row[4:]]
        quantity, price, rate, term, interest, tax, commission, net, balance = values
        if quantity <= 0 or price <= 0 or net < 0 or any(
            value < 0 for value in (rate, term, interest, tax, commission)
        ):
            raise ExportError("Una operación tiene cantidades o cargos fuera del alcance.")
        if term != term.to_integral_value():
            raise ExportError("Un plazo no es entero.")
        counts[kind] += 1
        counts["operation_rows"] += 1
        counts["balance_zero_rows"] += balance == 0
        counts["reporto_price_two_decimal_rows"] += (
            kind.startswith("reporto") and price.as_tuple().exponent == -2
        )
    if not counts["operation_rows"]:
        raise ExportError("El CSV no contiene operaciones reconocibles.")
    return {"sha256": sha256(raw).hexdigest(), "checks": dict(sorted(counts.items()))}


def inspect_folder(root: Path) -> dict[str, object]:
    """Count unique CSVs and duplicates; never infer a contract from a folder name."""
    if not root.is_dir() or root.is_symlink():
        raise ExportError("Selecciona una carpeta local válida, sin enlaces simbólicos.")
    counts = Counter()
    unique = {}
    try:
        paths = sorted(root.iterdir())
    except OSError as exc:
        raise ExportError("No se pudo enumerar la carpeta local.") from exc
    for path in paths:
        if path.is_symlink():
            counts["symlink_rejected"] += 1
        elif not path.is_file() or path.suffix.lower() != ".csv":
            counts["other_entries"] += 1
        else:
            counts["csv_files"] += 1
            try:
                if not 0 < path.stat().st_size <= MAX_CSV_BYTES:
                    raise ExportError("El CSV está vacío o excede el tamaño permitido.")
                raw = path.read_bytes()
                digest = sha256(raw).hexdigest()
                if digest in unique:
                    counts["duplicate_csv_files"] += 1
                else:
                    unique[digest] = inspect_export(raw)
            except (OSError, ExportError):
                counts["csv_review_required"] += 1
    if len(unique) != 1 or any(counts[key] for key in (
        "symlink_rejected", "duplicate_csv_files", "csv_review_required",
    )):
        status = "REVIEW_REQUIRED"
    else:
        status = "STRUCTURALLY_PLAUSIBLE"
    return {
        "status": status,
        "file_checks": dict(sorted(counts.items())),
        "unique_exports": [unique[digest] for digest in sorted(unique)],
        "caution": "Sólo revisa la estructura del CSV observado. No comprueba cuenta, "
                   "integridad de operaciones, saldo de efectivo, precio, netos contra PDF "
                   "ni significado de fechas de liquidación.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Revisión local y privada de exportaciones GBM CSV")
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_folder(args.folder)
    except ExportError as exc:
        result = {"status": "REVIEW_REQUIRED", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "STRUCTURALLY_PLAUSIBLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
