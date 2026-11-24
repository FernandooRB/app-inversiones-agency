"""Regression cases from the independent final review, only temporary synthetic files."""

import threading
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest

import local_review_storage as storage
from operations_recovery import inspect_package, local_copy_guide
from operations_review import build_operations_review
from portfolio_core import PortfolioError


@pytest.fixture
def copy_files(tmp_path):
    source = tmp_path / "review.zip"
    source.write_bytes(build_operations_review({"ledger": b"Fictional"}, cutoff="2026-01-10", base="MXN")[1])
    key = tmp_path / "key.sigkey"
    storage.generate_key(key)
    copy = tmp_path / "copy.siglocal"
    storage.save_copy(source, copy, key)
    return source, key, copy


@pytest.mark.parametrize("second_file", [False, True])
def test_rotation_rejects_identical_key_material_before_creating_output(copy_files, tmp_path, second_file):
    _, key, copy = copy_files
    other = tmp_path / "same-key.sigkey" if second_file else key
    if second_file:
        other.write_bytes(key.read_bytes())
    dest = tmp_path / "new.siglocal"
    with pytest.raises(PortfolioError):
        storage.rotate_copy(copy, dest, key, other)
    assert not dest.exists() and copy.exists()


@pytest.mark.parametrize("alteration", [b"\n", b" ", b"\t"])
def test_noncanonical_encrypted_representation_never_verifies_or_restores(copy_files, tmp_path, alteration):
    _, key, copy = copy_files
    raw = copy.read_bytes()
    copy.write_bytes(raw[:10] + alteration + raw[10:])
    with pytest.raises(PortfolioError):
        storage.verify_copy(copy, key)
    dest = tmp_path / "reopened.zip"
    with pytest.raises(PortfolioError):
        storage.restore_copy(copy, dest, key)
    assert not dest.exists()


def test_unknown_zip_extraction_version_has_controlled_redacted_rejection():
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        info = ZipInfo("review.json")
        info.extract_version = 99
        archive.writestr(info, b"PRIVATE-CANARY")
    with pytest.raises(PortfolioError):
        inspect_package(stream.getvalue())


def test_competing_delete_cannot_reuse_name_under_an_old_confirmed_hash(copy_files, monkeypatch):
    source, key, copy = copy_files
    digest = sha256(copy.read_bytes()).hexdigest()
    verified, release = threading.Event(), threading.Event()
    original_verify = storage.verify_copy
    first_errors = []

    def paused_verify(*args, **kwargs):
        info = original_verify(*args, **kwargs)
        if threading.current_thread().name == "first-delete":
            verified.set()
            assert release.wait(10)
        return info

    def first_delete():
        try:
            storage.delete_copy(copy, key, confirmation=digest)
        except Exception as exc:
            first_errors.append(type(exc).__name__)

    monkeypatch.setattr(storage, "verify_copy", paused_verify)
    first = threading.Thread(target=first_delete, name="first-delete")
    first.start()
    assert verified.wait(10)
    rejected = False
    try:
        try:
            storage.delete_copy(copy, key, confirmation=digest)
        except PortfolioError:
            rejected = True
        if not rejected:
            storage.save_copy(source, copy, key)
    finally:
        release.set()
        first.join(10)
    assert rejected, "A second delete must not replace the file while the first hash is in use"
    assert not first.is_alive() and not first_errors
    storage.save_copy(source, copy, key)
    assert storage.verify_copy(copy, key)["sha256"] == sha256(source.read_bytes()).hexdigest()


def test_guide_uses_git_ignored_key_extension_consistently():
    guide = local_copy_guide().decode()
    assert "clave.txt" not in guide
    assert "clave.sigkey" in guide


def test_active_current_context_proposal_requires_explicit_replacement(monkeypatch):
    from types import SimpleNamespace

    import operations_review_ui as ui

    state = {
        "_execution_proposal": {
            "context": (None, None),
            "inputs": {"date": "2026-01-10"},
            "result": {"cash": 100},
        }
    }
    monkeypatch.setattr(ui, "st", SimpleNamespace(session_state=state))
    assert ui._has_current_inputs((None, None, None, None))
    assert not ui._has_current_inputs((None, None, {"id": "other-case"}, "other-account"))


def test_active_proposal_ui_warns_without_changing_it_on_preview():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        """
from io import BytesIO
from unittest.mock import patch
import streamlit as st
from operations_review import build_operations_review
from operations_review_ui import open_review
proposal={"context":(None,None),"inputs":{"date":"2026-01-10"},"result":{"cash":100}}
st.session_state.setdefault("_execution_proposal",proposal)
raw=build_operations_review({"ledger":b"Fictitious"},cutoff="2026-01-10",base="MXN")[1]
with patch.object(st,"file_uploader",return_value=BytesIO(raw)):
    open_review((None,None,None,None))
""",
        default_timeout=35,
    ).run()
    assert not app.exception and not app.error
    assert app.button(key="ops_review_open_temporary").label == "Reemplazar revisión con este paquete"
    assert any("Se reemplazarán" in item.value for item in app.warning)
    assert app.session_state["_execution_proposal"]["result"]["cash"] == 100
