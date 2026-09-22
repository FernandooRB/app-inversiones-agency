from datetime import date

import pytest

from holdings import read_current_holdings_csv
from holdings_control import (
    compare_holdings_detail_csv,
    read_holdings_control_csv,
    read_holdings_coverage_csv,
)
from portfolio_core import PortfolioError


def holdings():
    cutoff = date.today().isoformat()
    contents = (
        "FechaCorte,Instrumento,ValorMXN\n"
        f"{cutoff},AAA,60000.001\n"
        f"{cutoff},BBB,39999.999\n"
    ).encode()
    return read_current_holdings_csv(contents, ("AAA", "BBB"))


def control(total="100000.00", *, cutoff=None, source="Estado de cuenta ficticio"):
    cutoff = cutoff or date.today().isoformat()
    return (
        f"FechaCorte,TotalMXN,Fuente\n{cutoff},{total},{source}\n"
    ).encode("utf-8-sig")


def primary_detail():
    cutoff = date.today().isoformat()
    return (
        f"FechaCorte,Instrumento,ValorMXN\n{cutoff},AAA,60000.001\n"
        f"{cutoff},BBB,39999.999\n"
    ).encode()


def statement_detail(first="39999.999", second="60000.001", *, cutoff=None):
    cutoff = cutoff or date.today().isoformat()
    return (
        f"FechaCorte,Instrumento,ValorMXN\n{cutoff},BBB,{first}\n"
        f"{cutoff},AAA,{second}\n"
    ).encode("utf-8-sig")


def coverage(
    analyzed="100000.00",
    cash="5000.00",
    pending="-1000.00",
    other="250.00",
    total="104250.00",
    *,
    cutoff=None,
    source="Estado de cuenta ficticio",
):
    cutoff = cutoff or date.today().isoformat()
    return (
        "FechaCorte,ValorCarteraAnalizadaMXN,EfectivoFueraAnalisisMXN,"
        "PendienteLiquidacionMXN,OtrosFueraAnalisisMXN,TotalCuentaMXN,Fuente\n"
        f"{cutoff},{analyzed},{cash},{pending},{other},{total},{source}\n"
    ).encode("utf-8-sig")


def test_reconciles_account_coverage_without_adding_external_components_to_holdings():
    result = read_holdings_coverage_csv(coverage(), holdings())
    assert result.analyzed_value == 100_000
    assert result.outside_analysis_total == 4_250
    assert result.account_total == 104_250
    assert holdings().total_value == 100_000
    assert len(result.fingerprint) == 64


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (coverage(analyzed="99999.99"), "no coincide con la suma"),
        (coverage(total="104249.99"), "no coincide con cartera"),
        (coverage(cash="-1.00", total="99249.00"), "EfectivoFueraAnalisisMXN"),
        (coverage(total="0.00", cash="0", pending="-100000", other="0"), "debe ser positivo"),
        (coverage(cutoff="2020-01-01"), "fecha.*no coincide"),
        (coverage(source="=FORMULA()"), "fórmulas CSV"),
    ],
)
def test_rejects_inconsistent_or_unsafe_account_coverage(contents, message):
    with pytest.raises(PortfolioError, match=message):
        read_holdings_coverage_csv(contents, holdings())


def test_reconciles_each_instrument_from_separately_prepared_detail():
    result = compare_holdings_detail_csv(statement_detail(), holdings(), primary_detail())
    assert result.as_of == date.today()
    assert result.asset_count == 2
    assert len(result.fingerprint) == 64


def test_rejects_offsetting_instrument_errors_even_when_total_matches():
    with pytest.raises(PortfolioError, match="AAA, BBB|BBB, AAA"):
        compare_holdings_detail_csv(
            statement_detail("49999.999", "50000.001"), holdings(), primary_detail()
        )


def test_rejects_identical_file_as_reference_and_wrong_cutoff():
    with pytest.raises(PortfolioError, match="idéntico"):
        compare_holdings_detail_csv(primary_detail(), holdings(), primary_detail())
    with pytest.raises(PortfolioError, match="fecha.*no coincide"):
        compare_holdings_detail_csv(
            statement_detail(cutoff="2020-01-01"), holdings(), primary_detail()
        )


def test_reconciles_statement_total_at_cent_precision_and_keeps_fingerprint():
    result = read_holdings_control_csv(control(), holdings())
    assert result.as_of == date.today()
    assert result.statement_total == result.calculated_total
    assert str(result.statement_total) == "100000.00"
    assert len(result.fingerprint) == 64


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (control("100000.01"), "no coincide"),
        (control("100000.000"), "hasta dos decimales"),
        (control("1000000000000000000.00"), "hasta dos decimales"),
        (control("0"), "positivo"),
        (control(cutoff="2020-01-01"), "fecha.*no coincide"),
        (control(source="=FORMULA()"), "fórmulas CSV"),
        (b"FechaCorte,TotalMXN,Fuente,Cuenta\n2026-01-15,100000,Ejemplo,123\n", "una fila"),
    ],
)
def test_rejects_mismatched_or_unsafe_statement_control(contents, message):
    with pytest.raises(PortfolioError, match=message):
        read_holdings_control_csv(contents, holdings())


def test_rejects_unrepresentable_holdings_total_as_portfolio_error():
    cutoff = date.today().isoformat()
    huge_holdings = read_current_holdings_csv(
        f"FechaCorte,Instrumento,ValorMXN\n{cutoff},AAA,1e100\n".encode(),
        ("AAA",),
    )
    with pytest.raises(PortfolioError, match="no se puede conciliar"):
        read_holdings_control_csv(control(), huge_holdings)
