"""Synthetic source provenance, bounded v6 ZIP, legacy and encryption contracts."""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from test_csv_mapping import RAW, mapping
from test_operations_review import repack

import csv_mapping as mapper
from operations_recovery import inspect_package, movements_inventory
from operations_review import build_operations_review, read_operations_review
from portfolio_core import PortfolioError


def proposal(applied=False, scope=None):
    config = mapping()
    ledger = mapper.preview(RAW, config, {})["ledger"]
    return {
        "source": RAW,
        "mapping": config,
        "decisions": {},
        "scope": scope or {"case_id": None, "account_id": None},
        "applied_ledger_sha256": sha256(ledger).hexdigest() if applied else None,
    }, ledger


@pytest.mark.parametrize("applied", [False, True])
def test_v6_partial_or_applied_roundtrip_preserves_exact_origin_and_inventory(applied):
    origin, ledger = proposal(applied)
    files = {"ledger": ledger} if applied else {}
    manifest, raw = build_operations_review(
        files, cutoff="2026-01-10", base="MXN", csv_import=origin, summary=b"Ficticio: fuentes pendientes"
    )
    restored, inputs = read_operations_review(raw)
    assert manifest["schema"] == 6 and inputs == files
    assert restored["csv_import_data"] == origin
    assert restored["review_state"] == "PENDING_REVIEW"
    inventory = movements_inventory(restored, inputs)
    assert inventory["stage"] == ("Libro incluido" if applied else "Borrador CSV sin libro")
    assert {"Contenido": "Resumen TXT", "Guardado": "Incluido"} in inventory["contents"]
    assert {"Contenido": "CSV original y correspondencia", "Guardado": "Incluido"} in inventory["contents"]
    assert inspect_package(raw)["schema"] == 6
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.read("mapping/source.csv") == RAW


def test_v6_rejects_missing_tampered_source_or_mapping_and_applied_book_mismatch():
    origin, ledger = proposal(True)
    _, raw = build_operations_review({"ledger": ledger}, cutoff="2026-01-10", base="MXN", csv_import=origin)
    for member, changed in [("mapping/source.csv", RAW + b"\n"), ("mapping/proposal.json", b"{}")]:
        with pytest.raises(PortfolioError):
            read_operations_review(repack(raw, remove={member}, add=[(member, changed)]))
        with pytest.raises(PortfolioError):
            read_operations_review(repack(raw, remove={member}))
    for files in ({}, {"ledger": ledger.replace(b",50,", b",51,")}):
        with pytest.raises(PortfolioError):
            build_operations_review(files, cutoff="2026-01-10", base="MXN", csv_import=origin)


def test_v6_scope_and_exclusive_source_and_unknown_members():
    origin, ledger = proposal(scope={"case_id": "c", "account_id": "a"})
    with pytest.raises(PortfolioError):
        build_operations_review({}, cutoff="2026-01-10", base="MXN", csv_import=origin)
    _, raw = build_operations_review(
        {}, cutoff="2026-01-10", base="MXN", csv_import=origin, case_id="c", account_id="a"
    )
    with pytest.raises(PortfolioError):
        read_operations_review(raw, case_id="c", account_id="b")
    with pytest.raises(PortfolioError):
        read_operations_review(repack(raw, add=[("mapping/execute.py", b"bad")]), case_id="c", account_id="a")
    with pytest.raises(PortfolioError):
        build_operations_review(
            {"ledger": ledger},
            cutoff="2026-01-10",
            base="MXN",
            csv_import=origin,
            case_id="c",
            account_id="a",
            draft={},
        )


def test_v6_reopening_keeps_inputs_when_financial_engine_rules_change(monkeypatch):
    origin, ledger = proposal(True)
    _, raw = build_operations_review({"ledger": ledger}, cutoff="2026-01-10", base="MXN", csv_import=origin)
    monkeypatch.setattr(mapper, "Event", lambda *a, **k: (_ for _ in ()).throw(PortfolioError("Regla nueva")))
    restored, files = read_operations_review(raw)
    assert files["ledger"] == ledger and restored["csv_import_data"] == origin
    assert not mapper.preview(RAW, mapping(), {})["ready"]


@pytest.mark.parametrize("value", [[], {}, True, 3, None])
def test_malformed_mapping_rules_fail_controlled(value):
    config = mapping()
    config["fields"]["Importe"]["mode"] = value
    with pytest.raises(PortfolioError):
        mapper.preview(RAW, config, {})


def test_new_source_template_retires_basis_and_cannot_carry_decisions():
    template = mapper.write_template(mapping(), mapper.read_source(RAW))
    assert mapper.read_template(template, RAW.replace(b",50,", b",51,"))["basis"] == ""
    origin, _ = proposal()
    origin = deepcopy(origin)
    origin["decisions"] = {"2": {"action": "exclude", "reason": "", "source": "fake"}}
    with pytest.raises(PortfolioError):
        mapper.pack_import(origin)


def test_v6_encrypted_local_copy_recovers_exact_zip(tmp_path):
    import local_review_storage as storage

    origin, ledger = proposal(True)
    _, raw = build_operations_review({"ledger": ledger}, cutoff="2026-01-10", base="MXN", csv_import=origin)
    source, key, target, restored = (
        tmp_path / n for n in ["source.zip", "key.sigkey", "copy.siglocal", "restored.zip"]
    )
    source.write_bytes(raw)
    storage.generate_key(key)
    storage.save_copy(source, target, key)
    assert storage.verify_copy(target, key)["schema"] == 6
    storage.restore_copy(target, restored, key)
    assert restored.read_bytes() == raw
