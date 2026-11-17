"""Independent fictional cash arithmetic, account binding and post-cost risk."""

from copy import deepcopy
from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from account_demo import demo_account
from account_workflow import AccountSettings, run_account_analysis
from implementation_costs import ImplementationCostAssumptions
from portfolio_core import PortfolioError


@pytest.fixture(scope="module")
def flow():
    files, metadata, defaults = demo_account()
    settings = AccountSettings(**defaults)
    result = run_account_analysis(files, settings, metadata)
    return {
        "context": ("fictional-store", "fictional-actor", "fictional-case", "fictional-account"),
        "files": files,
        "metadata": metadata,
        "defaults": asdict(settings),
        "completed": {
            "files": files,
            "metadata": metadata,
            "settings": settings,
            "result": result,
            "run_id": "a" * 32,
        },
    }


def strategy(flow, **changes):
    from operations_comparison import strategy_from_analysis

    settings = flow["completed"]["settings"]
    return strategy_from_analysis(
        flow,
        flow["context"],
        settings.assets,
        date.fromisoformat(settings.as_of),
        "MXN",
        "Mínima volatilidad",
        **changes,
    )


def test_strategy_preserves_exact_weights_period_version_and_input_hashes(flow):
    from operations_comparison import validate_strategy

    saved = strategy(flow)
    result = flow["completed"]["result"]
    expected = next(a.metrics.weights for a in result["alternatives"] if a.name == "Mínima volatilidad")
    assert saved["weights"] == expected.tolist()
    assert saved["analysis_key"] == result["key"]
    assert saved["code_sha256"] == result["code_sha256"]
    assert set(saved["files_sha256"]) == set(flow["files"])
    assert saved["sample_start"] == result["model"].returns.index[0].date().isoformat()
    assert saved["sample_end"] == result["model"].returns.index[-1].date().isoformat()
    assert "fictional-actor" not in str(saved) and "fictional-store" not in str(saved)
    assert validate_strategy(saved, saved["assets"], saved["as_of"], "MXN", saved["weights"]) == saved


@pytest.mark.parametrize("index", range(4))
def test_strategy_rejects_other_store_actor_case_or_account(flow, index):
    from operations_comparison import strategy_from_analysis

    binding = list(flow["context"])
    binding[index] = "other"
    s = flow["completed"]["settings"]
    with pytest.raises(PortfolioError, match="misma cuenta"):
        strategy_from_analysis(
            flow, tuple(binding), s.assets, date.fromisoformat(s.as_of), "MXN", "Mínima volatilidad"
        )


@pytest.mark.parametrize("change", ["input", "metadata", "settings", "key", "code"])
def test_strategy_rejects_uncomputed_or_obsolete_analysis(flow, change):
    changed = deepcopy(flow)
    if change == "input":
        changed["files"]["holdings"] += b"\n"
    elif change == "metadata":
        changed["metadata"]["SIM-A"]["Fuente"] = "Otro documento"
    elif change == "settings":
        changed["defaults"]["partial_fraction"] = 0.5
    elif change == "key":
        changed["completed"]["result"]["key"] = "f" * 64
    else:
        changed["completed"]["result"]["code_sha256"] = "f" * 64
    with pytest.raises(PortfolioError, match="calcula|versión"):
        strategy(changed)


@pytest.mark.parametrize("problem", ["order", "cutoff", "currency", "name"])
def test_strategy_rejects_wrong_universe_date_currency_or_alternative(flow, problem):
    from operations_comparison import strategy_from_analysis

    s = flow["completed"]["settings"]
    args = [flow, flow["context"], s.assets, date.fromisoformat(s.as_of), "MXN", "Mínima volatilidad"]
    if problem == "order":
        args[2] = tuple(reversed(s.assets))
    elif problem == "cutoff":
        args[3] = date(2026, 1, 1)
    elif problem == "currency":
        args[4] = "USD"
    else:
        args[5] = "No calculada"
    with pytest.raises(PortfolioError):
        strategy_from_analysis(*args)


def positions():
    return pd.DataFrame(
        {"Instrumento": ["SIM-A"], "Cantidad": [0], "Precio": [10], "Lote": [1], "PesoObjetivo": [0.4]}
    )


def test_comparison_has_independent_expected_cash_fees_and_quantities():
    from operations_comparison import compare_plans

    compared = compare_plans(
        positions(), 1000, [0.4], ImplementationCostAssumptions(10), quotes_confirmed=True
    )
    for name, titles, fee, cash in [
        ("Conservar", 0, 0, 1000),
        ("Cambio parcial", 10, 0.1, 899.9),
        ("Propuesta", 40, 0.4, 599.6),
    ]:
        plan = compared["plans"][name]
        assert plan["detail"].iloc[0]["Títulos finales"] == titles
        assert plan["cost"] == pytest.approx(fee)
        assert plan["cash"] == pytest.approx(cash)
    assert compared["summary"]["Alternativa"].tolist() == ["Conservar", "Cambio parcial", "Propuesta"]


def test_concentrated_reference_and_unachievable_target_stay_visible():
    from operations_comparison import compare_plans

    p = positions().assign(Cantidad=100)
    result = compare_plans(
        p, 0, [0], ImplementationCostAssumptions(), quotes_confirmed=True, max_weight=0.5, max_turnover=0
    )
    assert result["plans"]["Conservar"]["detail"].iloc[0]["Títulos finales"] == 100
    assert result["plans"]["Conservar"]["cost"] == 0
    table = result["summary"].set_index("Alternativa")
    assert table.loc["Conservar", "Estado"] == "Fuera de límites"
    assert result["plans"]["Propuesta"] is None
    assert pd.isna(table.loc["Propuesta", "Costo"])
    assert table.loc["Propuesta", "Motivo"]


@pytest.mark.parametrize("fraction", [0, 1])
def test_partial_endpoints_keep_reference_or_match_full_proposal(fraction):
    from operations_comparison import compare_plans

    result = compare_plans(positions(), 1000, [0.4], fraction=fraction, quotes_confirmed=True)
    expected = result["plans"]["Conservar" if fraction == 0 else "Propuesta"]
    assert result["plans"]["Cambio parcial"]["cash"] == expected["cash"]


def test_unconfirmed_quotes_and_bad_fraction_never_trigger_comparison():
    from operations_comparison import compare_plans

    with pytest.raises(PortfolioError):
        compare_plans(positions(), 1000, [0.4])
    with pytest.raises(PortfolioError):
        compare_plans(positions(), 1000, [0.4], fraction=float("nan"), quotes_confirmed=True)


def risk_model():
    return SimpleNamespace(
        returns=pd.DataFrame({"SIM-A": [0.01, -0.01, 0.02]}, index=pd.date_range("2026-01-01", periods=3)),
        moments=SimpleNamespace(
            mean=pd.Series([0.1], index=["SIM-A"]),
            covariance=pd.DataFrame([[0.04]], index=["SIM-A"], columns=["SIM-A"]),
            description="Modelo ficticio",
        ),
    )


def test_risk_uses_post_cost_wealth_and_does_not_normalize_away_cash():
    from operations_comparison import plan_risk

    plan = {"detail": positions().assign(**{"Títulos finales": 60}), "cash": 399, "cost": 1}
    risk = plan_risk(plan, risk_model())
    assert risk["annual_mean"] == pytest.approx(0.1 * 600 / 999)
    assert risk["annual_volatility"] == pytest.approx(0.2 * 600 / 999)
    assert risk["cash_weight"] == pytest.approx(399 / 999)
    assert risk["coverage"] == 1
    assert risk["observations"] == 3


def test_missing_history_or_model_is_pending_instead_of_zero_risk():
    from operations_comparison import plan_risk

    plan = {
        "detail": positions().assign(Instrumento="NO-HISTORY", **{"Títulos finales": 60}),
        "cash": 399,
        "cost": 1,
    }
    for model in [None, risk_model()]:
        risk = plan_risk(plan, model)
        assert risk["status"] == "Pendiente"
        assert risk["annual_mean"] is None and risk["annual_volatility"] is None


def proposal_case(flow, *, linked=False):
    import base64

    from executable_allocation import executable_plan

    s = flow["completed"]["settings"]
    saved_strategy = strategy(flow)
    weights = saved_strategy["weights"] if linked else [0.1] * len(s.assets)
    p = pd.DataFrame(
        {"Instrumento": s.assets, "Cantidad": 0, "Precio": 10, "Lote": 1, "PesoObjetivo": weights}
    )
    costs = ImplementationCostAssumptions(10)
    inputs = {
        "currency": "MXN",
        "date": s.as_of,
        "quote_source": "Precios ficticios sin ajuste",
        "tariff_source": "Tarifa ficticia",
        "tariff": asdict(costs),
        "cash": 1000.0,
        "cash_floor": 0.0,
        "max_turnover": 2.0,
        "max_weight": 1.0,
        "minimum_trade": 0.0,
        "origin": "CSV manual",
        "optimize": False,
        "book_origin": None,
        "target": weights,
        "csv": base64.b64encode(p.to_csv(index=False).encode()).decode(),
    }
    if linked:
        inputs["strategy"] = saved_strategy
    return {
        "context": (None, None),
        "signature": "f" * 64,
        "inputs": inputs,
        "result": executable_plan(p, 1000, weights, costs, quotes_confirmed=True),
    }


def test_v4_package_preserves_strategy_and_legacy_v3_stays_readable(flow):
    from operations_proposal import portable_proposal
    from operations_review import build_operations_review, read_operations_review

    for linked, schema in [(False, 3), (True, 4)]:
        payload = portable_proposal(proposal_case(flow, linked=linked))
        assert payload["schema"] == (2 if linked else 1)
        manifest, raw = build_operations_review(
            {}, cutoff=payload["inputs"]["date"], base="MXN", proposal=payload
        )
        assert manifest["schema"] == schema
        read, _ = read_operations_review(raw)
        assert read["proposal_data"] == payload
        assert read["review_state"] == "PENDING_REVIEW"
        if linked:
            assert read["proposal_data"]["inputs"]["strategy"]["run_id"] == "a" * 32


@pytest.mark.parametrize("change", ["weights", "date", "order", "source", "extra"])
def test_strategy_provenance_cannot_drift_from_proposal(flow, change):
    from operations_proposal import portable_proposal, validate_proposal

    payload = portable_proposal(proposal_case(flow, linked=True))
    s = payload["inputs"]["strategy"]
    if change == "weights":
        s["weights"] = [0.0, 0.0, 1.0]
    elif change == "date":
        s["as_of"] = "2026-01-01"
    elif change == "order":
        s["assets"].reverse()
    elif change == "source":
        s["files_sha256"]["prices"] = "not-a-hash"
    else:
        s["confirmed"] = True
    with pytest.raises(PortfolioError):
        validate_proposal(payload)


def test_strategy_pdf_retains_period_and_stays_brief(flow):
    from io import BytesIO

    from pypdf import PdfReader

    from operations_proposal import portable_proposal, proposal_pdf

    payload = portable_proposal(proposal_case(flow, linked=True))
    reader = PdfReader(BytesIO(proposal_pdf(payload)))
    assert len(reader.pages) <= 2
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Mínima volatilidad" in text
    assert payload["inputs"]["strategy"]["sample_start"] in text


def test_screen_connects_strategy_compares_and_withdraws_after_selection_changes(flow):
    from unittest.mock import patch

    from streamlit.testing.v1 import AppTest

    from executable_allocation import executable_plan
    from operations_proposal import portable_proposal

    current = deepcopy(flow)
    current["context"] = (None, None, None, None)
    saved = portable_proposal(proposal_case(current))
    app = AppTest.from_string(
        """
import streamlit as st
from operations_ui import _implementation
st.session_state['_ops_context_key']='comparison-test'
_implementation((None,None,None,None))
""",
        default_timeout=45,
    )
    app.session_state["_account_flow"] = current
    app.session_state["_ops_review_comparison-test"] = {"token": "test", "proposal": saved}
    app.run()
    next(r for r in app.radio if r.label == "Pesos objetivo").set_value(
        "Alternativa del análisis de cuenta"
    ).run()
    next(s for s in app.selectbox if s.label == "Alternativa objetivo del análisis").select(
        "Máximo Sharpe"
    ).run()
    assert not app.exception

    def check():
        return next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste"))

    assert not check().value
    check().check().run()
    with patch("operations_ui.executable_plan", wraps=executable_plan) as engine:
        next(b for b in app.button if b.label == "Calcular propuesta de títulos").click().run()
        assert not app.exception
        assert app.session_state["_execution_proposal"]["inputs"]["strategy"]["name"] == "Máximo Sharpe"
        assert engine.call_count == 1
        app.run()
        assert engine.call_count == 1
    next(b for b in app.button if b.label == "Comparar alternativas con estos insumos").click().run()
    compared = app.session_state["_execution_comparison"]
    assert len(compared["result"]["summary"]) == 3
    assert compared["risks"]["Propuesta"]["status"] == "Modelo disponible"
    next(s for s in app.selectbox if s.label == "Alternativa objetivo del análisis").select(
        "Pesos iguales"
    ).run()
    assert not check().value
    assert not any("Efectivo final **" in m.value for m in app.markdown)
    assert not any(b.label == "Descargar comparación CSV" for b in app.button)


def test_comparison_reuses_current_full_plan_instead_of_solving_it_twice(flow):
    import base64
    from io import BytesIO
    from unittest.mock import patch

    from executable_allocation import executable_plan
    from operations_comparison import compare_plans

    full = proposal_case(flow)
    inputs = full["inputs"]
    frame = pd.read_csv(BytesIO(base64.b64decode(inputs["csv"])))
    with patch("operations_comparison.executable_plan", wraps=executable_plan) as engine:
        result = compare_plans(
            frame,
            inputs["cash"],
            inputs["target"],
            ImplementationCostAssumptions(10),
            quotes_confirmed=True,
            full_plan=full,
        )
        assert engine.call_count == 1
        assert result["plans"]["Propuesta"] is full["result"]


def test_reopened_book_keeps_effective_strategy_weights(flow):
    import base64
    from hashlib import sha256

    from streamlit.testing.v1 import AppTest

    from operations_proposal import portable_proposal
    from operations_proposal_bridge import proposal_inputs

    current = deepcopy(flow)
    current["context"] = (None, None, None, None)
    saved = proposal_case(current, linked=True)
    day = saved["inputs"]["date"]
    ledger = (
        "ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,Referencia,MomentoFlujo,Interes\n"
        f"opening,{day},{day},OPEN_CASH,,MXN,0,0,1000,0,0,,UNKNOWN,0\n"
    ).encode()
    rows = [
        {
            "Instrumento": a,
            "Fecha": day,
            "Precio": "10",
            "Lote": "1",
            "PesoObjetivo": "0.1",
            "Fuente": "Fuente ficticia",
        }
        for a in current["completed"]["settings"].assets
    ]
    ready = proposal_inputs(
        ledger, cutoff=date.fromisoformat(day), currency="MXN", market_rows=rows, confirmed=True
    )
    saved["inputs"].update(
        origin="Libro de movimientos",
        book_origin={k: v for k, v in ready.items() if k != "positions"},
        csv=base64.b64encode(ready["positions"].to_csv(index=False).encode()).decode(),
    )
    payload = portable_proposal(saved)
    app = AppTest.from_string(
        """
import streamlit as st
from operations_ui import _implementation
st.session_state['_ops_context_key']='book-comparison-test'
_implementation((None,None,None,None))
""",
        default_timeout=45,
    )
    app.session_state["_ops_last_book_book-comparison-test"] = {
        "cutoff": day,
        "ledger_sha256": sha256(ledger).hexdigest(),
    }
    app.session_state["_ops_review_book-comparison-test"] = {
        "token": "test",
        "proposal": payload,
        "files": {"ledger": ledger},
    }
    app.run()
    next(c for c in app.checkbox if c.label.startswith("Cotejé títulos")).check()
    next(b for b in app.button if b.label == "Usar libro para preparar propuesta").click().run()
    next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste")).check().run()
    next(b for b in app.button if b.label == "Calcular propuesta de títulos").click().run()
    assert not app.exception
    assert app.session_state["_execution_proposal"]["inputs"]["strategy"] == payload["inputs"]["strategy"]
    assert app.session_state["_execution_proposal"]["inputs"]["target"] == payload["inputs"]["target"]


def test_recovered_strategy_with_changed_currency_is_gated_before_calculating(flow):
    from streamlit.testing.v1 import AppTest

    from operations_proposal import portable_proposal

    app = AppTest.from_string(
        """
import streamlit as st
from operations_ui import _implementation
st.session_state['_ops_context_key']='binding-comparison-test'
_implementation((None,None,None,None))
""",
        default_timeout=45,
    )
    app.session_state["_ops_review_binding-comparison-test"] = {
        "token": "test",
        "proposal": portable_proposal(proposal_case(flow, linked=True)),
    }
    app.run()
    next(s for s in app.selectbox if s.label == "Moneda de las órdenes").select("USD").run()
    next(c for c in app.checkbox if c.label.startswith("Confirmé precios sin ajuste")).check().run()
    assert next(b for b in app.button if b.label == "Calcular propuesta de títulos").disabled


def test_computed_weight_roundoff_can_reopen_without_changing_any_weight():
    from operations_proposal_bridge import proposal_inputs

    day = date(2026, 1, 30)
    raw = (
        b"ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,"
        b"Referencia,MomentoFlujo,Interes\n"
        b"opening,2026-01-30,2026-01-30,OPEN_CASH,,MXN,0,0,1000,0,0,,UNKNOWN,0\n"
    )
    weights = ["0.6", "0.11798677449484879", "0.2820132255051513"]
    rows = [
        {
            "Instrumento": f"SIM-{i}",
            "Fecha": str(day),
            "Precio": "10",
            "Lote": "1",
            "PesoObjetivo": w,
            "Fuente": "Modelo ficticio",
        }
        for i, w in enumerate(weights)
    ]
    ready = proposal_inputs(raw, cutoff=day, currency="MXN", market_rows=rows, confirmed=True)
    assert [q["PesoObjetivo"] for q in ready["quotes"]] == weights
    assert ready["cash"] == "1000"
    rows[0]["PesoObjetivo"] = "0.60000000001"
    with pytest.raises(PortfolioError, match="pesos objetivo"):
        proposal_inputs(raw, cutoff=day, currency="MXN", market_rows=rows, confirmed=True)
