"""Exact closing controls for a single-account ledger, without postings or corrections."""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import StringIO

from portfolio_core import PortfolioError
from transaction_ledger import decimal

COLUMNS = ("Fecha", "Tipo", "InstrumentoReferencia", "Moneda", "Saldo", "Fuente")
SECTIONS = {"CASH": "cash", "PENDING": "pending", "POSITION": "positions", "REPO": "repos"}


@dataclass(frozen=True)
class ClosingControl:
    day: date
    kind: str
    item: str
    currency: str
    balance: Decimal
    source: str

    def __post_init__(self):
        object.__setattr__(self, "balance", decimal(self.balance))
        if not isinstance(self.day, date) or self.kind not in SECTIONS or self.currency not in {"MXN", "USD"}:
            raise PortfolioError("El control de cierre requiere fecha, tipo y moneda MXN/USD válidos.")
        if (
            not isinstance(self.item, str) or len(self.item) > 160
            or any(ord(c) < 32 for c in self.item)
            or not isinstance(self.source, str) or not self.source.strip() or len(self.source) > 1000
            or any(ord(c) < 32 for c in self.source)
        ):
            raise PortfolioError("El control requiere una fuente y un identificador válidos.")
        if self.kind in {"CASH", "PENDING"} and self.item:
            raise PortfolioError("El control de efectivo se identifica por moneda, sin instrumento.")
        if self.kind in {"POSITION", "REPO"} and (not self.item.strip() or self.balance < 0):
            raise PortfolioError(
                "El control de títulos o capital de reporto requiere referencia y saldo no negativo."
            )


def read_closing_controls(raw: bytes, cutoff: date) -> tuple[ClosingControl, ...]:
    if not 0 < len(raw) <= 2_000_000:
        raise PortfolioError("El archivo de controles está vacío o excede 2 MB.")
    try:
        reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise PortfolioError("Los encabezados no corresponden a la plantilla de controles de cierre.")
        controls = []
        for row in reader:
            if len(controls) >= 20000 or None in row or any(v is None for v in row.values()):
                raise PortfolioError("Los controles tienen filas o columnas fuera del formato.")
            if row["Fecha"] != cutoff.isoformat():
                raise PortfolioError("Todos los controles deben corresponder al cierre elegido.")
            controls.append(
                ClosingControl(
                    cutoff, row["Tipo"], row["InstrumentoReferencia"], row["Moneda"],
                    row["Saldo"], row["Fuente"],
                )
            )
        return _unique_controls(controls, cutoff)
    except (UnicodeError, csv.Error, ValueError) as exc:
        if isinstance(exc, PortfolioError):
            raise
        raise PortfolioError("No se pudieron leer los controles de cierre.") from exc


def _unique_controls(controls, cutoff):
    rows, seen = [], set()
    for row in controls:
        if not isinstance(row, ClosingControl) or row.day != cutoff:
            raise PortfolioError("El control no está normalizado o pertenece a otro cierre.")
        key = row.kind, row.item, row.currency
        if key in seen:
            raise PortfolioError("Hay controles duplicados para el mismo saldo.")
        if len(rows) >= 20000:
            raise PortfolioError("Los controles exceden 20,000 filas.")
        seen.add(key)
        rows.append(row)
    if not rows:
        raise PortfolioError("El archivo no contiene controles de cierre.")
    return tuple(rows)


def reconcile_book(book: dict, controls, *, cutoff: date) -> dict:
    """Compare balances in original units. Missing source controls never mean zero.

    A missing modeled position means zero in this book and can reveal an omitted
    holding. A missing source control remains unknown, even if the book is zero.
    REPO compares principal only; it never establishes a carrying value or NAV.
    """
    controls = _unique_controls(controls, cutoff)
    declared = {(r.kind, r.item, r.currency): r for r in controls}
    modeled = {}
    for kind, section in SECTIONS.items():
        for key, balance in book.get(section, {}).items():
            item, currency = ("", key) if kind in {"CASH", "PENDING"} else key
            modeled[(kind, item, currency)] = decimal(balance)
    rows = []
    for key in sorted(set(modeled) | set(declared)):
        kind, item, currency = key
        control = declared.get(key)
        actual = modeled.get(key, decimal(0))
        expected = control.balance if control else None
        difference = actual - expected if control else None
        if control is not None and difference == 0 and actual != expected:
            raise PortfolioError(
                "La precisión de un saldo excede la comparación disponible; revisa el control."
            )
        status = "SIN_CONTROL" if control is None else "COINCIDE" if actual == expected else "DIFERENCIA"
        rows.append({
            "Tipo": kind, "InstrumentoReferencia": item, "Moneda": currency,
            "Unidad": "títulos" if kind == "POSITION" else currency,
            "Libro": actual, "Control": expected, "Diferencia": difference,
            "Estado": status,
            "Fuente": control.source if control else "",
        })
    differences = sum(row["Estado"] == "DIFERENCIA" for row in rows)
    missing = sum(row["Estado"] == "SIN_CONTROL" for row in rows)
    return {
        "schema": 1, "cutoff": cutoff.isoformat(), "rows": rows,
        "exact": len(rows) - differences - missing, "differences": differences, "missing": missing,
        "status": "REQUIERE_REVISION" if differences or missing else "COINCIDENCIA_ARITMETICA",
        "human_approval": None, "postings_created": 0,
    }
