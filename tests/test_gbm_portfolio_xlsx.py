"""Synthetic examples for GBM's observed portfolio snapshot layout."""

from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from openpyxl import Workbook

from scripts.inspect_gbm_portfolio_xlsx import PortfolioXlsxError, inspect_portfolio_xlsx

HEADER = [
    "Emisora/Fondo", "Títulos", "Costo promedio", "Precio mercado", "PPP",
    "Valor mercado", "P / M", "% Var. Hist.", "% Var. Dia.", "Imp X Cto",
    "% Cartera",
]


def portfolio_book(*, duplicate=False, formula=False, extra_column=False) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "App GBM Portfolio"
    sheet.append(["Mercado de Capitales Nacional"])
    sheet.append(HEADER)
    sheet.append(["SYNTHETIC A", 2, "$10.00", "$11.00", "$10.00", "$22.00",
                  "$2.00", "-", "0.00%", "-", "68.75%"])
    sheet.append(["SYNTHETIC A" if duplicate else "SYNTHETIC B", 1, "$9.00",
                  "$9.00", "$9.00", "$9.00", "$0.00", "-", "0.00%", "-", "28.13%"])
    sheet.append(["Efectivo"])
    sheet.append(HEADER)
    sheet.append(["EFEC. MISMO DIA", 1, "$1.00", "$1.00", "$1.00", "$1.00",
                  "$0.00", "-", "0.00%", "-", "3.12%"])
    if formula:
        sheet["F3"] = "=B3*D3"
    if extra_column:
        sheet["L3"] = "PRIVATE_CANARY"
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def test_snapshot_preflight_returns_no_labels_or_values_and_claims_no_proof():
    raw = portfolio_book()
    result = inspect_portfolio_xlsx(raw)

    assert result["status"] == "ESTRUCTURA_PLAUSIBLE_NO_AUTENTICADA"
    assert result["sha256"] == sha256(raw).hexdigest()
    assert result["position_rows"] == 2
    assert result["cash_rows"] == 1
    assert result["contains_movements"] is False
    assert result["as_of_date_verified"] is False
    assert result["account_verified"] is False
    assert "SYNTHETIC" not in str(result)
    assert "$22.00" not in str(result)


@pytest.mark.parametrize("change", [
    {"duplicate": True}, {"formula": True}, {"extra_column": True},
])
def test_snapshot_preflight_rejects_unsafe_or_ambiguous_content(change):
    with pytest.raises(PortfolioXlsxError) as caught:
        inspect_portfolio_xlsx(portfolio_book(**change))
    assert "SYNTHETIC" not in str(caught.value)
    assert "PRIVATE_CANARY" not in str(caught.value)


def test_snapshot_preflight_rejects_invalid_xlsx_without_echoing_bytes():
    with pytest.raises(PortfolioXlsxError, match="XLSX válido"):
        inspect_portfolio_xlsx(b"PRIVATE_CANARY_NOT_AN_XLSX")


def test_snapshot_preflight_rejects_oversized_uncompressed_archive():
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", b"A" * 15_000_001)
    with pytest.raises(PortfolioXlsxError, match="límite de contenido"):
        inspect_portfolio_xlsx(stream.getvalue())
