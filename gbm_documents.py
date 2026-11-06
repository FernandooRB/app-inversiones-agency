"""Reviewable GBM PDF/CFDI evidence. Reading never posts transactions automatically."""

from collections import Counter
from decimal import Decimal
from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader

from scripts.inspect_gbm_intake import (
    DETAIL_TOTALS,
    IntakeError,
    _cash_ledger_counts,
    _cfdi_arithmetic,
    _detail_differences,
    _equity_key,
    _equity_quantity_bridge,
    _equity_trade_cost_counts,
    _money_values,
    _movement_date_counts,
    _position_columns,
    _reporto_net_counts,
    _statement_summary,
    inspect_xml,
)


def read_statement(raw: bytes) -> dict:
    """Return private values and page provenance for the observed layout only.

    Reconciliation tolerates no unexplained difference: a printed cent remains a
    warning. Dates printed in movement rows are evidence, not settlement claims.
    """
    summary = _statement_summary(raw)  # validates size, wrapper and page count
    differences, detail_counts = _detail_differences(raw, summary)
    quantities, quantity_counts = _equity_quantity_bridge(raw, summary)
    checks = Counter(detail_counts)
    checks.update(quantity_counts)
    checks.update(_cash_ledger_counts(raw, summary))
    checks.update(_movement_date_counts(raw, summary))
    checks.update(_equity_trade_cost_counts(raw))
    checks.update(_reporto_net_counts(raw))
    reader = PdfReader(BytesIO(raw[raw.find(b"%PDF-") :]), strict=True)
    rows, candidates = [], []
    in_equity = False
    for page_number, page in enumerate(reader.pages[1:], start=2):
        for line_number, text in enumerate((page.extract_text() or "").splitlines(), start=1):
            text = text.strip()
            if text.upper() == "RENTA VARIABLE":
                in_equity = True
            if DETAIL_TOTALS["equity"].search(text):
                in_equity = False
            if in_equity and not text.upper().startswith("TOTAL:") and len(_money_values(text)) == 4:
                columns = _position_columns(text)
                rows.append(
                    {
                        "Instrumento": _equity_key(text),
                        "CantidadAnterior": str(columns[0]),
                        "Cantidad": str(columns[1]),
                        "PrecioSinAjustar": str(columns[5]),
                        "Valor": str(columns[7]),
                        "Pagina": page_number,
                        "Fila": line_number,
                    }
                )
            from scripts.inspect_gbm_intake import CASH_MOVEMENT_DAY_PAIR

            if CASH_MOVEMENT_DAY_PAIR.match(text):
                candidates.append(
                    {
                        "Pagina": page_number,
                        "Fila": line_number,
                        "Texto": text,
                        "Estado": "REQUIERE_REVISION",
                        "sha256": sha256(text.encode()).hexdigest(),
                    }
                )
    if len(rows) != len(quantities):
        raise IntakeError("No se reprodujeron todas las posiciones visibles del documento.")
    other = summary.closing_total - summary.closing_categories[1] - summary.closing_categories[7]
    warnings = []
    if any(differences.values()) or summary.opening_difference or summary.closing_difference:
        warnings.append(
            "Diferencia impresa de totales; requiere aceptación documentada, sin ajustar valores."
        )
    if any(value for key, value in checks.items() if "one_cent" in key):
        warnings.append("Hay transiciones impresas con diferencia de un centavo.")
    if other:
        warnings.append("Hay categorías fuera de capitales y efectivo; la cartera normalizada es parcial.")
    return {
        "schema": 1,
        "sha256": sha256(raw).hexdigest(),
        "contract": summary.contract,
        "start": summary.start.isoformat(),
        "end": summary.end.isoformat(),
        "opening_total": str(summary.opening_total),
        "closing_total": str(summary.closing_total),
        "cash": str(summary.closing_categories[7]),
        "equity": str(summary.closing_categories[1]),
        "other": str(other),
        "currency": "MXN",
        "currency_requires_confirmation": True,
        "positions": rows,
        "movement_candidates": candidates,
        "checks": dict(sorted(checks.items())),
        "warnings": warnings,
        "status": "REQUIERE_REVISION",
    }


def read_cfdi_evidence(raw: bytes) -> dict:
    """Validate arithmetic without interpreting a CFDI as a second cash debit."""
    classification = inspect_xml(raw)  # rejects DTD/entity, invalid structure and oversized input
    checks = _cfdi_arithmetic(raw)
    if any(value for key, value in checks.items() if key.endswith("different")):
        raise IntakeError("La aritmética del comprobante requiere revisión.")
    return {
        **classification,
        "sha256": sha256(raw).hexdigest(),
        "checks": dict(checks),
        "status": "EVIDENCIA_NO_CONTABILIZADA",
        "notice": "Vincula el comprobante con un cargo existente antes de registrar importes; "
        "evita duplicarlo.",
    }


def confirm_statement(
    draft: dict,
    *,
    contract_confirmed: bool,
    currency_confirmed: bool,
    differences_accepted: bool,
    mapping: dict[str, str],
) -> bytes:
    """Produce account-analysis CSV after explicit identity, MXN and mapping review."""
    import csv
    from io import StringIO

    if not contract_confirmed or not currency_confirmed:
        raise IntakeError("Confirma cuenta y moneda contra el documento original.")
    if Decimal(draft["other"]) != 0:
        raise IntakeError("Faltan categorías por normalizar; no se puede declarar una cartera completa.")
    if draft["warnings"] and not differences_accepted:
        raise IntakeError("Las diferencias impresas requieren una aceptación explícita.")
    symbols = [mapping.get(row["Instrumento"], "").strip().upper() for row in draft["positions"]]
    if not symbols or any(not symbol for symbol in symbols) or len(set(symbols)) != len(symbols):
        raise IntakeError("Confirma una correspondencia única por posición.")
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["FechaCorte", "Instrumento", "ValorMXN"])
    for symbol, row in zip(symbols, draft["positions"], strict=True):
        if len(symbol) > 40 or symbol[0] in "=+-@" or any(ord(c) < 33 for c in symbol):
            raise IntakeError("La correspondencia del instrumento no es válida.")
        writer.writerow([draft["end"], symbol, row["Valor"]])
    return buffer.getvalue().encode("utf-8")
