from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from access import authorized
from currencies import convert_prices, currency_map
from portfolio_core import PortfolioError


def test_authorization_requires_exact_identity_and_unexpired_claim():
    policy = {"identities": [{"issuer": "issuer", "subject": "123"}]}
    claims = {"iss": "issuer", "sub": "123", "exp": 200}
    assert authorized(claims, policy, now=100)
    for changed in ({"iss": "other"}, {"sub": "other"}, {"exp": 100}, {"exp": None}, {"exp": float("nan")}):
        assert not authorized(claims | changed, policy, now=100)
    assert not authorized(claims, {}, now=100)


def test_unconfigured_app_stops_before_market_data(monkeypatch):
    import portfolio_core

    def forbidden(*args, **kwargs):
        pytest.fail("Unauthenticated download")

    monkeypatch.setattr(portfolio_core.yf, "download", forbidden)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app_inversiones.py").run()
    assert not app.exception
    assert app.error
    assert not app.metric


def test_fx_direction_and_missing_dates():
    prices = pd.DataFrame({"US": [10.0, 11.0, 12.0], "MX": [200.0, 210.0, 220.0]})
    result = convert_prices(
        prices, {"US": "USD", "MX": "MXN"}, "MXN", {"USDMXN=X": pd.Series([20.0, 19.0, np.nan])}
    )
    assert result["US"].tolist() == [200.0, 209.0]
    assert result["MX"].tolist() == [200.0, 210.0]
    assert len(result) == 2
    with pytest.raises(PortfolioError):
        convert_prices(prices, {"US": "USD", "MX": "MXN"}, "MXN", {})
    with pytest.raises(PortfolioError):
        convert_prices(prices, {"US": "USD", "MX": "MXN"}, "MXN", {"USDMXN=X": pd.Series([20.0, -1.0, 20.0])})


def test_currency_mapping_rejects_ambiguous_units():
    assert currency_map(["A", "B"], "usd, mxn") == {"A": "USD", "B": "MXN"}
    with pytest.raises(PortfolioError):
        currency_map(["A", "B"], "USD")
    with pytest.raises(PortfolioError):
        currency_map(["A"], "GBp")


@pytest.mark.parametrize(
    "logged_in,claims,expected",
    [
        (False, {}, "Iniciar sesión"),
        (True, {"iss": "wrong", "sub": "123", "exp": 9999999999}, "Cerrar sesión"),
        (True, {"iss": "issuer", "sub": "123", "exp": 1}, "Cerrar sesión"),
    ],
)
def test_access_gate_denies_before_analysis(monkeypatch, logged_in, claims, expected):
    from types import SimpleNamespace

    import access

    class Stopped(Exception):
        pass

    buttons = []

    def stop():
        raise Stopped

    fake = SimpleNamespace(
        secrets={
            "auth": {"client_id": "configured"},
            "access": {"identities": [{"issuer": "issuer", "subject": "123"}]},
        },
        user=SimpleNamespace(is_logged_in=logged_in, to_dict=lambda: claims),
        error=lambda message: None,
        stop=stop,
        button=lambda label: buttons.append(label) or False,
    )
    monkeypatch.setattr(access, "st", fake)
    with pytest.raises(Stopped):
        access.require_access()
    assert buttons == [expected]
