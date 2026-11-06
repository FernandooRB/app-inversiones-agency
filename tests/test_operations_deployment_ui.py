"""Fail-closed deployment configuration and UI smoke checks; no external account needed."""

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from deployment_runtime import validate_configuration


def configuration(root):
    return {
        "workspace": {
            "enabled": True,
            "database_path": str(root / "cases.db"),
            "encryption_key": Fernet.generate_key().decode(),
        },
        "technical_watchlist": {"backend": "sqlite", "database_path": str(root / "technical.db")},
        "auth": {
            "client_id": "synthetic",
            "client_secret": "synthetic-secret",
            "cookie_secret": "a" * 40,
            "server_metadata_url": "https://issuer.test/.well-known/config",
            "redirect_uri": "https://staging.test/oauth2callback",
        },
        "access": {
            "identities": [{"issuer": "https://issuer.test", "subject": "synthetic", "role": "ADMIN"}]
        },
    }


def test_deployment_requires_durable_paths_oidc_and_admin(tmp_path):
    config = configuration(tmp_path)
    assert validate_configuration(config, tmp_path) == config
    config["workspace"]["database_path"] = str(tmp_path.parent / "outside.db")
    with pytest.raises(ValueError):
        validate_configuration(config, tmp_path)
    config = configuration(tmp_path)
    config["auth"]["redirect_uri"] = "http://staging.test/oauth2callback"
    with pytest.raises(ValueError):
        validate_configuration(config, tmp_path)
    config = configuration(tmp_path)
    config["access"]["identities"][0]["role"] = "VIEWER"
    with pytest.raises(ValueError):
        validate_configuration(config, tmp_path)


def test_operations_view_renders_without_private_workspace(monkeypatch):
    import access
    import workspace_ui
    from case_workspace import WorkspaceError

    monkeypatch.setattr(access, "require_access", lambda: None)

    def missing():
        raise WorkspaceError("Registro desactivado")

    monkeypatch.setattr(workspace_ui, "configured_workspace", missing)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "app_inversiones.py", default_timeout=30
    ).run()
    next(item for item in app.pills if item.label == "Área de trabajo").set_value("Operación").run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Operación por cuenta"
    assert any(item.label == "Calcular propuesta de títulos" and item.disabled for item in app.button)
