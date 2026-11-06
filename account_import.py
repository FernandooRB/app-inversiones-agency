"""Reviewed import of the observed GBM XLSX snapshot, preserving row provenance."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from portfolio_core import PortfolioError, normalize_tickers
from scripts.inspect_gbm_portfolio_xlsx import _fold, _number, inspect_portfolio_xlsx

CENT = Decimal("0.01")


@dataclass(frozen=True)
class ImportDraft:
    rows: pd.DataFrame
    cash: Decimal
    fingerprint: str
    source_format: str = "GBM_XLSX_CAPITALES_V1"


def read_gbm_draft(contents: bytes) -> ImportDraft:
    """The existing preflight checks ZIP bounds, formulas, layout and duplicate labels."""
    inspect_portfolio_xlsx(contents)
    book = load_workbook(BytesIO(contents), read_only=True, data_only=False, keep_links=False)
    try:
        rows, cash, in_cash = [], Decimal(0), False
        for number, values in enumerate(book.worksheets[0].iter_rows(values_only=True), 1):
            label = _fold(values[0])
            if label == "efectivo":
                in_cash = True
                continue
            if not label or label in {"emisora/fondo", "mercado de capitales nacional"}:
                continue
            quantity, price, value = (_number(values[index]) for index in (1, 3, 5))
            if value != value.quantize(CENT):
                raise PortfolioError("La valuación debe estar expresada al centavo.")
            if in_cash:
                cash += value
            else:
                calculated = (quantity * price).quantize(CENT, rounding=ROUND_HALF_UP)
                rows.append(
                    {
                        "Fila": number,
                        "Etiqueta original": str(values[0]).strip(),
                        "Instrumento": "",
                        "Cantidad": str(quantity),
                        "Precio": str(price),
                        "Valor MXN": str(value),
                        "Diferencia MXN": str(value - calculated),
                    }
                )
        return ImportDraft(pd.DataFrame(rows), cash, sha256(contents).hexdigest())
    finally:
        book.close()


def confirm_gbm_draft(draft, mapping, as_of, statement_total, *, currency_confirmed):
    if type(as_of) is not date or as_of > date.today():
        raise PortfolioError("Confirma una fecha de corte válida, sin inferirla del nombre del archivo.")
    if not currency_confirmed:
        raise PortfolioError("Confirma que las valuaciones y el efectivo del libro están en MXN.")
    if set(mapping.columns) != {"Fila", "Instrumento"} or len(mapping) != len(draft.rows):
        raise PortfolioError("Resuelve todas las filas del documento antes de continuar.")
    if mapping["Fila"].duplicated().any() or set(mapping["Fila"]) != set(draft.rows["Fila"]):
        raise PortfolioError("La correspondencia con las filas originales cambió.")
    by_row = mapping.set_index("Fila")["Instrumento"].reindex(draft.rows["Fila"])
    if any(not isinstance(value, str) or not value.strip() for value in by_row):
        raise PortfolioError("Cada fila necesita un instrumento confirmado, sin celdas vacías.")
    labels = [str(value).strip().upper() for value in by_row]
    assets = tuple(normalize_tickers(labels))
    if len(assets) != len(labels) or any(not value for value in labels):
        raise PortfolioError("Cada fila necesita un instrumento único, sin posiciones sin clasificar.")
    if any(Decimal(value) != 0 for value in draft.rows["Diferencia MXN"]):
        raise PortfolioError("Hay diferencias entre cantidad × precio y valuación; revisa el original.")
    total = sum((Decimal(value) for value in draft.rows["Valor MXN"]), Decimal(0))
    try:
        declared = Decimal(str(statement_total))
        if not declared.is_finite() or declared <= 0 or declared != declared.quantize(CENT):
            raise ValueError
    except (ValueError, ArithmeticError):
        raise PortfolioError("Declara el total de cuenta en MXN con hasta dos decimales.") from None
    if total <= 0 or total + draft.cash != declared:
        raise PortfolioError(
            "La suma de posiciones y efectivo no coincide al centavo con el total declarado."
        )
    holdings = pd.DataFrame(
        {"FechaCorte": as_of.isoformat(), "Instrumento": labels, "ValorMXN": draft.rows["Valor MXN"].tolist()}
    )
    provenance = draft.rows.copy()
    provenance["Instrumento"] = labels
    return {
        "holdings": holdings.to_csv(index=False).encode("utf-8-sig"),
        "cash_mxn": str(draft.cash),
        "account_total_mxn": str(declared),
        "as_of": as_of.isoformat(),
        "assets": list(assets),
        "source_sha256": draft.fingerprint,
        "source_format": draft.source_format,
        "reviewed_rows": provenance.to_dict(orient="records"),
        "currency_confirmed": True,
        "date_declaration_only": True,
    }
