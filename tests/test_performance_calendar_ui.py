"""Coverage feedback must remain distinct from a return or approval of account data."""

from streamlit.testing.v1 import AppTest


def screen(timing, dates):
    return AppTest.from_string(f'''
from datetime import date
from operations_ui import _valuation_calendar
from realized_performance import Flow
_valuation_calendar(date(2026,1,1),date(2026,1,10),
    [Flow(date(2026,1,5),50,{timing!r})], available_dates={dates!r})
''', default_timeout=30).run()


def test_plan_names_missing_and_conditional_closes_without_computing_returns():
    app = screen("UNKNOWN", ["2026-01-01", "2026-01-10"])
    assert not app.exception and not app.error and not app.metric and not app.success
    assert any("Cierres obligatorios faltantes: 1" in item.value for item in app.warning)
    table = app.dataframe[0].value
    assert table.loc[table["Fecha"].eq("2026-01-04"), "Requisito"].iloc[0] == "Si el flujo se confirma BOD"
    assert any(item.proto.label == "Descargar plan de valuaciones" for item in app.get("download_button"))


def test_available_dates_do_not_select_a_moment_for_an_unknown_flow():
    app = screen("UNKNOWN", ["2026-01-01", "2026-01-04", "2026-01-05", "2026-01-10"])
    assert not app.exception and not app.error and not app.success
    assert any("faltantes: 0 · Flujos sin momento: 1" in item.value for item in app.warning)


def test_complete_calendar_shows_only_calendar_coverage_without_return_metrics():
    app = screen("EOD", ["2026-01-01", "2026-01-05", "2026-01-10"])
    assert not app.exception and not app.error and not app.warning and not app.metric
    assert any("cubren el calendario de TWR" in item.value for item in app.success)


def test_single_day_book_is_not_extended_to_invent_a_performance_period():
    app = AppTest.from_string('''
from datetime import date
from operations_ui import _valuation_calendar
_valuation_calendar(date(2026,1,1),date(2026,1,1),[])
''', default_timeout=30).run()
    assert not app.exception and not app.error and not app.dataframe
    assert any("cierre posterior" in item.value for item in app.info)


def test_uploaded_nav_period_drives_calendar_instead_of_current_book_cutoff():
    ledger = (
        b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
        b"Referencia,MomentoFlujo,Interes\n"
        b"opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n"
        b"flow,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n"
    )
    nav = b"Fecha,NAV\n2026-01-01,100\n2026-01-10,160\n"
    app = AppTest.from_string(f'''
from io import BytesIO
from unittest.mock import patch
from operations_ui import _ledger
import streamlit as st
def upload(label,*args,**kwargs):
    if label=="Libro normalizado de movimientos": return BytesIO({ledger!r})
    if label.startswith("Valuaciones históricas verificadas"): return BytesIO({nav!r})
    return None
with patch.object(st,"file_uploader",side_effect=upload):
    _ledger((None,None,None,None))
''', default_timeout=30).run()
    assert not app.exception and not app.error
    plan = next(item.value for item in app.dataframe if "Fecha en CSV" in item.value)
    assert list(plan["Fecha"]) == ["2026-01-01", "2026-01-05", "2026-01-10"]
    app.checkbox(key="flows_confirmation_temporary").check().run()
    assert not app.exception and not app.error
    assert next(item.value for item in app.metric if item.label == "TWR del periodo") == "Pendiente"
