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

from csv_mapping import MAX_METADATA, pack_import, unpack_import
from gbm_movement_review import validate_draft
from operations_policy import MAX_POLICY_BYTES, validate_policy
from operations_proposal import MAX_PROPOSAL_BYTES, validate_proposal
from portfolio_core import PortfolioError

FILE_ROLES = ("ledger", "controls", "quotes", "fx", "repo_values", "nav", "flow_fx")
CODE_FILES = (
    "operations_review.py",
    "operations_review_ui.py",
    "operations_ui.py",
    "transaction_ledger.py",
    "ledger_reconciliation.py",
    "realized_performance.py",
)
MAX_FILE_BYTES = 2_000_000
V2_CODE_FILES = (
    *CODE_FILES,
    "gbm_documents.py",
    "gbm_movement_review.py",
    "gbm_movement_ui.py",
    "operations_input_forms.py",
    "operations_report.py",
)
V3_CODE_FILES = (
    *V2_CODE_FILES,
    "operations_proposal.py",
    "operations_proposal_bridge.py",
    "operations_proposal_ui.py",
    "executable_allocation.py",
    "implementation_costs.py",
)
V4_CODE_FILES = (
    *V3_CODE_FILES,
    "operations_comparison.py",
    "account_workflow.py",
    "allocation_analysis.py",
    "model_estimation.py",
    "portfolio_core.py",
    "covariance_calibration.py",
)
V5_CODE_FILES = (
    *V4_CODE_FILES,
    "operations_policy.py",
    "operations_policy_ui.py",
    "operations_cuts.py",
    "operations_status.py",
)
V6_CODE_FILES = (*V5_CODE_FILES, "csv_mapping.py", "csv_mapping_ui.py", "operations_recovery.py")
MAX_PACKAGE_BYTES = 15_000_000
MAX_MANIFEST_BYTES = 32_000
_FIELDS = {"schema", "kind", "created_at", "scope", "cutoff", "base", "files", "code_sha256", "review_state"}


def review_code_fingerprints(*, schema=1):
    root = Path(__file__).resolve().parent
    # Normalize source line endings for Windows/Linux portability; input CSV bytes stay exact.
    return {
        name: sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for name in (
            V6_CODE_FILES
            if schema == 6
            else V5_CODE_FILES
            if schema == 5
            else V4_CODE_FILES
            if schema == 4
            else V3_CODE_FILES
            if schema == 3
            else V2_CODE_FILES
            if schema == 2
            else CODE_FILES
        )
    }


def _scope(case_id, account_id):
    if (case_id is None) != (account_id is None):
        raise ValueError
    if case_id is not None and any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 160
        or any(ord(char) < 32 for char in value)
        for value in (case_id, account_id)
    ):
        raise ValueError
    return {"case_id": case_id, "account_id": account_id}


def _settings(cutoff, base):
    if (
        not isinstance(cutoff, str)
        or date.fromisoformat(cutoff).isoformat() != cutoff
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


def build_operations_review(
    files,
    *,
    cutoff,
    base,
    case_id=None,
    account_id=None,
    draft=None,
    summary=None,
    proposal=None,
    policy=None,
    csv_import=None,
):
    """Preserve exact CSV bytes and settings, including incomplete drafts, without approvals."""
    try:
        _settings(cutoff, base)
        scope = _scope(case_id, account_id)
        if (
            not isinstance(files, dict)
            or not set(files).issubset(FILE_ROLES)
            or ("ledger" not in files and draft is None and proposal is None and csv_import is None)
            or (csv_import is not None and draft is not None)
        ):
            raise ValueError
        if any(
            not isinstance(value, bytes) or not 0 < len(value) <= MAX_FILE_BYTES for value in files.values()
        ):
            raise ValueError
        manifest = {
            "schema": 1,
            "kind": "sig.operations.review",
            "created_at": datetime.now(UTC).isoformat(),
            "scope": scope,
            "cutoff": cutoff,
            "base": base,
            "files": {
                role: {"size": len(raw), "sha256": sha256(raw).hexdigest()} for role, raw in files.items()
            },
            "code_sha256": review_code_fingerprints(),
            "review_state": "PENDING_REVIEW",
        }
        draft_raw = None
        if draft is not None:
            validate_draft(draft)
            draft_raw = json.dumps(draft, ensure_ascii=False, allow_nan=False).encode()
            manifest.update(schema=2, draft={"size": len(draft_raw), "sha256": sha256(draft_raw).hexdigest()})
            manifest["code_sha256"] = review_code_fingerprints(schema=2)
        if summary is not None:
            if (
                (draft is None and proposal is None and policy is None and csv_import is None)
                or not isinstance(summary, bytes)
                or not 0 < len(summary) <= MAX_FILE_BYTES
            ):
                raise ValueError
            summary.decode("utf-8")
            manifest["summary"] = {"size": len(summary), "sha256": sha256(summary).hexdigest()}
        proposal_raw = None
        if proposal is not None:
            data = validate_proposal(proposal)
            if data["inputs"]["date"] != cutoff or data["inputs"]["currency"] != base:
                raise ValueError
            origin = data["inputs"]["book_origin"]
            if origin and (
                "ledger" not in files or origin["ledger_sha256"] != sha256(files["ledger"]).hexdigest()
            ):
                raise ValueError
            proposal_raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            schema = 4 if data["schema"] == 2 else 3
            manifest.update(
                schema=schema,
                proposal={"size": len(proposal_raw), "sha256": sha256(proposal_raw).hexdigest()},
            )
            manifest["code_sha256"] = review_code_fingerprints(schema=schema)
        policy_raw = None
        if policy is not None:
            proposed = validate_policy(policy)
            if "ledger" not in files or proposed["scope"] != scope or proposed["base"] != base:
                raise ValueError
            policy_raw = json.dumps(proposed, ensure_ascii=False, allow_nan=False).encode()
            manifest.update(
                schema=5, policy={"size": len(policy_raw), "sha256": sha256(policy_raw).hexdigest()}
            )
            manifest["code_sha256"] = review_code_fingerprints(schema=5)
        csv_meta = csv_source = None
        if csv_import is not None:
            csv_meta, csv_source = pack_import(csv_import)
            if csv_import["scope"] != scope:
                raise ValueError
            applied = csv_import["applied_ledger_sha256"]
            if applied is not None and (
                "ledger" not in files or sha256(files["ledger"]).hexdigest() != applied
            ):
                raise ValueError
            manifest.update(
                schema=6,
                csv_import={
                    "source": {"size": len(csv_source), "sha256": sha256(csv_source).hexdigest()},
                    "proposal": {"size": len(csv_meta), "sha256": sha256(csv_meta).hexdigest()},
                },
            )
            manifest["code_sha256"] = review_code_fingerprints(schema=6)
        stream = BytesIO()
        with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
            data = {"review.json": json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()}
            data.update({f"inputs/{role}.csv": raw for role, raw in files.items()})
            if draft_raw is not None:
                data["draft/gbm.json"] = draft_raw
            if summary is not None:
                data["evidence/review.txt"] = summary
            if proposal_raw is not None:
                data["proposal/proposal.json"] = proposal_raw
            if policy_raw is not None:
                data["policy/policy.json"] = policy_raw
            if csv_meta is not None:
                data["mapping/source.csv"] = csv_source
                data["mapping/proposal.json"] = csv_meta
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
            allowed = {
                "review.json",
                "draft/gbm.json",
                "evidence/review.txt",
                "proposal/proposal.json",
                "policy/policy.json",
                "mapping/source.csv",
                "mapping/proposal.json",
            } | {f"inputs/{role}.csv" for role in FILE_ROLES}
            if (
                len(entries) > len(allowed)
                or len(entries) != len(names)
                or "review.json" not in names
                or not names.issubset(allowed)
            ):
                raise ValueError
            raw_files = {}
            for entry in entries:
                limit = (
                    MAX_METADATA
                    if entry.filename == "mapping/proposal.json"
                    else MAX_POLICY_BYTES
                    if entry.filename == "policy/policy.json"
                    else MAX_MANIFEST_BYTES
                    if entry.filename == "review.json"
                    else MAX_PROPOSAL_BYTES
                    if entry.filename == "proposal/proposal.json"
                    else MAX_FILE_BYTES
                )
                if (
                    not 0 < entry.file_size <= limit
                    or entry.is_dir()
                    or entry.flag_bits & 1
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
            raw_files.pop("review.json"),
            object_pairs_hook=_unique_object,
            parse_constant=_no_constant,
        )
        if (
            not isinstance(manifest, dict)
            or type(manifest.get("schema")) is not int
            or manifest["schema"] not in {1, 2, 3, 4, 5, 6}
            or set(manifest)
            != (
                _FIELDS
                | {"csv_import"}
                | ({"policy"} if "policy" in manifest else set())
                | ({"proposal"} if "proposal" in manifest else set())
                | ({"summary"} if "summary" in manifest else set())
                if manifest["schema"] == 6
                else _FIELDS
                | {"policy"}
                | ({"proposal"} if "proposal" in manifest else set())
                | ({"draft"} if "draft" in manifest else set())
                | ({"summary"} if "summary" in manifest else set())
                if manifest["schema"] == 5
                else _FIELDS
                | {"proposal"}
                | ({"draft"} if "draft" in manifest else set())
                | ({"summary"} if "summary" in manifest else set())
                if manifest["schema"] in {3, 4}
                else _FIELDS | {"draft"} | ({"summary"} if "summary" in manifest else set())
                if manifest["schema"] == 2
                else _FIELDS
            )
            or manifest["kind"] != "sig.operations.review"
            or manifest["review_state"] != "PENDING_REVIEW"
        ):
            raise ValueError
        draft_raw = raw_files.pop("draft/gbm.json", None)
        summary_raw = raw_files.pop("evidence/review.txt", None)
        proposal_raw = raw_files.pop("proposal/proposal.json", None)
        policy_raw = raw_files.pop("policy/policy.json", None)
        csv_meta = raw_files.pop("mapping/proposal.json", None)
        csv_source = raw_files.pop("mapping/source.csv", None)
        csv_data = None
        if manifest["schema"] == 6:
            detail = manifest["csv_import"]
            if not isinstance(detail, dict) or set(detail) != {"source", "proposal"}:
                raise ValueError
            for label, raw in (("source", csv_source), ("proposal", csv_meta)):
                descriptor = detail[label]
                if (
                    raw is None
                    or not isinstance(descriptor, dict)
                    or set(descriptor) != {"size", "sha256"}
                    or type(descriptor["size"]) is not int
                    or descriptor["size"] != len(raw)
                    or descriptor["sha256"] != sha256(raw).hexdigest()
                ):
                    raise ValueError
            csv_data = unpack_import(csv_meta, csv_source, case_id=case_id, account_id=account_id)
            applied = csv_data["applied_ledger_sha256"]
            if applied is not None and (
                "inputs/ledger.csv" not in raw_files
                or sha256(raw_files["inputs/ledger.csv"]).hexdigest() != applied
            ):
                raise ValueError
        elif csv_meta is not None or csv_source is not None:
            raise ValueError
        policy_data = None
        if (("policy" in manifest) if manifest["schema"] == 6 else manifest["schema"] == 5) != (
            policy_raw is not None
        ):
            raise ValueError
        if policy_raw is not None:
            detail = manifest["policy"]
            if (
                not isinstance(detail, dict)
                or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int
                or detail["size"] != len(policy_raw)
                or detail["sha256"] != sha256(policy_raw).hexdigest()
                or "inputs/ledger.csv" not in raw_files
            ):
                raise ValueError
            policy_data = validate_policy(
                json.loads(policy_raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
            )
            if policy_data["scope"] != manifest["scope"] or policy_data["base"] != manifest["base"]:
                raise ValueError
        proposal_data = None
        if (("proposal" in manifest) if manifest["schema"] in {5, 6} else manifest["schema"] in {3, 4}) != (
            proposal_raw is not None
        ):
            raise ValueError
        if proposal_raw is not None:
            detail = manifest["proposal"]
            if (
                not isinstance(detail, dict)
                or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int
                or detail["size"] != len(proposal_raw)
                or detail["sha256"] != sha256(proposal_raw).hexdigest()
            ):
                raise ValueError
            proposal_data = validate_proposal(
                json.loads(proposal_raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
            )
            if manifest["schema"] not in {5, 6} and proposal_data["schema"] != (
                2 if manifest["schema"] == 4 else 1
            ):
                raise ValueError
            if (
                proposal_data["inputs"]["date"] != manifest["cutoff"]
                or proposal_data["inputs"]["currency"] != manifest["base"]
            ):
                raise ValueError
            origin = proposal_data["inputs"]["book_origin"]
            if origin and (
                "inputs/ledger.csv" not in raw_files
                or origin["ledger_sha256"] != sha256(raw_files["inputs/ledger.csv"]).hexdigest()
            ):
                raise ValueError
        if ("summary" in manifest) != (summary_raw is not None):
            raise ValueError
        if summary_raw is not None:
            detail = manifest["summary"]
            if (
                not isinstance(detail, dict)
                or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int
                or detail["size"] != len(summary_raw)
                or detail["sha256"] != sha256(summary_raw).hexdigest()
            ):
                raise ValueError
            summary_raw.decode("utf-8")
        if manifest["schema"] == 1:
            if draft_raw is not None or "inputs/ledger.csv" not in raw_files:
                raise ValueError
        elif manifest["schema"] == 2 or "draft" in manifest:
            detail = manifest["draft"]
            if (
                draft_raw is None
                or not isinstance(detail, dict)
                or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int
                or detail["size"] != len(draft_raw)
                or detail["sha256"] != sha256(draft_raw).hexdigest()
            ):
                raise ValueError
            validate_draft(
                json.loads(draft_raw, object_pairs_hook=_unique_object, parse_constant=_no_constant)
            )
        elif draft_raw is not None:
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
        if (
            not isinstance(code, dict)
            or set(code)
            != set(
                V6_CODE_FILES
                if manifest["schema"] == 6
                else V5_CODE_FILES
                if manifest["schema"] == 5
                else V4_CODE_FILES
                if manifest["schema"] == 4
                else V3_CODE_FILES
                if manifest["schema"] == 3
                else V2_CODE_FILES
                if manifest["schema"] == 2
                else CODE_FILES
            )
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in code.values()
            )
        ):
            raise ValueError
        files = {name[7:-4]: raw for name, raw in raw_files.items()}
        fingerprints = manifest["files"]
        if not isinstance(fingerprints, dict) or set(files) != set(fingerprints):
            raise ValueError
        for role, raw in files.items():
            detail = fingerprints[role]
            if (
                not isinstance(detail, dict)
                or set(detail) != {"size", "sha256"}
                or type(detail["size"]) is not int
                or detail["size"] != len(raw)
                or detail["sha256"] != sha256(raw).hexdigest()
            ):
                raise ValueError
        if draft_raw is not None:
            # Keep the historical two-value return contract; the validated draft is data, never approval.
            manifest = {**manifest, "draft_data": json.loads(draft_raw)}
        if proposal_data is not None:
            manifest = {**manifest, "proposal_data": proposal_data}
        if policy_data is not None:
            manifest = {**manifest, "policy_data": policy_data}
        if csv_data is not None:
            manifest = {**manifest, "csv_import_data": csv_data}
        return manifest, files
    except PortfolioError:
        raise
    except (
        BadZipFile,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        UnicodeError,
        EOFError,
        RuntimeError,
        NotImplementedError,
        ZlibError,
        RecursionError,
    ):
        raise PortfolioError(
            "El paquete de movimientos no supera la comprobación de formato e integridad."
        ) from None
