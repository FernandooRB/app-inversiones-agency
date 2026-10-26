from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from technical_analysis import TechnicalError, analyze_history
from technical_ui import build_technical_chart
from watchlist_store import WatchlistStore

APP = Path(__file__).resolve().parents[1] / "app_inversiones.py"


def open_tracking(monkeypatch, tmp_path, symbols=()):
    import access
    import technical_ui

    monkeypatch.setattr(access, "require_access", lambda: None)
    store = WatchlistStore(tmp_path / "watchlists.db")
    store.save("test-issuer", "test-user", symbols)
    monkeypatch.setattr(technical_ui, "configured_watchlist", lambda: (store, "test-issuer", "test-user"))
    app = AppTest.from_file(APP, default_timeout=120).run()
    app.session_state["workspace_area"] = "Seguimiento"
    app.run()
    return app, store


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_empty_list_copy_edit_persist_and_reopen(monkeypatch, tmp_path):
    app, store = open_tracking(monkeypatch, tmp_path)
    assert not app.exception
    assert button(app, "Actualizar señales").disabled
    button(app, "Copiar desde Análisis").click().run()
    assert app.text_area[0].value == "AAPL, MSFT, GOOG, TSLA"
    app.text_area[0].set_value("aapl, MSFT, AAPL").run()
    button(app, "Guardar lista").click().run()
    assert not app.exception
    assert store.load("test-issuer", "test-user") == ["AAPL", "MSFT"]
    reopened = AppTest.from_file(APP, default_timeout=30).run()
    reopened.session_state["workspace_area"] = "Seguimiento"
    reopened.run()
    assert reopened.text_area[0].value == "AAPL, MSFT"
    reopened.text_area[0].set_value("MSFT").run()
    button(reopened, "Guardar lista").click().run()
    assert store.load("test-issuer", "test-user") == ["MSFT"]
    assert not reopened.exception


def test_refresh_partial_provider_failure_filters_and_backtest(
    monkeypatch, tmp_path, technical_history,
):
    import technical_ui

    app, _store = open_tracking(monkeypatch, tmp_path, ["AAPL", "BROKEN"])
    calls = []

    def download(symbol, refresh_id):
        calls.append((symbol, refresh_id))
        if symbol == "BROKEN":
            raise TechnicalError("Proveedor no disponible para este símbolo.")
        return technical_history

    monkeypatch.setattr(technical_ui, "cached_market_history", download)
    button(app, "Actualizar señales").click().run()
    assert not app.exception
    table = app.dataframe[0].value
    assert table.loc[table["Acción"] == "BROKEN", "Señal"].iloc[0] == "No evaluable"
    assert pd.isna(table.loc[table["Acción"] == "BROKEN", "Último cierre"].iloc[0])
    assert pd.api.types.is_numeric_dtype(table["Último cierre"])
    assert len(app.get("plotly_chart")) == 1
    button(app, "Ejecutar prueba histórica").click().run()
    assert not app.exception
    assert len(app.get("plotly_chart")) == 2
    assert any(item.label == "Operaciones cerradas" for item in app.metric)
    button(app, "Validar por periodos").click().run()
    assert not app.exception
    assert any("Estrategia neta con estrés" in item.value.columns
               and len(item.value) == 3 for item in app.dataframe)
    assert len(calls) == 2
    next(item for item in app.number_input if item.label == "Costo total por lado (%)").set_value(1).run()
    assert not any(item.label == "Operaciones cerradas" for item in app.metric)
    next(item for item in app.selectbox if item.label == "Mostrar señales").set_value("No evaluable").run()
    assert any("Proveedor no disponible" in item.value for item in app.info)
    assert len(calls) == 2
    button(app, "Actualizar señales").click().run()
    assert len(calls) == 4 and calls[-1][1] != calls[0][1]
    assert not app.exception


def test_user_change_does_not_keep_previous_list_or_quotes(monkeypatch, tmp_path, technical_history):
    import technical_ui

    app, store = open_tracking(monkeypatch, tmp_path, ["AAPL"])
    monkeypatch.setattr(technical_ui, "cached_market_history", lambda *_: technical_history)
    button(app, "Actualizar señales").click().run()
    app.session_state["technical_sic_symbol_AAPL"] = "SERIE-ANTERIOR"
    store.save("test-issuer", "second-user", ["MSFT"])
    monkeypatch.setattr(technical_ui, "configured_watchlist", lambda: (store, "test-issuer", "second-user"))
    app.run()
    assert app.text_area[0].value == "MSFT"
    assert not app.session_state.filtered_state.get("_technical_histories", {})
    assert "technical_sic_symbol_AAPL" not in app.session_state.filtered_state
    assert not app.exception


def test_storage_change_reloads_the_list_in_same_session(monkeypatch, tmp_path):
    import technical_ui

    app, _ = open_tracking(monkeypatch, tmp_path, ["AAPL"])
    second_store = WatchlistStore(tmp_path / "second.db")
    second_store.save("test-issuer", "test-user", ["MSFT"])
    monkeypatch.setattr(
        technical_ui, "configured_watchlist",
        lambda: (second_store, "test-issuer", "test-user"),
    )
    app.run()
    assert not app.exception
    assert app.text_area[0].value == "MSFT"


def test_chart_has_four_aligned_panes_and_full_history_indicators(technical_history):
    snapshot = analyze_history(technical_history)
    figure = build_technical_chart(snapshot, currency="USD", months=3)
    assert figure.layout.xaxis.matches == "x4"
    assert figure.layout.xaxis2.matches == "x4"
    assert figure.layout.xaxis3.matches == "x4"
    assert figure.data[0].type == "candlestick"
    assert len(figure.data[0].x) < len(technical_history.bars)
    # Cropping the viewport must not discard the SMA200 warmup from before it.
    sma200 = next(trace for trace in figure.data if trace.name == "Media 200")
    assert all(value == value for value in sma200.y)


def test_unconfigured_storage_does_not_query_provider(monkeypatch, tmp_path):
    import technical_ui
    from watchlist_store import WatchlistError

    app, _store = open_tracking(monkeypatch, tmp_path)

    def fail():
        raise WatchlistError("Almacenamiento privado no disponible.")

    monkeypatch.setattr(technical_ui, "configured_watchlist", fail)
    app.run()
    assert not app.exception
    assert any("Almacenamiento privado" in item.value for item in app.info)


def test_selection_can_move_to_another_symbol(monkeypatch, tmp_path, technical_history):
    import technical_ui

    app, _store = open_tracking(monkeypatch, tmp_path, ["AAPL", "MSFT"])
    monkeypatch.setattr(technical_ui, "cached_market_history",
                        lambda symbol, refresh_id: replace(technical_history, symbol=symbol))
    button(app, "Actualizar señales").click().run()
    selector = next(item for item in app.selectbox if item.label == "Acción para revisar")
    selector.set_value("MSFT").run()
    assert any(item.value.startswith("MSFT ·") for item in app.subheader)
    assert not app.exception


def test_watchlist_storage_checks_authorization_before_identity_access(monkeypatch, tmp_path):
    import technical_ui
    from watchlist_store import WatchlistError

    claims = {"iss": "issuer", "sub": "subject", "exp": 0}
    policy = {"identities": [{"issuer": "issuer", "subject": "subject"}]}
    monkeypatch.setattr(technical_ui.st, "user", SimpleNamespace(to_dict=lambda: claims))
    monkeypatch.setattr(technical_ui.st, "secrets", {
        "access": policy, "technical_watchlist": {"database_path": str(tmp_path / "lists.db")},
    })
    with pytest.raises(WatchlistError, match="expirado"):
        technical_ui.configured_watchlist()
    assert not (tmp_path / "lists.db").exists()


def test_watchlist_storage_uses_verified_issuer_and_subject(monkeypatch, tmp_path):
    import time

    import technical_ui

    claims = {"iss": "issuer", "sub": "subject", "exp": time.time() + 3600}
    monkeypatch.setattr(technical_ui.st, "user", SimpleNamespace(to_dict=lambda: claims))
    monkeypatch.setattr(technical_ui.st, "secrets", {
        "access": {"identities": [{"issuer": "issuer", "subject": "subject"}]},
        "technical_watchlist": {"database_path": str(tmp_path / "lists.db")},
    })
    store, issuer, subject = technical_ui.configured_watchlist()
    assert (issuer, subject) == ("issuer", "subject")
    assert store.path == tmp_path / "lists.db"


def test_demo_preserves_saved_list_and_never_invents_real_ticker_prices(monkeypatch, tmp_path):
    import technical_ui
    import watchlist_store

    original_configuration = technical_ui.configured_watchlist
    original_loader = technical_ui.cached_market_history
    store = WatchlistStore(tmp_path / "preview.db")
    store.save("synthetic-preview", "synthetic-user", ["SIM-BETA", "AAPL"])
    monkeypatch.setattr(watchlist_store, "WatchlistStore", lambda _path: store)
    preview = APP.parent / "scripts" / "preview_technical.py"
    app = AppTest.from_file(preview, default_timeout=30).run()
    assert not app.exception
    assert app.text_area[0].value == "SIM-BETA, AAPL"
    assert len(app.get("plotly_chart")) == 1
    assert any("SIM-BETA · Esperar" in item.value for item in app.subheader)
    assert any("Para compra faltan:" in item.value for item in app.markdown)
    button(app, "Actualizar señales").click().run()
    table = app.dataframe[0].value
    real = table.loc[table["Acción"] == "AAPL"].iloc[0]
    assert real["Señal"] == "No evaluable" and pd.isna(real["Último cierre"])
    assert technical_ui.configured_watchlist is original_configuration
    assert technical_ui.cached_market_history is original_loader
    app.text_area[0].set_value("").run()
    button(app, "Guardar lista").click().run()
    reopened = AppTest.from_file(preview, default_timeout=30).run()
    assert not reopened.exception
    assert reopened.text_area[0].value == ""
    assert button(reopened, "Actualizar señales").disabled


def test_costs_can_eliminate_the_net_reward_and_ui_explains_it():
    def render():
        import pandas as pd

        from technical_analysis import BUY, TechnicalSnapshot
        from technical_ui import _render_reference_plan

        snapshot = TechnicalSnapshot("SIM", BUY, "", close=100,
                                     indicators=pd.DataFrame({"ATR14": [0.1]}))
        _render_reference_plan(snapshot, "USD", 0.01, 10)

    app = AppTest.from_function(render, default_timeout=30).run()
    assert not app.exception
    assert any("no deja beneficio neto" in item.value for item in app.warning)


def test_sic_broker_mode_does_not_offer_order_submission():
    def render():
        from technical_analysis import BUY, TechnicalSnapshot
        from technical_ui import _render_sic_trial

        _render_sic_trial(TechnicalSnapshot("SIM", BUY, ""))

    app = AppTest.from_function(render, default_timeout=30).run()
    assert not app.exception
    assert any(item.label == "Calcular borrador manual" for item in app.button)
    next(item for item in app.radio if item.label == "Forma de operación").set_value(
        "Conectar bróker"
    ).run()
    assert not app.exception
    assert any("Conexión de órdenes no disponible" in item.value for item in app.info)
    assert not any(item.label == "Calcular borrador manual" for item in app.button)
