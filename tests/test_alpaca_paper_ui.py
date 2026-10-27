import time
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import alpaca_paper_ui
from alpaca_paper import AlpacaPaperError, PaperAccount, PaperAccountSnapshot, PaperOrder, PaperPosition


def claims_for(subject="alice"):
    return {"iss": "issuer", "sub": subject, "exp": time.time() + 3600}


def configuration():
    return {"access": {"identities": [{"issuer": "issuer", "subject": "alice"},
                                       {"issuer": "issuer", "subject": "bob"}]},
            "alpaca_paper": {"enabled": True, "owner_issuer": "issuer", "owner_subject": "alice",
                             "api_key": "SYNTHETIC_PAPER_KEY", "secret_key": "SYNTHETIC_PAPER_SECRET"}}


@pytest.mark.parametrize("subject, expiry, reason", [
    ("bob", None, "propietario"), ("stranger", None, "autorizada"), ("alice", 0, "expirado"),
])
def test_configuration_checks_identity_before_creating_client(monkeypatch, subject, expiry, reason):
    claims = claims_for(subject)
    if expiry is not None:
        claims["exp"] = expiry
    monkeypatch.setattr(alpaca_paper_ui.st, "secrets", configuration())
    monkeypatch.setattr(alpaca_paper_ui.st, "user", SimpleNamespace(to_dict=lambda: claims))

    def fail_client(*args, **kwargs):
        raise AssertionError("Client must not be created for an unauthorized identity")

    monkeypatch.setattr(alpaca_paper_ui, "AlpacaPaperClient", fail_client)
    with pytest.raises(AlpacaPaperError, match=reason):
        alpaca_paper_ui.configured_alpaca_paper("issuer", subject)


def test_configured_client_only_accepts_verified_owner_and_explicit_enable(monkeypatch):
    config = configuration()
    monkeypatch.setattr(alpaca_paper_ui.st, "secrets", config)
    monkeypatch.setattr(alpaca_paper_ui.st, "user", SimpleNamespace(to_dict=claims_for))
    assert alpaca_paper_ui.configured_alpaca_paper("issuer", "alice").configuration_signature
    with pytest.raises(AlpacaPaperError, match="autorizada"):
        alpaca_paper_ui.configured_alpaca_paper("issuer", "bob")
    config["alpaca_paper"]["enabled"] = False
    with pytest.raises(AlpacaPaperError, match="Secrets"):
        alpaca_paper_ui.configured_alpaca_paper("issuer", "alice")


def snapshot():
    return PaperAccountSnapshot(
        PaperAccount("10000000-0000-0000-0000-000000000001", "PAPER0001", "ACTIVE", "USD",
                     Decimal(1000), Decimal(900), Decimal(1800), False, False),
        (PaperPosition("SIM", "us_equity", "long", Decimal(1), Decimal(99), Decimal(100),
                       Decimal(100), Decimal(1)),),
        (PaperOrder("synthetic-order", "SIM", "buy", "limit", "new", Decimal(1), None,
                    Decimal(0), None, Decimal(98), datetime(2026, 10, 27, 20, tzinfo=UTC)),),
        datetime(2026, 10, 27, 20, 30, tzinfo=UTC),
    )


class FakeClient:
    configuration_signature = "synthetic-configuration-1"
    calls = 0
    fail = False

    def fetch_snapshot(self):
        self.calls += 1
        if self.fail:
            raise AlpacaPaperError("No se pudo consultar la cuenta.")
        return snapshot()


def open_connection(monkeypatch, client):
    def factory(issuer, subject):
        if subject != "alice":
            raise AlpacaPaperError("La cuenta pertenece a otro usuario.")
        return client

    monkeypatch.setattr(alpaca_paper_ui, "configured_alpaca_paper", factory)
    return AppTest.from_string(
        "import streamlit as st\nfrom alpaca_paper_ui import render_alpaca_paper\n"
        "render_alpaca_paper('issuer', st.session_state.get('test_subject', 'alice'))",
        default_timeout=30,
    ).run()


def test_connection_queries_only_after_click_and_renders_snapshot_values(monkeypatch):
    client = FakeClient()
    app = open_connection(monkeypatch, client)
    assert client.calls == 0 and not app.exception
    app.button(key="technical_alpaca_refresh").click().run()
    assert not app.exception and client.calls == 1
    assert [item.value for item in app.metric] == ["1,000.00", "900.00", "1,800.00"]
    assert app.dataframe[0].value.loc[0, "Símbolo"] == "SIM"
    assert app.dataframe[1].value.loc[0, "Cantidad ejecutada"] == 0
    assert app.dataframe[1].value.loc[0, "Precio ejecutado · USD"] is None
    assert not app.text_input
    assert len(app.button) == 1
    app.run()
    assert client.calls == 1


def test_failed_refresh_labels_previous_snapshot_as_stale(monkeypatch):
    client = FakeClient()
    app = open_connection(monkeypatch, client)
    app.button(key="technical_alpaca_refresh").click().run()
    client.fail = True
    app.button(key="technical_alpaca_refresh").click().run()
    assert not app.exception and app.error
    assert any("no se actualizaron" in item.value for item in app.caption)
    assert app.metric[0].value == "1,000.00"


def test_credential_rotation_and_user_change_remove_private_snapshot(monkeypatch):
    client = FakeClient()
    app = open_connection(monkeypatch, client)
    app.button(key="technical_alpaca_refresh").click().run()
    client.configuration_signature = "synthetic-configuration-2"
    app.run()
    assert not app.metric and not app.dataframe
    assert client.calls == 1
    app.button(key="technical_alpaca_refresh").click().run()
    app.session_state["test_subject"] = "bob"
    app.run()
    assert not app.exception and not app.metric and not app.dataframe
    assert "_technical_alpaca_snapshot" not in app.session_state.filtered_state
    assert client.calls == 2
