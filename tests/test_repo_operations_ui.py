"""The operations screen must not show a complete NAV while repo values are missing."""

from datetime import date

import pytest
from streamlit.testing.v1 import AppTest


def screen(repo_csv=None):
    day = date.today().isoformat()
    ledger = (
        "ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
        "Referencia,MomentoFlujo,Interes\n"
        f"cash,{day},{day},OPEN_CASH,,MXN,0,0,1000,0,0,,UNKNOWN,0\n"
        f"repo,{day},{day},OPEN_REPO,,MXN,0,0,1000,0,0,SIM-R,UNKNOWN,0\n"
    ).encode()
    script = f'''
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_ui import _ledger
from portfolio_core import PortfolioError
ledger = {ledger!r}
repo_csv = {repo_csv!r}
def upload(label, *args, **kwargs):
    if label == "Libro normalizado de movimientos":
        return BytesIO(ledger)
    if label.startswith("Valuación de reportos al cierre") and repo_csv is not None:
        return BytesIO(repo_csv)
    return None
with patch.object(st, "file_uploader", side_effect=upload):
    try:
        _ledger(None)
    except PortfolioError as exc:
        st.error(str(exc))
'''
    app = AppTest.from_string(script, default_timeout=30).run()
    if not app.error:
        app.checkbox(key="raw_confirmation_temporary").check().run()
    return app


def test_outstanding_repo_does_not_show_incomplete_nav_without_valuation():
    app = screen()
    assert not app.exception and not app.error and not app.metric
    assert any("Valuación pendiente" in info.value for info in app.info)


def test_repo_and_cash_only_portfolio_can_be_valued_without_fictitious_equity_quotes():
    raw = (
        "Fecha,Referencia,Moneda,Valor,Fuente\n"
        f"{date.today()},SIM-R,MXN,1003.25,Estado ficticio\n"
    ).encode()
    app = screen(raw)
    assert not app.exception and not app.error
    assert app.metric[0].value == "2,003.25"
    assert not any("Valuación pendiente" in info.value for info in app.info)


@pytest.mark.parametrize("reference", ["OTHER", "SIM-R\n"])
def test_wrong_reference_or_malformed_repo_valuation_does_not_publish_nav(reference):
    raw = (
        "Fecha,Referencia,Moneda,Valor,Fuente\n"
        f"{date.today()},{reference},MXN,1003.25,Estado ficticio\n"
    ).encode()
    app = screen(raw)
    assert not app.exception and app.error and not app.metric
