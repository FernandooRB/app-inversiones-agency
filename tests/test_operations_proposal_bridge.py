"""Independent fictional balances, safety prerequisites, and live-session invalidation."""

from datetime import date
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from executable_allocation import executable_plan
from implementation_costs import ImplementationCostAssumptions
from operations_proposal_bridge import proposal_inputs
from portfolio_core import PortfolioError

DAY = date(2026, 1, 30)
HEADER = (
    b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
    b"Referencia,MomentoFlujo,Interes\n"
)
CASH = HEADER + b"opening,2026-01-30,2026-01-30,OPEN_CASH,,MXN,0,0,150,0,0,,UNKNOWN,0\n"


def quote(asset="SIM-NEW", **changes):
    return {
        "Instrumento": asset,
        "Fecha": str(DAY),
        "Precio": "10",
        "Lote": "1",
        "PesoObjetivo": "0.4",
        "Fuente": "Precio y lote ficticios, cierre",
        **changes,
    }


def prepare(raw=CASH, rows=None, **kwargs):
    return proposal_inputs(
        raw, cutoff=DAY, currency="MXN", market_rows=rows or [quote()], confirmed=True, **kwargs
    )


def test_settled_cash_funds_six_titles_and_six_cents_without_sending_orders():
    ready = prepare()
    assert ready["cash"] == "150" and ready["positions"].iloc[0]["Cantidad"] == "0"
    result = executable_plan(
        ready["positions"], 150, [0.4], ImplementationCostAssumptions(10, 0, 0, 0), quotes_confirmed=True
    )
    assert result["cash"] == pytest.approx(89.94)
    assert result["cost"] == pytest.approx(0.06)
    assert result["turnover"] == pytest.approx(0.4)
    assert ready["quotes"][0]["Fuente"] == quote()["Fuente"]


def test_quantities_are_rebuilt_from_book_and_held_instruments_cannot_be_omitted():
    raw = CASH + b"held,2026-01-30,2026-01-30,OPEN_POSITION,SIM-HELD,MXN,2,0,0,0,0,,UNKNOWN,0\n"
    with pytest.raises(PortfolioError, match="todos los títulos"):
        prepare(raw)
    ready = prepare(raw, [quote("SIM-HELD", PesoObjetivo="0"), quote()])
    assert list(ready["positions"]["Cantidad"]) == ["2", "0"]
    with pytest.raises(PortfolioError):
        prepare(raw, [{**quote("SIM-HELD"), "Cantidad": "999"}])


@pytest.mark.parametrize(
    "row,reason",
    [
        (b"pending,2026-01-30,2026-02-02,BUY,SIM,MXN,1,10,10,0,0,,UNKNOWN,0\n", "liquidaciones"),
        (b"repo,2026-01-30,2026-01-30,REPO_START,,MXN,0,0,10,0,0,repo-ficticio,UNKNOWN,0\n", "reportos"),
        (b"usd,2026-01-30,2026-01-30,OPEN_CASH,,USD,0,0,10,0,0,,UNKNOWN,0\n", "una sola moneda"),
        (b"withdraw,2026-01-30,2026-01-30,WITHDRAWAL,,MXN,0,0,200,0,0,,EOD,0\n", "negativo"),
    ],
)
def test_unavailable_or_foreign_cash_never_funds_a_proposal(row, reason):
    with pytest.raises(PortfolioError, match=reason):
        prepare(CASH + row)


@pytest.mark.parametrize(
    "changes",
    [
        {"Fecha": "2026-01-29"},
        {"Fuente": ""},
        {"Fuente": " =UNTRUSTED()"},
        {"Instrumento": "=UNTRUSTED()"},
        {"Precio": "NaN"},
        {"Lote": "0"},
        {"PesoObjetivo": "1.1"},
    ],
)
def test_market_inputs_require_exact_date_source_and_safe_finite_values(changes):
    with pytest.raises(PortfolioError):
        prepare(rows=[quote(**changes)])


def test_duplicates_weight_overflow_and_missing_confirmation_are_rejected():
    with pytest.raises(PortfolioError):
        prepare(rows=[quote(), quote()])
    with pytest.raises(PortfolioError):
        prepare(rows=[quote("SIM-A", PesoObjetivo="0.6"), quote("SIM-B", PesoObjetivo="0.6")])
    with pytest.raises(PortfolioError, match="Coteja"):
        proposal_inputs(CASH, cutoff=DAY, currency="MXN", market_rows=[quote()])


def test_pending_payable_and_receivable_do_not_disappear_when_their_net_is_zero():
    raw = (
        CASH
        + b"buy,2026-01-30,2026-02-02,BUY,SIM,MXN,1,10,10,0,0,,UNKNOWN,0\n"
        + b"sell,2026-01-30,2026-02-03,SELL,SIM,MXN,1,10,10,0,0,,UNKNOWN,0\n"
    )
    with pytest.raises(PortfolioError, match="liquidaciones"):
        prepare(raw)


def test_book_connection_reuses_proposal_then_withdraws_it_after_fee_or_ledger_change():
    app = AppTest.from_string(
        f"""
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch
import streamlit as st
from operations_ui import render_account_operations
key=sha256(str((None,None,None)).encode()).hexdigest()[:16]
st.session_state.setdefault('_ops_review_'+key, {{
    'token':'bridge-test','files':{{'ledger':{CASH!r}}},
    'settings':{{'cutoff':'2026-01-30','base':'MXN'}}
}})
actor=SimpleNamespace(actor='OTHER-FICTIONAL-USER') if st.session_state.get('_switch_actor') else None
with patch('operations_ui._context',return_value=(None,actor,None,None)):
    render_account_operations()
""",
        default_timeout=40,
    )
    with patch("operations_ui.executable_plan", wraps=executable_plan) as engine:
        app.run()
        next(t for t in app.text_input if t.label.startswith("Instrumentos adicionales")).input(
            "SIM-NEW"
        ).run()
        values = {
            "Precio sin ajuste · SIM-NEW": "10",
            "Lote · SIM-NEW": "1",
            "Peso objetivo entre 0 y 1 · SIM-NEW": "0.4",
            "Fuente de precio y lote · SIM-NEW": "Cotización y lote ficticios",
        }
        for label, value in values.items():
            next(t for t in app.text_input if t.label == label).input(value)
        next(c for c in app.checkbox if c.label.startswith("Cotejé títulos")).check()
        next(b for b in app.button if b.label == "Usar libro para preparar propuesta").click().run()
        assert not app.error and not app.exception
        assert (
            next(r for r in app.radio if r.label == "Origen de la propuesta").value == "Libro de movimientos"
        )
        next(t for t in app.text_input if t.label == "Fuente y vigencia de las tarifas aplicables").input(
            "Tarifa ficticia vigente"
        ).run()
        next(n for n in app.number_input if n.label == "Comisión · puntos base por operación").set_value(
            10.0
        ).run()
        confirmation = next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste"))
        confirmation.check().run()
        next(b for b in app.button if b.label == "Calcular propuesta de títulos").click().run()
        assert not app.error and not app.exception
        assert app.session_state["_execution_proposal"]["result"]["cash"] == pytest.approx(89.94)
        app.run()
        assert engine.call_count == 1
        app.session_state["_switch_actor"] = True
        app.run()
        assert not app.dataframe
        assert not any(b.proto.label == "Descargar propuesta CSV" for b in app.get("download_button"))
        app.session_state["_switch_actor"] = False
        app.run()
        next(n for n in app.number_input if n.label == "Comisión · puntos base por operación").set_value(
            20.0
        ).run()
        assert not next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste")).value
        assert not any(b.proto.label == "Descargar propuesta CSV" for b in app.get("download_button"))
        next(b for b in app.button if b.label.startswith("Quitar archivo recuperado · Libro")).click().run()
        assert not any(b.proto.label == "Descargar propuesta CSV" for b in app.get("download_button"))
        assert not app.error and not app.exception
