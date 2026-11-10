"""Portable, unapproved inputs for the operations screen; never restore results or consent."""

import json
import re
from datetime import UTC, date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from stat import S_IFMT, S_IFREG
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile, ZipInfo
from zlib import error as ZlibError

from portfolio_core import PortfolioError

FILE_ROLES = ("ledger", "controls", "quotes", "fx", "repo_values", "nav", "flow_fx")
CODE_FILES = (
    "operations_review.py", "operations_review_ui.py", "operations_ui.py",
    "transaction_ledger.py", "ledger_reconciliation.py", "realized_performance.py",
)
MAX_FILE_BYTES = 2_000_000
MAX_PACKAGE_BYTES = 15_000_000
MAX_MANIFEST_BYTES = 32_000
_FIELDS = {"schema", "kind", "created_at", "scope", "cutoff", "base", "files", "code_sha256", "review_state"}


def review_code_fingerprints():
    root = Path(__file__).resolve().parent
    # Normalize source line endings for Windows/Linux portability; input CSV bytes stay exact.
    return {
        name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in CODE_FILES
    }


def _scope(case_id, account_id):
    if (case_id is None) != (account_id is None):
        raise ValueError
    if case_id is not None and any(
        not isinstance(value, str) or not value.strip() or len(value) > 160
        or any(ord(char) < 32 for char in value)
        for value in (case_id, account_id)
    ):
        raise ValueError
    return {"case_id": case_id, "account_id": account_id}


def _settings(cutoff, base):
    if (
        not isinstance(cutoff, str) or date.fromisoformat(cutoff).isoformat() != cutoff
        or base not in {"MXN", "USD"}
    ):
        raise ValueError
    if date.fromisoformat(cutoff) > date.today():
        raise ValueError


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _no_constant(_value):
    raise ValueError


def build_operations_review(files, *, cutoff, base, case_id=None, account_id=None):
    """Preserve exact CSV bytes and settings, including incomplete drafts, without approvals."""
    try:
        _settings(cutoff, base)
        scope = _scope(case_id, account_id)
        if not isinstance(files, dict) or "ledger" not in files or not set(files).issubset(FILE_ROLES):
            raise ValueError
        if any(
            not isinstance(value, bytes) or not 0 < len(value) <= MAX_FILE_BYTES for value in files.values()
        ):
            raise ValueError
        manifest = {
            "schema": 1, "kind": "sig.operations.review",
            "created_at": datetime.now(UTC).isoformat(), "scope": scope, "cutoff": cutoff, "base": base,
            "files": {
                role: {"size": len(raw), "sha256": sha256(raw).hexdigest()} for role, raw in files.items()
            },
            "code_sha256": review_code_fingerprints(), "review_state": "PENDING_REVIEW",
        }
        stream = BytesIO()
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            data = {"review.json": json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()}
            data.update({f"inputs/{role}.csv": raw for role, raw in files.items()})
            for name, raw in sorted(data.items()):
                archive.writestr(ZipInfo(name, (1980, 1, 1, 0, 0, 0)), raw, compress_type=ZIP_DEFLATED)
        contents = stream.getvalue()
        if len(contents) > MAX_PACKAGE_BYTES:
            raise ValueError
        return manifest, contents
    except (ValueError, TypeError):
        raise PortfolioError(
            "El paquete requiere un libro, CSV de hasta 2 MB, corte válido y moneda MXN/USD."
        ) from None


def read_operations_review(contents, *, case_id=None, account_id=None):
    """Read a bounded allowlist in memory; no extraction, code execution or financial approval."""
    try:
        expected_scope = _scope(case_id, account_id)
        if not isinstance(contents, bytes) or not 0 < len(contents) <= MAX_PACKAGE_BYTES:
            raise ValueError
        with ZipFile(BytesIO(contents)) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            allowed = {"review.json"} | {f"inputs/{role}.csv" for role in FILE_ROLES}
            if (
                len(entries) > len(allowed) or len(entries) != len(names)
                or not {"review.json", "inputs/ledger.csv"}.issubset(names) or not names.issubset(allowed)
            ):
                raise ValueError
            raw_files = {}
            for entry in entries:
                limit = MAX_MANIFEST_BYTES if entry.filename == "review.json" else MAX_FILE_BYTES
                if (
                    not 0 < entry.file_size <= limit or entry.is_dir() or entry.flag_bits & 1
                    or entry.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                    or S_IFMT(entry.external_attr >> 16) not in {0, S_IFREG}
                ):
                    raise ValueError
                with archive.open(entry) as source:
                    raw = source.read(limit + 1)
                if len(raw) != entry.file_size or len(raw) > limit:
                    raise ValueError
                raw_files[entry.filename] = raw
        manifest = json.loads(
            raw_files.pop("review.json"), object_pairs_hook=_unique_object, parse_constant=_no_constant,
        )
        if (
            not isinstance(manifest, dict) or set(manifest) != _FIELDS
            or type(manifest["schema"]) is not int or manifest["schema"] != 1
            or manifest["kind"] != "sig.operations.review" or manifest["review_state"] != "PENDING_REVIEW"
        ):
            raise ValueError
        _settings(manifest["cutoff"], manifest["base"])
        scope = manifest["scope"]
        if not isinstance(scope, dict) or set(scope) != {"case_id", "account_id"}:
            raise ValueError
        _scope(scope["case_id"], scope["account_id"])
        if scope != expected_scope:
            raise PortfolioError(
                "Abre la misma cuenta y expediente del paquete, o usa revisión temporal si no tiene cuenta."
            )
        created_at = datetime.fromisoformat(manifest["created_at"])
        if created_at.utcoffset() is None:
            raise ValueError
        code = manifest["code_sha256"]
        if not isinstance(code, dict) or set(code) != set(CODE_FILES) or any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in code.values()
        ):
            raise ValueError
        files = {name[7:-4]: raw for name, raw in raw_files.items()}
        fingerprints = manifest["files"]
        if not isinstance(fingerprints, dict) or set(files) != set(fingerprints):
            raise ValueError
        for role, raw in files.items():
            detail = fingerprints[role]
            if (
                not isinstance(detail, dict) or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int or detail["size"] != len(raw)
                or detail["sha256"] != sha256(raw).hexdigest()
            ):
                raise ValueError
        return manifest, files
    except PortfolioError:
        raise
    except (BadZipFile, ValueError, KeyError, TypeError, OSError, UnicodeError,
            EOFError, RuntimeError, NotImplementedError, ZlibError):
        raise PortfolioError(
            "El paquete de movimientos no supera la comprobación de formato e integridad."
        ) from None
