import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from cryptography.fernet import Fernet
from streamlit.testing.v1 import AppTest

from case_workspace import CaseStore, Principal

APP = Path(__file__).resolve().parents[1] / "app_inversiones.py"


def test_navigation_explains_unconfigured_storage_without_access_to_real_secrets(monkeypatch):
    import access
    import workspace_ui
    from case_workspace import WorkspaceError

    monkeypatch.setattr(access, "require_access", lambda: None)

    def missing():
        raise WorkspaceError("Registro desactivado para esta prueba.")

    monkeypatch.setattr(workspace_ui, "configured_workspace", missing)
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.session_state["workspace_area"] = "Expedientes"
    app.run()
    assert not app.exception
    assert any("Registro desactivado" in item.value for item in app.info)
    app.session_state["workspace_area"] = "Guía operativa"
    app.run()
    assert not app.exception
    assert any("Preparar el expediente" in item.value for item in app.subheader)


def test_workspace_ui_persists_a_synthetic_account_and_reloads_it(monkeypatch, tmp_path):
    import access
    import workspace_ui

    monkeypatch.setattr(access, "require_access", lambda: None)
    store = CaseStore(tmp_path / "ui.db", Fernet.generate_key())
    admin = Principal("test-issuer", "test-admin", "ADMIN")
    store.initialize(admin)
    case = store.create(admin, "Piloto sintético")
    policy = {"identities": [{"issuer": admin.issuer, "subject": admin.subject, "role": admin.role}]}
    monkeypatch.setattr(workspace_ui, "configured_workspace", lambda: (store, admin, policy))
    app = AppTest.from_file(APP, default_timeout=15).run()
    app.session_state["workspace_area"] = "Expedientes"
    app.run()
    assert not app.exception
    next(item for item in app.text_input if item.label == "Alias de cartera o subcuenta").set_value(
        "BMV sintético"
    )
    next(item for item in app.button if item.label == "Añadir cuenta al expediente").click().run()
    assert not app.exception
    assert store.read(admin, case["id"])["accounts"][0]["portfolio"] == "BMV sintético"


def test_report_bundle_requires_explicit_case_and_account_and_binds_pdf_hash(monkeypatch, tmp_path):
    import workspace_ui

    store = CaseStore(tmp_path / "archive.db", Fernet.generate_key())
    admin = Principal("test-issuer", "test-admin", "ADMIN")
    store.initialize(admin)
    case = store.create(admin, "Caso sintético")
    state = store.update(
        admin,
        case["id"],
        1,
        "account",
        {
            "broker": "GBM",
            "product": "Trading MX",
            "portfolio": "BMV sintético",
            "currency": "MXN",
        },
    )
    account = state["accounts"][0]["id"]
    monkeypatch.setattr(workspace_ui, "configured_workspace", lambda: (store, admin, {}))
    app = AppTest.from_string(
        "from workspace_ui import render_archive_report\n"
        'render_archive_report(b"%PDF-synthetic", {"assets": ["AAA"]})',
        default_timeout=15,
    ).run()
    assert not app.exception
    assert not store.read(admin, case["id"]).get("artifacts")
    app.selectbox[0].set_value(case["id"]).run()
    app.selectbox[1].set_value(account).run()
    app.checkbox[0].set_value(True).run()
    app.button[0].click().run()
    assert not app.exception
    state = store.read(admin, case["id"])
    assert len(state["artifacts"]) == 1
    assert state["artifacts"][0]["account_id"] == account
    _, contents = store.artifact(admin, case["id"], state["artifacts"][0]["id"])
    with ZipFile(BytesIO(contents)) as archive:
        pdf = archive.read("comparativo_interno.pdf")
        manifest = json.loads(archive.read("parametros_y_procedencia.json"))
    assert manifest["report_sha256"] == sha256(pdf).hexdigest()
    assert manifest["account_id"] == account and manifest["case_id"] == case["id"]
    assert not manifest["client_delivery_allowed"]
