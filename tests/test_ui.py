from datetime import date
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import portfolio_core as core


def test_complete_analysis_survives_rerun(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(21)
    prices = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, (150, 4)), axis=0)
    data = pd.DataFrame(
        prices,
        index=pd.date_range("2024-01-01", periods=150, freq="B"),
        columns=pd.MultiIndex.from_product([["Close"], ["AAPL", "MSFT", "GOOG", "TSLA"]]),
    )
    monkeypatch.setattr(core.yf, "download", lambda *args, **kwargs: data)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert len(app.metric) == 4
    next(
        item for item in app.checkbox if item.label == "Calcular trayectorias hipotéticas"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    assert len(app.metric) == 8
    app.radio[0].set_value("Retiros").run()
    withdrawal = next(item for item in app.number_input if item.label.startswith("Retiro mensual"))
    withdrawal.set_value(50_000.0).run()
    assert not app.exception
    assert not app.error
    assert any(item.label == "Con retiro no cubierto" for item in app.metric)
    next(
        item for item in app.checkbox if item.label == "Calcular pruebas de estrés"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    next(
        item for item in app.checkbox if item.label == "Añadir shock hipotético por activo"
    ).set_value(True).run()
    shocks = next(item for item in app.text_input if item.label.startswith("Cambios por activo"))
    shocks.set_value("-20,-10,-5,0").run()
    assert not app.exception
    assert not app.error
    app.run()
    assert not app.exception
    assert len(app.metric) == 8
    current = next(item for item in app.text_input if item.label.startswith("Cartera actual"))
    current.set_value("25,25,25,25").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error


def test_builtin_h10_comparison_runs_on_common_dates(monkeypatch):
    import access
    from fx_comparison import H10_REFERENCE, read_reference

    monkeypatch.setattr(access, "require_access", lambda: None)
    reference = read_reference(H10_REFERENCE.read_bytes())
    dates = reference.index.drop(pd.Timestamp("2024-03-29"))
    rng = np.random.default_rng(9)
    stock_prices = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, (len(dates), 2)), axis=0)

    def fake_download(symbols, **_kwargs):
        if symbols == ["USDMXN=X"]:
            values = reference.reindex(dates).to_numpy()[:, None]
            tickers = ["USDMXN=X"]
        else:
            values = stock_prices
            tickers = ["AAPL", "MSFT"]
        return pd.DataFrame(
            values, index=dates,
            columns=pd.MultiIndex.from_product([["Close"], tickers]),
        )

    monkeypatch.setattr(core.yf, "download", fake_download)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.text_input[0].set_value("AAPL, MSFT")
    app.text_input[1].set_value("USD, USD")
    app.selectbox[0].set_value("MXN")
    app.date_input[0].set_value(date(2024, 1, 1))
    app.date_input[1].set_value(date(2024, 6, 30))
    app.run()
    app.button[0].click().run()
    assert not app.exception
    app.radio[0].set_value("Reserva Federal H.10 (enero-junio 2024)").run()
    assert not app.exception
    assert not app.error


def test_holdout_panel_runs_with_disjoint_dates(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(101)
    prices = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, (180, 4)), axis=0)
    supplied = pd.DataFrame(
        prices,
        index=pd.date_range("2024-01-01", periods=180, freq="B"),
        columns=pd.MultiIndex.from_product([["Close"], ["AAPL", "MSFT", "GOOG", "TSLA"]]),
    )
    monkeypatch.setattr(core.yf, "download", lambda *args, **kwargs: supplied)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.button[0].click().run()
    holdout = next(
        item for item in app.checkbox if item.label == "Comparar resultados fuera de muestra"
    )
    holdout.set_value(True).run()
    assert not app.exception
    assert not app.error


    assert any("Estimación:" in item.value and "Evaluación:" in item.value for item in app.markdown)
    next(
        item for item in app.checkbox if item.label == "Evaluar cuatro cortes predefinidos"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    next(
        item for item in app.checkbox
        if item.label == "Comparar estimadores de covarianza (corte único)"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    next(
        item for item in app.checkbox
        if item.label == "Añadir intensidad calibrada (corte único)"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    successive = next(
        item for item in app.checkbox if item.label == "Evaluar revisiones sucesivas"
    )
    successive.set_value(True).run()
    assert not app.exception
    assert not app.error
    assert any("Estimación inicial hasta:" in item.value for item in app.markdown)
    next(
        item for item in app.checkbox
        if item.label == "Comparar estimadores de covarianza (revisiones)"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    next(
        item for item in app.checkbox
        if item.label == "Añadir intensidad calibrada (revisiones)"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    sensitivity = next(
        item for item in app.checkbox if item.label == "Comparar ventanas de estimación"
    )
    sensitivity.set_value(True).run()
    assert not app.exception
    assert not app.error


def test_uploaded_prices_run_without_yahoo_price_download(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(251)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    values = 100 * np.cumprod(1 + rng.normal(0.0006, 0.01, (140, 4)), axis=0)
    table = pd.DataFrame(values, columns=["AAPL", "MSFT", "GOOG", "TSLA"])
    table.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    upload = BytesIO(table.to_csv(index=False).encode("utf-8-sig"))
    monkeypatch.setattr(
        st, "file_uploader",
        lambda label, **_kwargs: upload if label.startswith("Precios ajustados CSV") else None,
    )
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    source = next(
        item for item in app.text_input if item.label == "Fuente declarada de precios CSV"
    )
    source.set_value("Archivo de investigación").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("Precios CSV aportados" in item.value for item in app.info)
