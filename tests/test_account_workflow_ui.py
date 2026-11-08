"""Synthetic end-to-end account research and lazy reports in Streamlit's test runtime."""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app_inversiones.py"


def test_account_demo_calculates_only_on_request_and_pdf_is_lazy(monkeypatch):
    import streamlit as st

    import access
    import account_workflow
    import workspace_ui
    from case_workspace import WorkspaceError

    monkeypatch.setattr(access, "require_access", lambda: None)

    def missing():
        raise WorkspaceError("Registro desactivado")

    monkeypatch.setattr(workspace_ui, "configured_workspace", missing)
    calls = []
    original = account_workflow.calculate_allocation

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(account_workflow, "calculate_allocation", counted)
    downloads = {}
    original_download = st.download_button

    def capture_download(label, data, *args, **kwargs):
        downloads[label] = data
        return original_download(label, data, *args, **kwargs)

    monkeypatch.setattr(st, "download_button", capture_download)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.pills if item.label == "Modo de análisis").set_value("Por cuenta").run()
    next(item for item in app.button if item.label == "Abrir demostración ficticia").click().run()
    assert not app.exception
    assert not calls
    next(item for item in app.number_input if item.label == "Monto objetivo · MXN").set_value(110000.0).run()
    next(item for item in app.number_input if item.label == "Trayectorias").set_value(100).run()
    next(item for item in app.checkbox if item.label.startswith("Confirmé que posiciones")).check().run()
    next(item for item in app.button if item.label == "Analizar cuenta").click().run()
    assert not app.exception
    assert not app.error
    assert len(calls) == 1
    completed = app.session_state["_account_flow"]["completed"]
    assert not completed.get("pdf")
    with ZipFile(BytesIO(downloads["Descargar paquete para retomar"])) as archive:
        assert "report.pdf" not in archive.namelist()
    next(item for item in app.selectbox if item.label == "Agrupar exposición").set_value("Sector").run()
    assert len(calls) == 1
    next(item for item in app.button if item.label == "Generar PDF de esta ejecución").click().run()
    assert not app.exception
    assert not app.error
    pdf = app.session_state["_account_flow"]["completed"]["pdf"]
    assert pdf.startswith(b"%PDF")
    bundle = downloads["Descargar paquete para retomar"]
    manifest, _, _ = account_workflow.read_run_bundle(bundle)
    with ZipFile(BytesIO(bundle)) as archive:
        assert archive.read("report.pdf") == pdf
    assert manifest["run_id"] == completed["run_id"]
    assert len(calls) == 1
    next(item for item in app.number_input if item.label == "Tasa libre de riesgo MXN · % anual").set_value(
        4.0
    ).run()
    assert any("cambios sin calcular" in item.value for item in app.info)
    assert len(calls) == 1
    next(item for item in app.button if item.label == "Analizar cuenta").click().run()
    assert len(calls) == 2
    assert not app.exception


def test_advanced_benchmark_requires_explicit_currency_before_provider_call(monkeypatch):
    import access
    import portfolio_core

    monkeypatch.setattr(access, "require_access", lambda: None)
    calls = []
    monkeypatch.setattr(portfolio_core.yf, "download", lambda *args, **kwargs: calls.append(True))
    app = AppTest.from_file(APP, default_timeout=30).run()
    currency = next(item for item in app.selectbox if item.label == "Moneda de cotización del benchmark")
    assert currency.value is None
    next(item for item in app.text_input if item.label == "Ticker del benchmark (opcional)").set_value(
        "SPY"
    ).run()
    next(item for item in app.button if item.label == "Analizar portafolio").click().run()
    assert any("Confirma la moneda" in item.value for item in app.error)
    assert not calls


def test_advanced_model_survives_rerun_and_builds_only_requested_pdf(monkeypatch):
    import access
    import allocation_analysis
    import portfolio_core
    import reporting

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(73)
    prices = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (150, 4)), axis=0)),
        index=pd.bdate_range("2024-01-01", periods=150),
        columns=pd.MultiIndex.from_product([["Close"], ["AAPL", "MSFT", "GOOG", "TSLA"]]),
    )
    monkeypatch.setattr(portfolio_core.yf, "download", lambda *_args, **_kwargs: prices)
    calls, pdfs = [], []
    original = allocation_analysis.calculate_allocation

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    def comparison(*args, **kwargs):
        pdfs.append("comparison")
        return b"%PDF-synthetic"

    def method(*args, **kwargs):
        pdfs.append("method")
        return b"%PDF-synthetic"

    monkeypatch.setattr(allocation_analysis, "calculate_allocation", counted)
    monkeypatch.setattr(reporting, "create_comparison_pdf_report", comparison)
    monkeypatch.setattr(reporting, "create_pdf_report", method)
    app = AppTest.from_file(APP, default_timeout=30).run()
    next(item for item in app.button if item.label == "Analizar portafolio").click().run()
    assert not app.exception and not app.error
    assert len(calls) == 1 and not pdfs
    app.run()
    assert len(calls) == 1 and not pdfs
    next(item for item in app.button if item.label == "Generar comparativo PDF").click().run()
    assert not app.exception and not app.error
    assert pdfs == ["comparison"] and len(calls) == 1
    app.run()
    assert pdfs == ["comparison"] and len(calls) == 1
    next(item for item in app.number_input if item.label == "Tasa libre de riesgo anual (%)").set_value(
        4.0
    ).run()
    next(item for item in app.button if item.label == "Analizar portafolio").click().run()
    assert not app.exception and not app.error
    assert len(calls) == 2 and pdfs == ["comparison"]
