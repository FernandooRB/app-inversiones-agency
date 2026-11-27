"""Independent synthetic evidence for market observation comparisons."""

import csv
from io import StringIO

import pytest

from portfolio_core import PortfolioError

HEADERS = (
    "Tipo",
    "Fecha",
    "Serie",
    "Mercado",
    "Moneda",
    "Unidad",
    "Metodo",
    "Corte",
    "PlazoDias",
    "BaseDias",
    "Valor",
    "Proveedor",
    "Origen",
    "Evidencia",
)
PRICE = (
    "PRECIO",
    "2026-01-08",
    "SIM-A",
    "SIM-X",
    "MXN",
    "POR_TITULO",
    "Cierre sin ajuste",
    "2026-01-08T15:00:00-06:00",
    "",
    "",
    "100.01",
    "Mesa A",
    "Origen A",
    "Documento ficticio A",
)
FX = (
    "FX",
    "2026-01-08",
    "USD/MXN",
    "SIM-X",
    "MXN",
    "MXN_POR_USD",
    "Cierre simulado spot",
    "2026-01-08T15:00:00-06:00",
    "",
    "",
    "20.04",
    "Mesa A",
    "Origen A",
    "Documento ficticio A",
)
RATE = (
    "TASA",
    "2026-01-08",
    "CETE-SIM",
    "SIM-X",
    "MXN",
    "PORCENTAJE_ANUAL",
    "Rendimiento subasta",
    "2026-01-08T10:00:00-06:00",
    "28",
    "360",
    "7.05",
    "Mesa A",
    "Origen A",
    "Documento ficticio A",
)


def file(*rows):
    buf = StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return buf.getvalue().encode()


def alternate(row, **changes):
    values = dict(zip(HEADERS, row, strict=True))
    values.update(Proveedor="Mesa B", Origen="Origen B", Evidencia="Documento ficticio B")
    values.update(changes)
    return tuple(values[name] for name in HEADERS)


def compare(primary, reference, **tolerance):
    from operations_market_review import compare_observations

    return compare_observations(primary, reference, {"PRECIO": "1", "FX": "10", "TASA": "5"} | tolerance)


def test_exact_differences_and_distinct_bps_denominators():
    result = compare(
        file(PRICE, FX, RATE),
        file(alternate(PRICE, Valor="100"), alternate(FX, Valor="20"), alternate(RATE, Valor="7.00")),
    )
    rows = {r["type"]: r for r in result["rows"]}
    assert (rows["PRECIO"]["delta"], rows["PRECIO"]["bps"], rows["PRECIO"]["state"]) == (
        "0.01",
        "1",
        "DENTRO",
    )
    assert (rows["FX"]["delta"], rows["FX"]["bps"], rows["FX"]["state"]) == ("0.04", "20", "DIFERENCIA")
    assert (rows["TASA"]["delta"], rows["TASA"]["bps"], rows["TASA"]["state"]) == ("0.05", "5", "DENTRO")
    assert rows["PRECIO"]["primary"]["Valor"] == "100.01"
    assert len(result["inputs"]["primary_sha256"]) == 64


@pytest.mark.parametrize(
    ("row", "change", "field"),
    [
        (PRICE, {"Metodo": "Cierre ajustado"}, "Metodo"),
        (PRICE, {"Mercado": "OTRO"}, "Mercado"),
        (PRICE, {"Moneda": "USD"}, "Moneda"),
        (FX, {"Corte": "2026-01-08T12:00:00-06:00"}, "Corte"),
        (RATE, {"PlazoDias": "91"}, "PlazoDias"),
        (RATE, {"BaseDias": "365"}, "BaseDias"),
        (PRICE, {"Origen": "  ORIGEN   A "}, "Origen"),
        (PRICE, {"Proveedor": " MESA A "}, "Proveedor"),
        (PRICE, {"Evidencia": "Documento ficticio A"}, "Evidencia"),
    ],
)
def test_incompatible_rows_keep_evidence_without_numeric_difference(row, change, field):
    item = compare(file(row), file(alternate(row, **change)))["rows"][0]
    assert item["state"] == "NO_COMPARABLE" and field in item["reasons"]
    assert item["delta"] is None and item["bps"] is None
    assert item["reference"]["Valor"] == row[10]


def test_equal_instants_across_offsets_and_missing_dates_without_fill():
    same = alternate(PRICE, Corte="2026-01-08T21:00:00+00:00")
    other_day = alternate(FX, Fecha="2026-01-09", Corte="2026-01-09T15:00:00-06:00")
    result = compare(file(PRICE, FX), file(same, other_day))
    assert {r["state"] for r in result["rows"]} == {"IGUAL", "FALTA_REFERENCIA", "FALTA_PRINCIPAL"}
    assert result["coverage"]["FX"] == {"union": 2, "paired": 0, "comparable": 0}


def test_no_implicit_equivalence_for_series_identifiers():
    result = compare(file(PRICE), file(alternate(PRICE, Serie="SIM-ª")))
    assert {r["state"] for r in result["rows"]} == {"FALTA_PRINCIPAL", "FALTA_REFERENCIA"}


def test_threshold_uses_exact_decimal_even_when_display_rounds():
    raw = file(alternate(PRICE, Valor="100.010000000001"))
    alternate_source = alternate(
        PRICE, Valor="100", Proveedor="Mesa C", Origen="Origen C", Evidencia="Ficticio C"
    )
    result = compare(raw, file(alternate_source))
    assert result["rows"][0]["state"] == "DIFERENCIA"


@pytest.mark.parametrize(
    "change",
    [
        {"Valor": "NaN"},
        {"Valor": "1e12"},
        {"Valor": "0"},
        {"Fecha": "2099-01-01"},
        {"Serie": "=malicioso"},
        {"Metodo": "  "},
        {"Corte": "2026-01-08T15:00:00"},
        {"Corte": "2026-01-08T15:00:00-05:60"},
        {"Corte": "2026-01-08T15:00:00-00:00"},
        {"Corte": "2026-01-09T15:00:00-06:00"},
        {"Evidencia": ""},
        {"Evidencia": "N/D"},
        {"Origen": "Desconocido"},
        {"Metodo": "Sin dato"},
        {"PlazoDias": "28"},
    ],
)
def test_bad_values_fail_without_echoing_submitted_value(change):
    with pytest.raises(PortfolioError, match=r"Principal.*fila 2"):
        compare(file(alternate(PRICE, **change)), file(alternate(PRICE)))


def test_duplicate_identity_is_rejected_and_negative_rates_are_allowed():
    with pytest.raises(PortfolioError, match="repetida"):
        compare(file(PRICE, PRICE), file(alternate(PRICE)))
    result = compare(file(alternate(RATE, Valor="-0.05")), file(alternate(RATE, Valor="0", Origen="C")))
    assert result["rows"][0]["bps"] is None  # Both rows declare the same distributor.
    result = compare(
        file(alternate(RATE, Valor="-0.05")),
        file(alternate(RATE, Valor="0", Origen="C", Proveedor="C", Evidencia="Ficticio C")),
    )
    assert result["rows"][0]["bps"] == "-5"
