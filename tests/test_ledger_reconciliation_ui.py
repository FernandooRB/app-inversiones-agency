"""The review screen must distinguish arithmetic matches, missing controls and differences."""

from datetime import date
from decimal import Decimal

from streamlit.testing.v1 import AppTest


def screen(control_rows):
    raw = (
        "Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente\n" + control_rows
    ).encode()
    return AppTest.from_string(f'''
from datetime import date
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_ui import _closing_reconciliation
from portfolio_core import PortfolioError
book = {{"cash": {{"MXN": 100}}, "pending": {{}}, "positions": {{("SIM-A", "MXN"): 2}}, "repos": {{}}}}
with patch.object(st, "file_uploader", return_value=BytesIO({raw!r})):
    try:
        _closing_reconciliation((None,None,None,None), book, date.today(), b"fictional ledger")
    except PortfolioError as exc:
        st.error(str(exc))
''', default_timeout=30).run()


def test_cent_difference_stays_pending_and_does_not_show_a_match():
    app = screen(f"{date.today()},CASH,,MXN,100.01,Estado ficticio\n"
                 f"{date.today()},POSITION,SIM-A,MXN,2,Estado ficticio\n")
    assert not app.exception and not app.error and not app.success
    assert any("Con diferencia: 1" in warning.value for warning in app.warning)
    table = app.dataframe[0].value
    assert table.loc[table["Tipo"].eq("Efectivo liquidado"), "Diferencia"].iloc[0] == Decimal("-0.01")
    assert any(item.proto.label == "Descargar conciliación de cierre" for item in app.get("download_button"))


def test_quantity_only_control_does_not_report_complete_cash_coverage():
    app = screen(f"{date.today()},POSITION,SIM-A,MXN,2,Estado ficticio\n")
    assert not app.exception and not app.error and not app.success
    assert any("Sin control: 1" in warning.value for warning in app.warning)
    table = app.dataframe[0].value
    row = table[table["Tipo"].eq("Efectivo liquidado")].iloc[0]
    assert row["Estado"] == "Sin control" and row["Control"] is None


def test_complete_controls_show_only_arithmetic_match_and_keep_evidence_columns():
    app = screen(f"{date.today()},CASH,,MXN,100,Estado ficticio\n"
                 f"{date.today()},POSITION,SIM-A,MXN,2,Estado ficticio\n")
    assert not app.exception and not app.error and not app.warning
    assert any("Controles con coincidencia aritmética: 2" in item.value for item in app.success)
    assert {"Unidad", "Fuente", "Libro", "Control", "Diferencia", "Estado"}.issubset(app.dataframe[0].value)
