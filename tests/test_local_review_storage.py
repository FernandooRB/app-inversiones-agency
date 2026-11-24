"""Fictional-only independent recovery, authorization and filesystem safety cases."""

import json
import subprocess
import sys
from hashlib import sha256

import pytest
from cryptography.fernet import Fernet

import local_review_storage as storage
from operations_recovery import inspect_package
from operations_review import build_operations_review
from portfolio_core import PortfolioError


def package(**scope):
    return build_operations_review(
        {"ledger": b"ID,Importe\nfictitious,100.01\n"},
        cutoff="2026-01-10",
        base="MXN",
        **scope,
    )[1]


@pytest.fixture
def local(tmp_path):
    key = tmp_path / "key.txt"
    storage.generate_key(key)
    source = tmp_path / "review.zip"
    source.write_bytes(package())
    return key, source, tmp_path / "copy.siglocal"


def test_inventory_never_exposes_financial_values_or_treats_book_as_approval():
    info = inspect_package(package())
    assert info["kind"] == "sig.operations.review" and info["schema"] == 1
    assert info["stage"] == "Libro incluido"
    assert info["review_state"] == "PENDING_REVIEW"
    assert "100.01" not in json.dumps(info)
    assert info["originals_included"] is False


def test_ciphertext_recovers_exact_package_in_new_process_and_is_private(local, tmp_path):
    key, source, copy = local
    saved = storage.save_copy(source, copy, key)
    assert source.read_bytes() not in copy.read_bytes()
    assert b"fictitious" not in copy.read_bytes()
    assert saved["sha256"] == sha256(source.read_bytes()).hexdigest()
    result = storage.verify_copy(copy, key)
    assert result["review_state"] == "PENDING_REVIEW"
    dest = tmp_path / "reopened.zip"
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.local_review",
            "restore",
            "--source",
            str(copy),
            "--key-file",
            str(key),
            "--destination",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0, cli.stderr
    assert dest.read_bytes() == source.read_bytes()
    assert key.read_text() not in cli.stdout + cli.stderr
    assert "fictitious" not in cli.stdout + cli.stderr
    assert str(tmp_path) not in cli.stdout + cli.stderr


@pytest.mark.parametrize("fault", ["key", "altered", "truncated", "authenticated_bad_zip"])
def test_corruption_or_wrong_key_never_creates_output(local, tmp_path, fault):
    key, source, copy = local
    storage.save_copy(source, copy, key)
    if fault == "key":
        key.write_bytes(Fernet.generate_key())
    elif fault == "altered":
        raw = bytearray(copy.read_bytes())
        raw[-20] ^= 1
        copy.write_bytes(raw)
    elif fault == "truncated":
        copy.write_bytes(copy.read_bytes()[:40])
    else:
        copy.write_bytes(Fernet(key.read_bytes()).encrypt(b"private invalid ZIP text"))
    dest = tmp_path / "restored.zip"
    with pytest.raises(PortfolioError):
        storage.restore_copy(copy, dest, key)
    assert not dest.exists() and source.exists()


def test_foreign_scope_never_rebound_and_valid_scope_can_restore(local, tmp_path):
    key, source, copy = local
    source.write_bytes(package(case_id="case-a", account_id="account-a"))
    with pytest.raises(PortfolioError):
        storage.save_copy(source, copy, key)
    assert not copy.exists()
    storage.save_copy(source, copy, key, case_id="case-a", account_id="account-a")
    with pytest.raises(PortfolioError):
        storage.restore_copy(copy, tmp_path / "other.zip", key, case_id="case-a", account_id="account-b")
    dest = tmp_path / "correct.zip"
    storage.restore_copy(copy, dest, key, case_id="case-a", account_id="account-a")
    assert dest.read_bytes() == source.read_bytes()


def test_existing_destination_key_and_source_are_never_overwritten(local, tmp_path):
    key, source, copy = local
    original_key = key.read_bytes()
    original_source = source.read_bytes()
    with pytest.raises(PortfolioError):
        storage.generate_key(key)
    assert key.read_bytes() == original_key
    copy.write_bytes(b"keep encrypted older copy")
    with pytest.raises(PortfolioError):
        storage.save_copy(source, copy, key)
    assert copy.read_bytes() == b"keep encrypted older copy"
    with pytest.raises(PortfolioError):
        storage.save_copy(source, source, key)
    assert source.read_bytes() == original_source


def test_rotate_creates_independent_copy_preserves_old_and_exact_bytes(local, tmp_path):
    key, source, copy = local
    storage.save_copy(source, copy, key)
    old = copy.read_bytes()
    new_key = tmp_path / "new-key.txt"
    storage.generate_key(new_key)
    rotated = tmp_path / "rotated.siglocal"
    storage.rotate_copy(copy, rotated, key, new_key)
    assert copy.read_bytes() == old
    assert storage.verify_copy(rotated, new_key)["sha256"] == sha256(source.read_bytes()).hexdigest()
    with pytest.raises(PortfolioError):
        storage.verify_copy(rotated, key)
    with pytest.raises(PortfolioError):
        storage.verify_copy(copy, new_key)


def test_delete_requires_exact_ciphertext_hash_and_only_deletes_selected_file(local):
    key, source, copy = local
    storage.save_copy(source, copy, key)
    digest = sha256(copy.read_bytes()).hexdigest()
    with pytest.raises(PortfolioError):
        storage.delete_copy(copy, key, confirmation="0" * 64)
    assert copy.exists()
    storage.delete_copy(copy, key, confirmation=digest)
    assert not copy.exists() and source.exists() and key.exists()


def test_oversized_input_rejected_before_reading_and_bad_key_is_controlled(local, monkeypatch):
    key, source, copy = local
    monkeypatch.setattr(storage, "MAX_PACKAGE_BYTES", 2)
    with pytest.raises(PortfolioError):
        storage.save_copy(source, copy, key)
    assert not copy.exists()
    key.write_bytes(b"wrong")
    with pytest.raises(PortfolioError):
        storage.verify_copy(source, key)


def test_symlink_input_parent_and_destination_rejected_without_following(local, tmp_path):
    key, source, copy = local
    link = tmp_path / "link.zip"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("OS does not permit symlink creation; Linux CI covers this case")
    with pytest.raises(PortfolioError):
        storage.save_copy(link, copy, key)
    folder = tmp_path / "linked"
    folder.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PortfolioError):
        storage.save_copy(source, folder / "forbidden.siglocal", key)
    with pytest.raises(PortfolioError):
        storage.generate_key(link)
    assert not copy.exists() and not (tmp_path / "forbidden.siglocal").exists()


def test_cli_errors_redact_paths_sources_and_keys(local):
    key, source, copy = local
    source.write_bytes(b"private-secret-canary")
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.local_review",
            "save",
            "--source",
            str(source),
            "--key-file",
            str(key),
            "--destination",
            str(copy),
        ],
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 2
    assert json.loads(cli.stdout)["status"] == "OPERATION_REJECTED"
    assert not cli.stderr and "canary" not in cli.stdout and str(source) not in cli.stdout
    assert not copy.exists()


def test_group_package_uses_existing_scope_reader(local, tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/book_consolidation_fixture.py", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    key, _, copy = local
    group = tmp_path / "group_fixture.zip"
    info = storage.save_copy(group, copy, key)
    assert info["kind"] == "sig.operations.consolidation"
    assert info["account_count"] == 2
    assert storage.verify_copy(copy, key)["review_state"] == "PENDING_REVIEW"
