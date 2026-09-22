from datetime import date, timedelta
from decimal import Decimal

import pytest

from cash_bridge import read_cash_bridge_csv
from holdings_control import HoldingsCoverageControl
from portfolio_core import PortfolioError


def coverage(cash=Decimal("5000.00")):
    return HoldingsCoverageControl(
        date.today(), Decimal("100000.00"), cash, Decimal("0.00"),
        Decimal("0.00"), Decimal("100000.00") + cash, "Estado ficticio", "0" * 64,
    )


def ledger(*, opening="4000.00", deposit="1500.00", fee="500.00", closing="5000.00"):
    start = (date.today() - timedelta(days=14)).isoformat()
    end = date.today().isoformat()
    return (
        "Fecha,Tipo,ImporteMXN\n"
        f"{start},SALDO_INICIAL,{opening}\n"
        f"{start},DEPOSITO,{deposit}\n"
        f"{end},COMISION_IMPUESTO,{fee}\n"
        f"{end},SALDO_FINAL,{closing}\n"
    ).encode("utf-8-sig")


def test_reconciles_settled_cash_to_account_coverage():
    result = read_cash_bridge_csv(ledger(), coverage(), "Movimientos ficticios")
    assert result.opening_cash == Decimal("4000.00")
    assert result.net_movements == Decimal("1000.00")
    assert result.closing_cash == Decimal("5000.00")
    assert result.movement_count == 2
    assert result.other_movement_count == 0
    assert len(result.fingerprint) == 64


def test_applies_direction_of_each_settled_movement_type():
    cutoff = date.today().isoformat()
    rows = [
        "Fecha,Tipo,ImporteMXN",
        f"{cutoff},SALDO_INICIAL,5000.00",
        f"{cutoff},DEPOSITO,1000.00",
        f"{cutoff},RETIRO,200.00",
        f"{cutoff},COMPRA_LIQUIDADA,300.00",
        f"{cutoff},VENTA_LIQUIDADA,400.00",
        f"{cutoff},DIVIDENDO_INTERES,100.00",
        f"{cutoff},COMISION_IMPUESTO,50.00",
        f"{cutoff},OTRA_ENTRADA,75.00",
        f"{cutoff},OTRA_SALIDA,25.00",
        f"{cutoff},SALDO_FINAL,6000.00",
    ]
    result = read_cash_bridge_csv(
        ("\n".join(rows) + "\n").encode(), coverage(Decimal("6000.00")), "Estado ficticio"
    )
    assert result.net_movements == Decimal("1000.00")
    assert result.movement_count == 8
    assert result.other_movement_count == 2


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (ledger(closing="4999.99"), "saldo inicial y los movimientos"),
        (ledger(opening="4500.00", closing="5500.00"), "EfectivoFueraAnalisisMXN"),
        (ledger(deposit="0.00", closing="3500.00"), "importe positivo"),
        (ledger(deposit="=1+1499"), "ImporteMXN"),
        (ledger().replace(b"DEPOSITO", b"TRANSFERENCIA"), "tipo de movimiento desconocido"),
        (ledger().replace(b"SALDO_FINAL", b"SALDO_INICIAL"), "SALDO_FINAL"),
        (ledger().replace(b"COMISION_IMPUESTO", b"OTRA_SALIDA").replace(
            b"SALDO_INICIAL", b"OTRA_ENTRADA", 1
        ), "SALDO_INICIAL"),
    ],
)
def test_rejects_inconsistent_cash_bridge(contents, expected):
    with pytest.raises(PortfolioError, match=expected):
        read_cash_bridge_csv(contents, coverage(), "Movimientos ficticios")


def test_rejects_wrong_cutoff_or_unsorted_dates():
    wrong_cutoff = ledger().replace(date.today().isoformat().encode(), b"2020-01-01")
    with pytest.raises(PortfolioError, match="SALDO_FINAL"):
        read_cash_bridge_csv(wrong_cutoff, coverage(), "Movimientos ficticios")
    start = (date.today() - timedelta(days=14)).isoformat().encode()
    unsorted = ledger().replace(
        start + b",DEPOSITO", date.today().isoformat().encode() + b",DEPOSITO"
    ).replace(date.today().isoformat().encode() + b",COMISION_IMPUESTO", start + b",COMISION_IMPUESTO")
    with pytest.raises(PortfolioError, match="ordenadas"):
        read_cash_bridge_csv(unsorted, coverage(), "Movimientos ficticios")


def test_marks_other_movements_for_review_and_rejects_formula_source():
    result = read_cash_bridge_csv(
        ledger().replace(b"DEPOSITO", b"OTRA_ENTRADA"), coverage(), "Estado ficticio"
    )
    assert result.other_movement_count == 1
    with pytest.raises(PortfolioError, match="fuente válida"):
        read_cash_bridge_csv(ledger(), coverage(), "=FORMULA()")
