"""The observed GBM CSV preflight is tested with invented records only."""

import csv
import json
from io import StringIO

import pytest

from scripts.inspect_gbm_export import ExportError, inspect_export, inspect_folder

HEADERS = (
    "Emisora", "Fecha", "Hora", "Descripción", "Títulos", "Precio", "Tasa", "Plazo",
    "Interés", "Impuesto", "Comisión", "Importe", "Saldo",
)
BUY = (
    "SIMBOLO_FICTICIO", "15/ENE/2026", "10:15:30", "COMPRA DE REPORTO", "10", "1.00",
    "8.50", "1", "0.00", "0.00", "0.00", "$10.00", "0.00",
)
MATURITY = (
    "SIMBOLO_FICTICIO", "16/ENE/2026", "11:00:00", "VENCIMIENTO DE REPORTO", "10", "1.01",
    "8.50", "1", "0.10", "0.01", "0.00", "$10.09", "0.00",
)
EQUITY = (
    "ACCION_FICTICIA", "16/ENE/2026", "12:00:00", "COMPRA DE ACCIONES", "2", "20.00",
    "0.00", "0", "0.00", "0.02", "0.10", "$40.12", "0.00",
)


def _csv(*rows):
    stream = StringIO()
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerow(["MOVIMIENTOS FICTICIOS"])
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def test_inspect_export_counts_supported_rows_without_exposing_values():
    result = inspect_export(_csv(BUY, MATURITY, EQUITY))
    assert result["checks"] == {
        "balance_zero_rows": 3,
        "equity_buy": 1,
        "operation_rows": 3,
        "reporto_buy": 1,
        "reporto_maturity": 1,
        "reporto_price_two_decimal_rows": 2,
        "section_rows": 1,
    }
    assert len(result["sha256"]) == 64
    output = json.dumps(result)
    assert "SIMBOLO_FICTICIO" not in output
    assert "ACCION_FICTICIA" not in output
    assert "40.12" not in output


def test_duplicate_exports_are_deduplicated_and_block_approval(tmp_path):
    raw = _csv(BUY)
    (tmp_path / "example.csv").write_bytes(raw)
    (tmp_path / "copy.csv").write_bytes(raw)
    result = inspect_folder(tmp_path)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["file_checks"] == {"csv_files": 2, "duplicate_csv_files": 1}
    assert len(result["unique_exports"]) == 1
    assert result["unique_exports"][0]["checks"]["operation_rows"] == 1


def test_one_valid_export_is_only_structurally_plausible(tmp_path):
    (tmp_path / "example.csv").write_bytes(_csv(BUY))
    assert inspect_folder(tmp_path)["status"] == "STRUCTURALLY_PLAUSIBLE"


def test_distinct_exports_need_scope_review(tmp_path):
    (tmp_path / "first.csv").write_bytes(_csv(BUY))
    (tmp_path / "second.csv").write_bytes(_csv(MATURITY))
    result = inspect_folder(tmp_path)
    assert result["status"] == "REVIEW_REQUIRED"
    assert len(result["unique_exports"]) == 2


@pytest.mark.parametrize(
    "row",
    [
        (*BUY[:1], "31/FEB/2026", *BUY[2:]),
        (*BUY[:2], "25:15:30", *BUY[3:]),
        (*BUY[:3], "OPERACION DESCONOCIDA", *BUY[4:]),
        (*BUY[:4], "-10", *BUY[5:]),
        (*BUY[:11], "=2+2", *BUY[12:]),
    ],
)
def test_invalid_or_unknown_rows_fail_closed_without_echoing_data(row):
    with pytest.raises(ExportError) as caught:
        inspect_export(_csv(row))
    assert "SIMBOLO_FICTICIO" not in str(caught.value)
    assert "=2+2" not in str(caught.value)


def test_unexpected_headers_and_invalid_encoding_fail_closed():
    wrong_headers = _csv(BUY).replace(b"Emisora", b"Cliente")
    with pytest.raises(ExportError):
        inspect_export(wrong_headers)
    with pytest.raises(ExportError):
        inspect_export(b"\xff\xfe\xff")
