"""Portable inputs must survive a session loss without importing approvals or arbitrary ZIP members."""

import json
from copy import deepcopy
from io import BytesIO
from stat import S_IFLNK
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

import operations_review as review
from portfolio_core import PortfolioError

FILES = {
    "ledger": b"ID,Fecha,Tipo\nopening,2026-01-01,OPEN_CASH\n",
    "controls": "Fecha,Fuente\n2026-01-10,Estado ficticio de revisión\n".encode("utf-8-sig"),
    "quotes": b"Fecha,Instrumento,Moneda,Precio\n2026-01-10,SIM-A,MXN,100.01\n",
    "fx": b"Fecha,Moneda,Base,Tasa,Fuente\n2026-01-10,USD,MXN,20.01,Prueba\n",
    "repo_values": b"Fecha,Referencia,Moneda,Valor,Fuente\n2026-01-10,repo-1,MXN,,\n",
    "nav": b"Fecha,NAV\n2026-01-01,100\n2026-01-10,150\n",
    "flow_fx": b"Fecha,Moneda,Base,Tasa,Fuente\n2026-01-05,USD,MXN,20.02,Prueba\n",
}


def bundle(**kwargs):
    return review.build_operations_review(FILES, cutoff="2026-01-10", base="MXN", **kwargs)


def repack(contents, *, transform=None, add=(), remove=()):
    with ZipFile(BytesIO(contents)) as original:
        entries = [(item, original.read(item)) for item in original.infolist() if item.filename not in remove]
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        for item, raw in entries:
            if item.filename == "review.json" and transform:
                manifest = json.loads(raw)
                transform(manifest)
                raw = json.dumps(manifest).encode()
            archive.writestr(item, raw)
        for name, raw in add:
            archive.writestr(name, raw)
    return stream.getvalue()


def test_round_trip_preserves_all_exact_bytes_and_incomplete_evidence_without_results():
    manifest, contents = bundle()
    recovered, files = review.read_operations_review(contents)
    assert files == FILES and recovered == manifest
    assert recovered["review_state"] == "PENDING_REVIEW" and recovered["base"] == "MXN"
    assert recovered["code_sha256"] == review.review_code_fingerprints()
    assert "result" not in recovered and "confirmations" not in recovered
    # A blank reporto value stays blank; the container does not turn it into approved input.
    assert files["repo_values"].endswith(b"MXN,,\n")


def test_bound_package_can_be_opened_only_in_its_declared_scope():
    _, contents = bundle(case_id="case-A", account_id="account-A")
    _, files = review.read_operations_review(contents, case_id="case-A", account_id="account-A")
    assert files == FILES
    for scope in ({}, {"case_id": "case-A", "account_id": "account-B"},
                  {"case_id": "case-B", "account_id": "account-A"}):
        with pytest.raises(PortfolioError, match="misma cuenta"):
            review.read_operations_review(contents, **scope)


def test_temporary_review_is_not_silently_attached_to_a_case():
    _, contents = bundle()
    with pytest.raises(PortfolioError, match="misma cuenta"):
        review.read_operations_review(contents, case_id="case-A", account_id="account-A")


@pytest.mark.parametrize("files", [{}, {"ledger": b""}, {"ledger": "text"},
                                     {"ledger": b"ok", "secret": b"no"},
                                     {"ledger": b"x" * (review.MAX_FILE_BYTES + 1)}])
def test_export_rejects_missing_oversized_or_unsupported_inputs(files):
    with pytest.raises(PortfolioError):
        review.build_operations_review(files, cutoff="2026-01-10", base="MXN")


@pytest.mark.parametrize("settings", [
    {"cutoff": "20260110", "base": "MXN"}, {"cutoff": "NaT", "base": "MXN"},
    {"cutoff": "9999-01-01", "base": "MXN"}, {"cutoff": "2026-01-10", "base": "EUR"},
    {"cutoff": "2026-01-10", "base": ["MXN"]},
])
def test_export_rejects_invalid_period_or_currency(settings):
    with pytest.raises(PortfolioError):
        review.build_operations_review(FILES, **settings)


@pytest.mark.parametrize("field,value", [
    ("schema", True), ("kind", "sig.analysis"), ("review_state", "APPROVED"),
    ("confirmations", {"flows": True}), ("files", []), ("created_at", "2026-01-10"),
    ("created_at", True), ("code_sha256", None), ("scope", None), ("cutoff", "NaT"),
])
def test_untrusted_manifest_does_not_inject_state_or_unsupported_metadata(field, value):
    _, contents = bundle()
    altered = repack(contents, transform=lambda manifest: manifest.update({field: value}))
    with pytest.raises(PortfolioError):
        review.read_operations_review(altered)


def test_changed_engine_is_informational_and_does_not_block_recovering_inputs():
    _, contents = bundle()
    altered = repack(contents, transform=lambda manifest: manifest["code_sha256"].update(
        {"operations_ui.py": "a" * 64}
    ))
    manifest, files = review.read_operations_review(altered)
    assert files == FILES and manifest["code_sha256"] != review.review_code_fingerprints()


@pytest.mark.parametrize("name", ["../outside.csv", "/tmp/outside.csv", "inputs/extra.csv", "run.json"])
def test_rejects_unexpected_or_traversal_members(name):
    _, contents = bundle()
    with pytest.raises(PortfolioError):
        review.read_operations_review(repack(contents, add=[(name, b"not allowed")]))


def test_modified_or_missing_csv_does_not_pass_integrity():
    _, contents = bundle()
    changed = repack(contents, remove={"inputs/ledger.csv"}, add=[("inputs/ledger.csv", b"changed")])
    for altered in (changed, repack(contents, remove={"inputs/ledger.csv"}),
                    repack(contents, remove={"inputs/nav.csv"})):
        with pytest.raises(PortfolioError):
            review.read_operations_review(altered)


def test_duplicate_names_are_rejected_even_when_contents_match():
    _, contents = bundle()
    with pytest.warns(UserWarning, match="Duplicate name"):
        duplicated = repack(contents, add=[("inputs/ledger.csv", FILES["ledger"])])
    with pytest.raises(PortfolioError):
        review.read_operations_review(duplicated)


def test_duplicate_json_keys_and_nonfinite_constants_are_rejected():
    manifest, contents = bundle()
    original = json.dumps(manifest).encode()
    for changed in (b'{"schema":1,' + original[1:], original.replace(b'"schema": 1', b'"schema": NaN')):
        altered = repack(contents, remove={"review.json"}, add=[("review.json", changed)])
        with pytest.raises(PortfolioError):
            review.read_operations_review(altered)


def test_symlink_and_unsupported_compression_are_rejected():
    _, contents = bundle()
    symlink = ZipInfo("inputs/ledger.csv")
    symlink.create_system = 3
    symlink.external_attr = (S_IFLNK | 0o777) << 16
    compressed = ZipInfo("inputs/ledger.csv")
    compressed.compress_type = ZIP_BZIP2
    for entry in (symlink, compressed):
        altered = repack(contents, remove={"inputs/ledger.csv"}, add=[(entry, FILES["ledger"])])
        with pytest.raises(PortfolioError):
            review.read_operations_review(altered)


def test_compressed_oversized_member_is_rejected_before_decompression(monkeypatch):
    manifest, _ = bundle()
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("inputs/ledger.csv", b"x" * (review.MAX_FILE_BYTES + 1))
        archive.writestr("review.json", json.dumps(manifest))
    monkeypatch.setattr(ZipFile, "open", lambda *a, **k: pytest.fail("oversized member was opened"))
    with pytest.raises(PortfolioError):
        review.read_operations_review(stream.getvalue())


def test_raw_package_limit_and_corrupt_archives_are_rejected(monkeypatch):
    _, contents = bundle()
    monkeypatch.setattr(review, "MAX_PACKAGE_BYTES", len(contents) - 1)
    for raw in (contents, b"not a zip", b"", contents[:90]):
        with pytest.raises(PortfolioError):
            review.read_operations_review(raw)


def test_manifest_size_and_role_fingerprints_are_validated():
    _, contents = bundle()
    for transform in (
        lambda m: m["files"]["nav"].update(size=True),
        lambda m: m["files"]["nav"].update(sha256="0" * 64),
        lambda m: m["files"].update(extra={"size": 1, "sha256": "0" * 64}),
    ):
        altered = repack(contents, transform=transform)
        with pytest.raises(PortfolioError):
            review.read_operations_review(altered)
    oversized = repack(contents, remove={"review.json"}, add=[("review.json", b" " * 32_001)])
    with pytest.raises(PortfolioError):
        review.read_operations_review(oversized)


def test_build_does_not_mutate_the_supplied_file_mapping():
    files = deepcopy(FILES)
    review.build_operations_review(files, cutoff="2026-01-10", base="USD")
    assert files == FILES


def test_deep_json_is_a_controlled_rejection():
    _, contents = bundle()
    nested = b"[" * 2000 + b"0" + b"]" * 2000
    altered = repack(contents, remove={"review.json"}, add=[("review.json", nested)])
    with pytest.raises(PortfolioError):
        review.read_operations_review(altered)


def test_code_fingerprints_ignore_platform_line_endings(monkeypatch):
    monkeypatch.setattr(review.Path, "read_bytes", lambda _path: b"first\r\nsecond\r\n")
    windows = review.review_code_fingerprints()
    monkeypatch.setattr(review.Path, "read_bytes", lambda _path: b"first\nsecond\n")
    assert windows == review.review_code_fingerprints()
