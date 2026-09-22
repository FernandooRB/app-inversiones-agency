from datetime import date

import pytest

from holdings import read_current_holdings_csv
from portfolio_core import PortfolioError
from position_bridge import read_position_bridge_csv


def _holdings():
    cutoff = date.today().isoformat()
    return read_current_holdings_csv((
        f"FechaCorte,Instrumento,ValorMXN\n{cutoff},AAA,60000\n{cutoff},BBB,40000\n"
    ).encode(), ("AAA", "BBB"))


def _ledger(movements=None):
    cutoff = date.today().isoformat()
    movements = movements or [f"{cutoff},AAA,TITULOS,COMPRA,2"]
    return ("Fecha,Instrumento,Unidad,Tipo,Cantidad\n"
            "2020-01-01,AAA,TITULOS,SALDO_INICIAL,10\n"
            "2020-01-01,BBB,TITULOS,SALDO_INICIAL,5\n"
            + "\n".join(movements) + "\n").encode()


def _closing(*, aaa="12", bbb="5", value="60000.00", unit="TITULOS"):
    cutoff = date.today().isoformat()
    return ("FechaCorte,Instrumento,Unidad,CantidadFinal,ValorMXN\n"
            f"{cutoff},BBB,TITULOS,{bbb},40000.00\n"
            f"{cutoff},AAA,{unit},{aaa},{value}\n").encode()


def _read(ledger=None, closing=None):
    return read_position_bridge_csv(
        ledger if ledger is not None else _ledger(),
        closing if closing is not None else _closing(),
        _holdings(), "Movimientos de prueba", "Cierre de prueba",
    )


def test_reconciles_independent_closing_quantities_and_values():
    result = _read()
    assert result.start_date == date(2020, 1, 1)
    assert result.end_date == date.today()
    assert [(line.asset, line.opening, line.net_movements, line.closing)
            for line in result.lines] == [("AAA", 10, 2, 12), ("BBB", 5, 0, 5)]
    assert result.movement_count == 1
    assert result.adjustment_count == 0
    assert len(result.ledger_fingerprint) == len(result.closing_fingerprint) == 64


def test_offsetting_trades_and_adjustment_are_recorded_without_adding_units_across_assets():
    cutoff = date.today().isoformat()
    result = _read(_ledger([
        f"{cutoff},AAA,TITULOS,VENTA,1",
        f"{cutoff},AAA,TITULOS,COMPRA,3",
        f"{cutoff},BBB,TITULOS,AJUSTE_POSITIVO,0.5",
    ]), _closing(bbb="5.5"))
    assert result.movement_count == 3
    assert result.adjustment_count == 1
    assert result.lines[1].closing == 5.5


@pytest.mark.parametrize(("ledger", "closing", "message"), [
    (_ledger(), _closing(aaa="11"), "CantidadFinal de AAA"),
    (_ledger(), _closing(value="59999.99"), "ValorMXN de AAA"),
    (_ledger(), _closing(unit="NOMINAL_MXN"), "Unidad de AAA"),
    (_ledger([f"{date.today():%Y-%m-%d},AAA,TITULOS,VENTA,11",
              f"{date.today():%Y-%m-%d},AAA,TITULOS,COMPRA,13"]),
     _closing(), "cantidad negativa"),
    (_ledger([f"{date.today():%Y-%m-%d},CCC,TITULOS,COMPRA,2"]),
     _closing(), "fuera de la cartera"),
    (_ledger([f"{date.today():%Y-%m-%d},AAA,NOMINAL_MXN,COMPRA,2"]),
     _closing(), "Unidad inconsistente"),
    (_ledger([f"{date.today():%Y-%m-%d},AAA,TITULOS,COMPRA,0"]),
     _closing(), "cantidad positiva"),
    (_ledger(["2019-12-31,AAA,TITULOS,COMPRA,2"]),
     _closing(), "fechas de movimientos"),
])
def test_rejects_inconsistent_quantities_units_and_values(ledger, closing, message):
    with pytest.raises(PortfolioError, match=message):
        _read(ledger, closing)


def test_rejects_missing_asset_and_unsafe_extra_columns():
    with pytest.raises(PortfolioError, match="exactamente una fila"):
        _read(closing=_closing().splitlines(keepends=True)[0]
              + _closing().splitlines(keepends=True)[1])
    with pytest.raises(PortfolioError, match="columnas exactas"):
        _read(ledger=_ledger().replace(b"Cantidad\n", b"Cantidad,Cuenta\n"))
    with pytest.raises(PortfolioError, match="fuente válida"):
        read_position_bridge_csv(_ledger(), _closing(), _holdings(), "=FORMULA()", "Cierre")
