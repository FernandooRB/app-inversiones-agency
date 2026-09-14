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
    app.run()
    assert not app.exception
    assert len(app.metric) == 4
    app.text_input[2].set_value("25,25,25,25").run()
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
