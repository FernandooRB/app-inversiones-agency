from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import portfolio_core as core


def rights_manifest(scope: str = "ENTREGABLES_DERIVADOS") -> BytesIO:
    reviewed = (date.today() - timedelta(days=10)).isoformat()
    expires = (date.today() + timedelta(days=365)).isoformat()
    contents = (
        "Fuente,Producto,Mercados,FechaRevision,VigenciaHasta,EstadoDerechos,"
        "AlcanceAutorizado,AjusteCorporativo,HoraCorteZona,ReferenciaContractual\n"
        f"Proveedor de prueba,Cierres diarios,BMV y SIC,{reviewed},{expires},CONFIRMADO,"
        f"{scope},AJUSTADO,Cierre oficial America/Mexico_City,Contrato ficticio sección 4\n"
    )
    return BytesIO(contents.encode("utf-8-sig"))


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
    benchmark_data = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0005, 0.008, (150, 1)), axis=0),
        index=data.index,
        columns=pd.MultiIndex.from_product([["Close"], ["SPY"]]),
    )

    def fake_download(symbols, **_kwargs):
        return benchmark_data if symbols == ["SPY"] else data

    monkeypatch.setattr(core.yf, "download", fake_download)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    policy_toggle = next(
        item for item in app.checkbox if item.label == "Aplicar límites por clase"
    )
    policy_toggle.set_value(True).run()
    classes = next(
        item for item in app.text_input if item.label == "Clases de los tickers, en el mismo orden"
    )
    classes.set_value("crecimiento,crecimiento,defensivo,defensivo").run()
    limits = next(
        item for item in app.text_area if item.label == "Límites: clase, mínimo %, máximo %"
    )
    limits.set_value("crecimiento,20,40\ndefensivo,60,80").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("clasificación fue declarada" in item.value for item in app.caption)
    benchmark = next(
        item for item in app.text_input if item.label == "Ticker del benchmark (opcional)"
    )
    benchmark.set_value("SPY").run()
    benchmark_currency = next(
        item for item in app.selectbox if item.label == "Moneda de cotización del benchmark"
    )
    benchmark_currency.set_value("USD").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("Alpha usa CAPM" in item.value for item in app.caption)
    next(
        item for item in app.checkbox if item.label == "Añadir alternativa Black-Litterman"
    ).set_value(True).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("Equilibrio: referencia simple factible" in item.value for item in app.caption)
    views = next(
        item for item in app.text_area
        if item.label == "Opiniones: activo, rendimiento anual %, confianza %"
    )
    views.set_value("AAPL,12,60\nMSFT,9,50").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("misma covarianza histórica" in item.value for item in app.caption)
    commission = next(
        item for item in app.number_input if item.label == "Comisión sobre cada operación (%)"
    )
    commission.set_value(0.25).run()
    app.button[0].click().run()
    assert any("referencia del tarifario" in item.value for item in app.error)
    cost_source = next(
        item for item in app.text_input if item.label == "Referencia del tarifario"
    )
    cost_source.set_value("Tarifario ficticio de prueba").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("Tarifario ficticio de prueba" in item.value for item in app.caption)
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
    asset_shock = next(
        item for item in app.checkbox if item.label == "Añadir shock hipotético por activo"
    )
    asset_shock.set_value(False).run()
    next(
        item for item in app.checkbox if item.label == "Añadir shock hipotético por clase"
    ).set_value(True).run()
    assert not app.exception
    assert not app.error
    assert any("Shocks definidos por clase" in item.value for item in app.markdown)
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
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": upload,
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": (
            rights_manifest("INVESTIGACION_INTERNA")
        ),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert any("Precios CSV aportados" in item.value for item in app.info)
    assert any("sólo investigación interna" in item.value for item in app.warning)


def test_uploaded_prices_require_a_confirmed_rights_manifest(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    dates = pd.date_range("2024-01-02", periods=80, freq="B")
    prices = pd.DataFrame({
        "Fecha": dates.strftime("%Y-%m-%d"),
        "AAPL": np.linspace(100, 120, len(dates)),
        "MSFT": np.linspace(200, 230, len(dates)),
        "GOOG": np.linspace(90, 110, len(dates)),
        "TSLA": np.linspace(180, 210, len(dates)),
    })
    upload = BytesIO(prices.to_csv(index=False).encode("utf-8-sig"))
    monkeypatch.setattr(
        st, "file_uploader",
        lambda label, **_kwargs: upload if label.startswith("Precios ajustados CSV") else None,
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    app.button[0].click().run()
    assert not app.exception
    assert any("manifiesto de derechos" in item.value for item in app.error)


def test_current_holdings_csv_sets_weights_and_capital_without_persisting_client_data(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(271)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    values = 100 * np.cumprod(1 + rng.normal(0.0005, 0.009, (140, 2)), axis=0)
    prices = pd.DataFrame(values, columns=["AAPL", "MSFT"])
    prices.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    cutoff = date.today().isoformat()
    holdings = pd.DataFrame({
        "FechaCorte": [cutoff, cutoff],
        "Instrumento": ["MSFT", "AAPL"],
        "ValorMXN": [30_000, 70_000],
    })
    tax_basis = pd.DataFrame({
        "FechaCorte": [cutoff, cutoff],
        "Instrumento": ["MSFT", "AAPL"],
        "CostoFiscalActualizadoMXN": [25_000, 45_000],
        "TratamientoFiscal": ["PF_ACCIONES_BOLSA_ART129"] * 2,
        "TasaEscenarioPct": [10, 10],
        "Fuente": ["Estado fiscal ficticio"] * 2,
    })
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": BytesIO(
            prices.to_csv(index=False).encode("utf-8-sig")
        ),
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": rights_manifest(),
        "Cartera actual valuada en MXN CSV (opcional)": BytesIO(
            holdings.to_csv(index=False).encode("utf-8-sig")
        ),
        "Bases fiscales actualizadas CSV (opcional; requiere cartera actual)": BytesIO(
            tax_basis.to_csv(index=False).encode("utf-8-sig")
        ),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label == "Tickers").set_value("AAPL, MSFT")
    next(
        item for item in app.text_input
        if item.label == "Monedas de cotización, en el mismo orden"
    ).set_value("MXN, MXN")
    next(
        item for item in app.selectbox if item.label == "Moneda base del análisis"
    ).set_value("MXN")
    next(
        item for item in app.text_input if item.label == "Fuente declarada de la cartera actual"
    ).set_value("Estado de cuenta ficticio")
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any(
        cutoff in item.value and "100,000.00 MXN" in item.value
        and "Estado de cuenta ficticio" in item.value
        for item in app.info
    )
    assert any(
        frame.value.astype(str).eq("Cartera actual").any().any()
        for frame in app.dataframe
    )
    assert any("Reserva fiscal estimada" in frame.value.columns for frame in app.dataframe)


def test_current_holdings_csv_cannot_be_combined_with_manual_weights(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    holdings = BytesIO(
        (
            "FechaCorte,Instrumento,ValorMXN\n"
            f"{date.today().isoformat()},AAPL,100000\n"
        ).encode("utf-8-sig")
    )
    monkeypatch.setattr(
        st, "file_uploader",
        lambda label, **_kwargs: holdings if label.startswith("Cartera actual valuada") else None,
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label.startswith("Cartera actual, pesos")).set_value(
        "25,25,25,25"
    ).run()
    app.button[0].click().run()
    assert not app.exception
    assert any("sólo una entrada" in item.value for item in app.error)


def test_contractual_tariff_profile_overrides_zero_manual_costs(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    rng = np.random.default_rng(281)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    values = 100 * np.cumprod(1 + rng.normal(0.0005, 0.009, (140, 2)), axis=0)
    prices = pd.DataFrame(values, columns=["AAPL", "MSFT"])
    prices.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    tariff = (
        "Intermediario,Producto,Mercado,FechaConsulta,ComisionOperacionPct,"
        "IVAPctComision,ComisionMinimaMXN,CostoMercadoPbSupuesto,"
        "CostoFijoAnualTotalMXN,AdministracionAnualTotalPct,Fuente\n"
        "Casa de Bolsa,Cuenta de prueba,Capitales MX y SIC,2026-09-01,0.25,16,0,8,"
        "1032,1.0,Contrato ficticio de prueba\n"
    )
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": BytesIO(
            prices.to_csv(index=False).encode("utf-8-sig")
        ),
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": rights_manifest(),
        "Perfil contractual de costos CSV (opcional)": BytesIO(tariff.encode("utf-8-sig")),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label == "Tickers").set_value("AAPL, MSFT")
    next(
        item for item in app.text_input
        if item.label == "Monedas de cotización, en el mismo orden"
    ).set_value("MXN, MXN")
    next(
        item for item in app.selectbox if item.label == "Moneda base del análisis"
    ).set_value("MXN")
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any(
        "Casa de Bolsa" in item.value and "Cuenta de prueba" in item.value
        and "2,032.00 MXN" in item.value
        for item in app.info
    )


def test_bond_issue_csv_is_integrated_with_auditable_total_return(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    rng = np.random.default_rng(77)
    stock_values = 100 * np.cumprod(1 + rng.normal(0.0005, 0.008, (140, 2)), axis=0)
    price_table = pd.DataFrame(stock_values, columns=["AAPL", "MSFT"])
    price_table.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    bond_table = pd.DataFrame({
        "Fecha": dates.strftime("%Y-%m-%d"),
        "Emision": "M 310529",
        "Vencimiento": "2031-05-29",
        "PrecioLimpio": np.linspace(98.0, 99.0, len(dates)),
        "InteresDevengado": np.linspace(0.1, 2.9, len(dates)),
        "Cupon": 0.0,
    })
    bond_table.loc[70, ["PrecioLimpio", "InteresDevengado", "Cupon"]] = [96.0, 0.1, 3.0]
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": BytesIO(
            price_table.to_csv(index=False).encode("utf-8-sig")
        ),
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": rights_manifest(),
        "Serie de Bono M por emisión (opcional)": BytesIO(
            bond_table.to_csv(index=False).encode("utf-8-sig")
        ),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label == "Tickers").set_value("AAPL, MSFT")
    next(
        item for item in app.text_input
        if item.label == "Monedas de cotización, en el mismo orden"
    ).set_value("MXN, MXN")
    next(
        item for item in app.selectbox if item.label == "Moneda base del análisis"
    ).set_value("MXN")
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any("M 310529" in item.value for item in app.info)


def test_liquidity_rate_csv_is_integrated_without_future_rate_use(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    rng = np.random.default_rng(91)
    stock_values = 100 * np.cumprod(1 + rng.normal(0.0004, 0.008, (140, 2)), axis=0)
    price_table = pd.DataFrame(stock_values, columns=["AAPL", "MSFT"])
    price_table.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    liquidity_table = pd.DataFrame({
        "Fecha": dates.strftime("%Y-%m-%d"),
        "Vehiculo": "Cuenta remunerada de prueba",
        "TasaAnualPct": np.linspace(7.5, 8.5, len(dates)),
        "Convencion": "nominal_360",
        "Tratamiento": "NETA",
    })
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": BytesIO(
            price_table.to_csv(index=False).encode("utf-8-sig")
        ),
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": rights_manifest(),
        "Tasas de vehículo de liquidez MXN (opcional)": BytesIO(
            liquidity_table.to_csv(index=False).encode("utf-8-sig")
        ),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label == "Tickers").set_value("AAPL, MSFT")
    next(
        item for item in app.text_input
        if item.label == "Monedas de cotización, en el mismo orden"
    ).set_value("MXN, MXN")
    next(
        item for item in app.selectbox if item.label == "Moneda base del análisis"
    ).set_value("MXN")
    next(
        item for item in app.text_input
        if item.label == "Fuente declarada de la tasa de liquidez"
    ).set_value("Estado de cuenta de prueba")
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any("Cuenta remunerada de prueba" in item.value for item in app.info)


def test_exact_fund_series_csv_is_integrated_with_distributions(monkeypatch):
    import access

    monkeypatch.setattr(access, "require_access", lambda: None)
    dates = pd.date_range("2024-01-02", periods=140, freq="B")
    rng = np.random.default_rng(101)
    stock_values = 100 * np.cumprod(1 + rng.normal(0.0004, 0.008, (140, 2)), axis=0)
    price_table = pd.DataFrame(stock_values, columns=["AAPL", "MSFT"])
    price_table.insert(0, "Fecha", dates.strftime("%Y-%m-%d"))
    fund_values = np.linspace(10.0, 10.8, len(dates))
    distributions = np.zeros(len(dates))
    distributions[70] = 0.2
    fund_values[70:] -= 0.2
    fund_table = pd.DataFrame({
        "Fecha": dates.strftime("%Y-%m-%d"),
        "Fondo": "Fondo de prueba",
        "Serie": "A1",
        "Moneda": "MXN",
        "ValorAccion": fund_values,
        "Distribucion": distributions,
    })
    uploads = {
        "Precios ajustados CSV aportados por el equipo (opcional)": BytesIO(
            price_table.to_csv(index=False).encode("utf-8-sig")
        ),
        "Manifiesto de derechos de los precios CSV (obligatorio si cargas precios)": rights_manifest(),
        "Serie de fondo de inversión MXN (opcional)": BytesIO(
            fund_table.to_csv(index=False).encode("utf-8-sig")
        ),
    }
    monkeypatch.setattr(st, "file_uploader", lambda label, **_kwargs: uploads.get(label))
    monkeypatch.setattr(
        core.yf, "download",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Yahoo no debe consultarse")),
    )
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.text_input if item.label == "Tickers").set_value("AAPL, MSFT")
    next(
        item for item in app.text_input
        if item.label == "Monedas de cotización, en el mismo orden"
    ).set_value("MXN, MXN")
    next(
        item for item in app.selectbox if item.label == "Moneda base del análisis"
    ).set_value("MXN")
    next(
        item for item in app.text_input if item.label == "Fuente declarada del valor del fondo"
    ).set_value("Estado de cuenta de prueba")
    app.run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any("Fondo de prueba" in item.value and "A1" in item.value for item in app.info)
