"""Synthetic portable proposals preserve evidence, never consent or executable history."""

import base64
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
from zipfile import ZipFile

import pandas as pd
import pytest

from executable_allocation import executable_plan
from implementation_costs import ImplementationCostAssumptions
from operations_review import build_operations_review, read_operations_review
from portfolio_core import PortfolioError

CSV = b"Instrumento,Cantidad,Precio,Lote,PesoObjetivo\nSIM-NEW,0,10,1,0.4\n"
LEDGER = b"ID,Fecha,Tipo\nopening,2026-01-01,OPEN_CASH\n"


def execution():
    costs = ImplementationCostAssumptions(commission_bps=10)
    return {
        "context": (None, None),
        "signature": "f" * 64,
        "inputs": {
            "currency": "MXN",
            "date": "2026-01-30",
            "quote_source": "Cotización ficticia",
            "tariff_source": "Contrato ficticio enero",
            "tariff": asdict(costs),
            "cash": 150.0,
            "cash_floor": 0.0,
            "max_turnover": 0.5,
            "max_weight": 1.0,
            "minimum_trade": 0.0,
            "origin": "CSV manual",
            "optimize": False,
            "book_origin": None,
            "target": [0.4],
            "csv": base64.b64encode(CSV).decode(),
        },
        "result": executable_plan(
            pd.read_csv(BytesIO(CSV)), 150, [0.4], costs, max_turnover=0.5, quotes_confirmed=True
        ),
    }


@pytest.mark.parametrize(
    "vat,market,expected_fee,expected_market,expected_cash",
    [
        (0, 0, 0.35, 0, 649.65),
        (0.16, 0, 0.41, 0, 649.59),
        (0, 10, 0.35, 0.35, 649.30),
    ],
)
def test_decimal_charges_do_not_create_an_artificial_cent(
    vat, market, expected_fee, expected_market, expected_cash
):
    from operations_proposal import portable_proposal

    raw = CSV.replace(b"0.4", b"0.35")
    costs = ImplementationCostAssumptions(commission_bps=10, vat_rate=vat, market_cost_bps=market)
    saved = execution()
    saved["inputs"].update(
        cash=1000.0, target=[0.35], tariff=asdict(costs), csv=base64.b64encode(raw).decode()
    )
    saved["result"] = executable_plan(
        pd.read_csv(BytesIO(raw)), 1000, [0.35], costs, max_turnover=0.5, quotes_confirmed=True
    )
    item = saved["result"]["detail"].iloc[0]
    assert item["Títulos a operar"] == 35
    assert item["Comisión e IVA"] == expected_fee
    assert item["Costo de mercado"] == expected_market
    assert saved["result"]["cash"] == pytest.approx(expected_cash)
    assert portable_proposal(saved)["result"]["cash"] == pytest.approx(expected_cash)


def test_proposal_roundtrip_keeps_sources_fees_lots_and_historical_result_without_consent():
    from operations_proposal import portable_proposal

    payload = portable_proposal(execution())
    manifest, raw = build_operations_review(
        {"ledger": LEDGER}, cutoff="2026-01-30", base="MXN", proposal=payload
    )
    recovered, files = read_operations_review(raw)
    assert manifest["schema"] == 3 and files == {"ledger": LEDGER}
    assert recovered["proposal_data"]["inputs"]["tariff_source"] == "Contrato ficticio enero"
    assert recovered["proposal_data"]["inputs"]["csv"] == base64.b64encode(CSV).decode()
    assert recovered["proposal_data"]["result"]["cash"] == pytest.approx(89.94)
    assert recovered["review_state"] == "PENDING_REVIEW"
    assert "signature" not in recovered["proposal_data"] and "context" not in recovered["proposal_data"]
    assert "confirmed" not in recovered["proposal_data"]
    with ZipFile(BytesIO(raw)) as archive:
        assert "proposal/proposal.json" in archive.namelist()
        assert not any(name.endswith(".pdf") for name in archive.namelist())


def test_proposal_can_travel_without_a_movement_book_and_cannot_change_accounts():
    from operations_proposal import portable_proposal

    _, raw = build_operations_review(
        {},
        cutoff="2026-01-30",
        base="MXN",
        case_id="A",
        account_id="B",
        proposal=portable_proposal(execution()),
    )
    assert read_operations_review(raw, case_id="A", account_id="B")[1] == {}
    with pytest.raises(PortfolioError, match="misma cuenta"):
        read_operations_review(raw, case_id="A", account_id="C")


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p["inputs"].update(confirmed=True),
        lambda p: p["inputs"].update(cash=float("nan")),
        lambda p: p["inputs"].update(quote_source="=WEBSERVICE(secret)"),
        lambda p: p["inputs"].update(quote_source=" =WEBSERVICE(secret)"),
        lambda p: p["inputs"].update(cash="150"),
        lambda p: p["inputs"].update(minimum_trade=100),
        lambda p: p["inputs"].update(csv=base64.b64encode(CSV.replace(b"SIM-NEW", b"=BAD()")).decode()),
        lambda p: p["inputs"].update(target=[1.2]),
        lambda p: p["result"].update(cash=10000),
        lambda p: p["result"]["detail"][0].update(**{"Títulos finales": 9000}),
    ],
)
def test_portable_proposal_rejects_hostile_or_inconsistent_payload(edit):
    from operations_proposal import portable_proposal, validate_proposal

    payload = deepcopy(portable_proposal(execution()))
    edit(payload)
    with pytest.raises(PortfolioError):
        validate_proposal(payload)


def test_exact_quote_reuse_requires_date_currency_source_and_unique_identity():
    from datetime import date

    from operations_proposal import reviewed_quote_defaults

    raw = (
        b"Fecha,Instrumento,Moneda,Precio,Fuente\n"
        b"2026-01-30,SIM-A,MXN,10,Cierre ficticio\n"
        b"2026-01-29,SIM-B,MXN,20,Ayer\n"
        b"2026-01-30,SIM-C,USD,30,Otra divisa\n"
        b"2026-01-30,SIM-D,MXN,40,\n"
        b"2026-01-30,SIM-E,MXN,50,Uno\n"
        b"2026-01-30,SIM-E,MXN,51,Dos\n"
    )
    result = reviewed_quote_defaults(
        raw, assets=["SIM-A", "SIM-B", "SIM-C", "SIM-D", "SIM-E"], cutoff=date(2026, 1, 30), currency="MXN"
    )
    assert result == {"SIM-A": {"Precio": "10", "Fuente": "Cierre ficticio"}}
    assert (
        reviewed_quote_defaults(b"invalid", assets=["SIM-A"], cutoff=date(2026, 1, 30), currency="MXN") == {}
    )


def test_v3_proposal_member_integrity_is_checked_even_when_the_csvs_are_unchanged():
    from operations_proposal import portable_proposal

    _, original = build_operations_review(
        {}, cutoff="2026-01-30", base="MXN", proposal=portable_proposal(execution())
    )
    stream = BytesIO()
    with ZipFile(BytesIO(original)) as archive, ZipFile(stream, "w") as changed:
        for name in archive.namelist():
            value = archive.read(name)
            if name == "proposal/proposal.json":
                value = value.replace(b"89.94", b"99.94")
            changed.writestr(name, value)
    with pytest.raises(PortfolioError, match="integridad"):
        read_operations_review(stream.getvalue())


def test_proposal_pdf_shares_actual_execution_values_and_is_bounded():
    from pypdf import PdfReader

    from operations_proposal import portable_proposal, proposal_pdf

    payload = portable_proposal(execution())
    reader = PdfReader(BytesIO(proposal_pdf(payload)))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert 1 <= len(reader.pages) <= 2
    assert "89.94" in text and "0.06" in text and "SIM-NEW" in text
    assert "Contrato ficticio enero" in text and "Cotización ficticia" in text
    assert "Propuesta" in text and "ejecutada" in text


def test_two_page_limit_includes_long_instrument_sources_and_pending_reasons():
    from pypdf import PdfReader

    from operations_proposal import portable_proposal, proposal_pdf

    saved = execution()
    frame = pd.DataFrame(
        [
            {
                "Instrumento": f"SIM-{i:02d}-" + "W" * 193,
                "Cantidad": 1,
                "Precio": 10,
                "Lote": 1,
                "PesoObjetivo": 10 / 230,
            }
            for i in range(8)
        ]
    )
    costs = ImplementationCostAssumptions(commission_bps=10)
    saved["inputs"].update(
        origin="Libro de movimientos",
        target=[10 / 230] * 8,
        csv=base64.b64encode(frame.to_csv(index=False).encode()).decode(),
        quote_source="W" * 200,
        tariff_source="W" * 200,
    )
    saved["inputs"]["book_origin"] = {
        "cash": "150",
        "currency": "MXN",
        "cutoff": "2026-01-30",
        "ledger_sha256": "a" * 64,
        "code_sha256": {"synthetic.py": "b" * 64},
        "quotes": [
            {
                "Instrumento": row["Instrumento"],
                "Fecha": "2026-01-30",
                "Precio": "10",
                "Lote": "1",
                "PesoObjetivo": str(10 / 230),
                "Fuente": "W" * 200,
            }
            for row in frame.to_dict("records")
        ],
    }
    saved["result"] = executable_plan(frame, 150, [10 / 230] * 8, costs, quotes_confirmed=True)
    saved["result"]["basis"] = "W" * 200
    payload = portable_proposal(saved)
    snapshot = {"issues": [{"title": "W" * 100, "reason": "W" * 160}] * 3}
    assert len(PdfReader(BytesIO(proposal_pdf(payload, snapshot))).pages) == 2


@pytest.mark.parametrize("weight,expected_cash", [(0.4, 89.94), (0.2, 119.97)])
def test_reopening_manual_proposal_prefills_terms_but_requires_fresh_confirmation(weight, expected_cash):
    from hashlib import sha256

    from streamlit.testing.v1 import AppTest

    from operations_proposal import portable_proposal

    saved = execution()
    saved["inputs"]["target"] = [weight]
    saved["result"] = executable_plan(
        pd.read_csv(BytesIO(CSV)),
        150,
        [weight],
        ImplementationCostAssumptions(commission_bps=10),
        max_turnover=0.5,
        quotes_confirmed=True,
    )
    payload = portable_proposal(saved)
    key = sha256(str((None, None, None)).encode()).hexdigest()[:16]
    nav_raw = b"Fecha,NAV,Fuente\n2026-01-30,150,Ficticia\n"
    app = AppTest.from_string(
        f"""
from unittest.mock import patch
import streamlit as st
from operations_ui import render_account_operations
st.session_state.setdefault('_ops_review_{key}', {{
 'token':'portable-test','files':{{}},'settings':{{'cutoff':'2026-01-30','base':'MXN'}},
 'proposal':{payload!r}
}})
if st.session_state.pop('_complete_nav',False):
 from operations_review_ui import save_review_input
 st.session_state['_ops_context_key']='{key}'
 save_review_input('nav',{nav_raw!r})
with patch('operations_ui._context',return_value=(None,None,None,None)):
 render_account_operations()
""",
        default_timeout=40,
    ).run()
    assert not app.exception
    assert any(b.label == "Vaciar movimientos y empezar" for b in app.button)
    assert next(n for n in app.number_input if n.label == "Efectivo disponible para operar").value == 150
    assert next(n for n in app.number_input if n.label == "Comisión · puntos base por operación").value == 10
    assert (
        next(t for t in app.text_input if t.label == "Fuente y vigencia de las tarifas aplicables").value
        == "Contrato ficticio enero"
    )
    confirmation = next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste"))
    assert not confirmation.value
    assert not any(b.proto.label == "Descargar propuesta CSV" for b in app.get("download_button"))
    confirmation.check().run()
    next(b for b in app.button if b.label == "Calcular propuesta de títulos").click().run()
    assert not app.exception and not app.error
    assert app.session_state["_execution_proposal"]["result"]["cash"] == pytest.approx(expected_cash)
    commission = next(n for n in app.number_input if n.label == "Comisión · puntos base por operación")
    commission.set_value(20.0).run()
    app.session_state["_complete_nav"] = True
    app.run()
    assert not app.exception
    assert next(n for n in app.number_input if n.label == "Comisión · puntos base por operación").value == 20
    assert not next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste")).value
