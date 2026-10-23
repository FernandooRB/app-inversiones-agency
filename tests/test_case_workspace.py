import json
import sqlite3
from datetime import date
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet

from case_workspace import (
    CaseStore,
    Principal,
    WorkspaceError,
    case_readiness,
    principal_from_claims,
)


@pytest.fixture
def workspace(tmp_path):
    key = Fernet.generate_key()
    store = CaseStore(tmp_path / "register.db", key)
    admin = Principal("https://issuer.test", "admin", "ADMIN")
    analyst = Principal("https://issuer.test", "analyst", "ANALYST")
    reviewer = Principal("https://issuer.test", "reviewer", "REVIEWER")
    store.initialize(admin)
    return store, key, admin, analyst, reviewer


def profile():
    return {
        "objective": "Objetivo sintético confidencial",
        "horizon_months": 24,
        "liquidity_mxn": 1234.56,
        "loss_capacity_pct": 10.0,
        "loss_tolerance_pct": 8.0,
        "experience": "BASICA",
        "restrictions": "Sin apalancamiento",
        "reviewed_on": date.today().isoformat(),
    }


def test_encrypted_profile_is_persistent_private_and_versioned(workspace):
    store, key, admin, analyst, _ = workspace
    state = store.create(analyst, "Expediente de prueba confidencial")
    assert store.list_cases(analyst)[0]["id"] == state["id"]
    changed = store.update(analyst, state["id"], 1, "profile", profile())
    reopened = CaseStore(store.path, key)
    assert reopened.read(analyst, state["id"])["profile"] == profile()
    assert changed["revision"] == 2
    history = reopened.history(admin, state["id"])
    assert history[0]["state"]["profile"] is None
    assert history[-2]["state"]["profile"] == profile()
    raw = store.path.read_bytes()
    assert b"confidencial" not in raw
    assert b"1234.56" not in raw
    assert not case_readiness(changed)["client_delivery_allowed"]


def test_case_permissions_are_checked_for_every_operation(workspace):
    store, _, admin, analyst, reviewer = workspace
    state = store.create(analyst, "Caso")
    assert store.list_cases(reviewer) == []
    for operation in (
        lambda: store.read(reviewer, state["id"]),
        lambda: store.history(reviewer, state["id"]),
        lambda: store.update(reviewer, state["id"], 1, "profile", profile()),
        lambda: store.attach(reviewer, state["id"], 1, "x.txt", b"x"),
        lambda: store.artifact(reviewer, state["id"], "a" * 32),
        lambda: store.review(reviewer, state["id"], 1, "TECNICA", "Prueba"),
        lambda: store.grant(analyst, state["id"], reviewer),
    ):
        with pytest.raises(WorkspaceError):
            operation()
    store.grant(admin, state["id"], reviewer)
    assert store.read(reviewer, state["id"])["revision"] == 2
    with pytest.raises(WorkspaceError):
        store.update(reviewer, state["id"], 2, "profile", profile())


def test_reviews_are_independent_bound_to_revision_and_never_release(workspace):
    store, _, admin, analyst, reviewer = workspace
    state = store.create(analyst, "Caso")
    store.grant(admin, state["id"], reviewer)
    state = store.update(analyst, state["id"], 2, "profile", profile())
    with pytest.raises(WorkspaceError):
        store.review(admin, state["id"], 2, "TECNICA", "Versión anterior")
    first = store.review(reviewer, state["id"], 3, "TECNICA", "Revisión interna de prueba")
    with pytest.raises(WorkspaceError):
        store.review(reviewer, state["id"], 3, "FINANCIERA", "Repetida")
    final = store.review(admin, state["id"], 3, "FINANCIERA", "Revisión interna de prueba")
    assert len(final["reviews"]) == 2
    assert case_readiness(final)["current_reviews"] == 2
    assert not case_readiness(final)["client_delivery_allowed"]
    changed = store.update(analyst, state["id"], first["revision"], "profile", profile())
    assert case_readiness(changed)["current_reviews"] == 0
    # The last editor cannot use a global admin role to approve its own edit.
    changed = store.update(admin, state["id"], changed["revision"], "profile", profile())
    with pytest.raises(WorkspaceError):
        store.review(admin, state["id"], changed["revision"], "TECNICA", "Autorrevisión")


def test_stale_updates_are_rejected_without_losing_current_data(workspace):
    store, _, _, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    store.update(analyst, state["id"], 1, "profile", profile())
    with pytest.raises(WorkspaceError, match="Otra persona"):
        store.update(analyst, state["id"], 1, "profile", {**profile(), "horizon_months": 5})
    assert store.read(analyst, state["id"])["profile"]["horizon_months"] == 24


def test_hierarchy_and_evidence_do_not_claim_authenticity(workspace):
    store, _, _, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    account = {"broker": "GBM", "product": "Trading MX", "portfolio": "BMV de prueba", "currency": "MXN"}
    state = store.update(analyst, state["id"], 1, "account", account)
    with pytest.raises(WorkspaceError):
        store.update(analyst, state["id"], 2, "account", account)
    state = store.update(
        analyst,
        state["id"],
        2,
        "evidence",
        {
            "control": "positions",
            "sha256": sha256(b"synthetic").hexdigest(),
            "reference": "Documento sintético, página 1",
            "reviewed_on": date.today().isoformat(),
            "expires_on": None,
        },
    )
    assert state["evidence"]["positions"]["status"] == "DECLARADA_REQUIERE_COTEJO"
    assert not case_readiness(state)["client_delivery_allowed"]


def test_files_are_encrypted_bound_to_case_and_invalidate_reviews(workspace):
    store, _, admin, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    store.review(admin, state["id"], 1, "TECNICA", "Prueba")
    artifact_id = store.attach(analyst, state["id"], 1, "reporte.txt", b"CONTENIDO_PRIVADO_SINTETICO")
    state = store.read(analyst, state["id"])
    assert state["revision"] == 2
    assert case_readiness(state)["current_reviews"] == 0
    metadata, data = store.artifact(analyst, state["id"], artifact_id)
    assert data == b"CONTENIDO_PRIVADO_SINTETICO"
    assert metadata["sha256"] == sha256(data).hexdigest()
    assert data not in store.path.read_bytes()
    second = store.create(analyst, "Otro caso")
    with pytest.raises(WorkspaceError):
        store.artifact(analyst, second["id"], artifact_id)


@pytest.mark.parametrize("target", ["snapshot", "audit", "inventory", "key"])
def test_tampering_is_detected_and_wrong_keys_do_not_mutate(workspace, target):
    store, _, admin, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    if target == "key":
        raw = store.path.read_bytes()
        with pytest.raises(WorkspaceError):
            CaseStore(store.path, Fernet.generate_key()).read(admin, state["id"])
        assert raw == store.path.read_bytes()
        return
    with sqlite3.connect(store.path) as db:
        if target == "snapshot":
            db.execute("UPDATE cases SET token=?", (b"invalid",))
        elif target == "audit":
            db.execute("UPDATE audit SET action='REVIEW'")
        else:
            db.execute("DELETE FROM cases")
    with pytest.raises(WorkspaceError):
        store.list_cases(admin)


def test_backup_is_recoverable_and_never_overwrites(workspace, tmp_path):
    store, key, admin, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    destination = tmp_path / "backup.db"
    assert store.backup(admin, destination)["integrity"] == "VERIFIED"
    recovered = CaseStore(destination, key)
    assert recovered.read(analyst, state["id"])["alias"] == "Caso"
    with pytest.raises(WorkspaceError):
        store.backup(admin, destination)
    with pytest.raises(WorkspaceError):
        store.backup(analyst, tmp_path / "forbidden.db")


def test_archive_recovery_and_purge_remove_live_case_and_files(workspace):
    store, _, admin, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    file_id = store.attach(analyst, state["id"], 1, "x.txt", b"Prueba")
    with pytest.raises(WorkspaceError):
        store.purge(admin, state["id"], "Caso")
    state = store.update(admin, state["id"], 2, "archived", True)
    with pytest.raises(WorkspaceError):
        store.update(analyst, state["id"], 3, "profile", profile())
    state = store.update(admin, state["id"], 3, "archived", False)
    assert not state["archived"]
    store.update(admin, state["id"], 4, "archived", True)
    with pytest.raises(WorkspaceError):
        store.purge(admin, state["id"], "Otro alias")
    store.purge(admin, state["id"], "Caso")
    assert store.list_cases(admin) == []
    with pytest.raises(WorkspaceError):
        store.artifact(admin, state["id"], file_id)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM cases").fetchone()[0] == 0


def test_oidc_role_requires_valid_expiry_unique_identity_and_explicit_role():
    claims = {"iss": "https://issuer.test", "sub": "opaque-id", "exp": 200}
    row = {"issuer": claims["iss"], "subject": claims["sub"], "role": "ANALYST"}
    assert principal_from_claims(claims, {"identities": [row]}, now=100).role == "ANALYST"
    for policy in (
        {"identities": [{"issuer": claims["iss"], "subject": claims["sub"]}]},
        {"identities": [row, row]},
        {"identities": []},
    ):
        with pytest.raises(WorkspaceError):
            principal_from_claims(claims, policy, now=100)
    with pytest.raises(WorkspaceError):
        principal_from_claims(claims, {"identities": [row]}, now=300)
    assert "opaque-id" not in json.dumps({"actor": Principal(claims["iss"], claims["sub"], "ANALYST").actor})


def test_revocation_is_immediate_and_restoration_uses_new_path(workspace, tmp_path):
    store, key, admin, analyst, reviewer = workspace
    state = store.create(analyst, "Caso")
    store.grant(admin, state["id"], reviewer)
    store.revoke(admin, state["id"], reviewer)
    with pytest.raises(WorkspaceError):
        store.read(reviewer, state["id"])
    backup = tmp_path / "backup_new.db"
    recovered = tmp_path / "recovered.db"
    store.backup(admin, backup)
    assert store.restore_new(admin, backup, recovered)["integrity"] == "VERIFIED"
    assert CaseStore(recovered, key).read(analyst, state["id"])["alias"] == "Caso"
    with pytest.raises(WorkspaceError):
        store.restore_new(admin, backup, recovered)


def test_corrupt_or_missing_attachment_blocks_backup_verification(workspace, tmp_path):
    store, _, admin, analyst, _ = workspace
    state = store.create(analyst, "Caso")
    artifact_id = store.attach(analyst, state["id"], 1, "x.txt", b"Synthetic file")
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE artifacts SET token=? WHERE id=?", (b"corrupted", artifact_id))
    with pytest.raises(WorkspaceError):
        store.restore_check(admin, store.path)
    with sqlite3.connect(store.path) as db:
        db.execute("DELETE FROM artifacts")
    with pytest.raises(WorkspaceError):
        store.restore_check(admin, store.path)


def test_oidc_rejects_boolean_expiry_and_malformed_policy():
    from access import authorized

    row = {"issuer": "test", "subject": "user", "role": "ANALYST"}
    assert not authorized({"iss": "test", "sub": "user", "exp": True}, {"identities": [row]}, now=0)
    claims = {"iss": "test", "sub": "user", "exp": 200}
    assert not authorized(claims, {"identities": "invalid"}, now=100)
    assert not authorized(claims, {"identities": [None]}, now=100)
    with pytest.raises(WorkspaceError):
        principal_from_claims(claims, {"identities": [{**row, "role": []}]}, now=100)


def test_access_change_does_not_allow_the_content_author_to_review_own_work(workspace):
    store, _, admin, _, reviewer = workspace
    state = store.create(admin, "Caso")
    other_admin = Principal("test-issuer", "other-admin", "ADMIN")
    store.grant(other_admin, state["id"], reviewer)
    with pytest.raises(WorkspaceError):
        store.review(admin, state["id"], 2, "TECNICA", "Autorrevisión tras cambio de acceso")
    assert store.read(admin, state["id"])["content_editor"] == admin.actor
