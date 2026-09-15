from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
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
    app.checkbox[0].set_value(True).run()
    assert not app.exception
    assert not app.error
    assert len(app.metric) == 8
    app.radio[0].set_value("Retiros").run()
    withdrawal = next(item for item in app.number_input if item.label.startswith("Retiro mensual"))
    withdrawal.set_value(50_000.0).run()
    assert not app.exception
    assert not app.error
    assert any(item.label == "Con retiro no cubierto" for item in app.metric)
    app.checkbox[1].set_value(True).run()
    assert not app.exception
    assert not app.error
    app.checkbox[2].set_value(True).run()
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
