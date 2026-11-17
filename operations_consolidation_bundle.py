"""Portable, bounded, data-only multi-account proposals. Originals and consent stay out."""

import json
import stat
import zlib
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from operations_consolidation import (
    MAX_CSV_BYTES,
    MAX_INPUT_BYTES,
    canonical,
    consolidate_books,
    prepare_accounts,
)
from portfolio_core import PortfolioError

MAX_ZIP_BYTES = 12_000_000
MAX_MANIFEST_BYTES = 32_000


def build_bundle(entries, *, base="MXN", fx=b"", links=b"", case_id=None, allowed_accounts=None):
    report = consolidate_books(
        entries, base=base, fx=fx, links=links, case_id=case_id, allowed_accounts=allowed_accounts
    )
    members = {"accounts/" + e["alias"] + ".cut.json": e["cut"] for e in entries}
    for name, raw in (("inputs/fx.csv", fx), ("inputs/transfers.csv", links)):
        if raw:
            members[name] = raw
    manifest = {
        "schema": 1,
        "kind": "sig.operations.consolidation",
        "base": base,
        "cutoff": report["cutoff"],
        "case_id": case_id,
        "review_state": "PENDING_REVIEW",
        "accounts": [{"alias": e["alias"], "source": e["source"]} for e in entries],
        "engine": report["engine"],
        "members": {n: {"size": len(b), "sha256": sha256(b).hexdigest()} for n, b in members.items()},
    }
    raw_manifest = canonical(manifest)
    if len(raw_manifest) > MAX_MANIFEST_BYTES:
        raise PortfolioError("El manifiesto de consolidación supera el límite.")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("consolidation.json", raw_manifest)
        for name, raw in members.items():
            archive.writestr(name, raw)
    result = output.getvalue()
    if len(result) > MAX_ZIP_BYTES:
        raise PortfolioError("El paquete de consolidación supera 12 MB.")
    return result


def read_bundle(raw, *, case_id=None, allowed_accounts=None):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError
            obj[key] = value
        return obj

    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ZIP_BYTES:
            raise ValueError
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [i.filename for i in infos]
            if len(infos) > 13 or len(set(names)) != len(names) or "consolidation.json" not in names:
                raise ValueError
            if sum(i.file_size for i in infos) > MAX_INPUT_BYTES + 2 * MAX_CSV_BYTES + MAX_MANIFEST_BYTES:
                raise ValueError
            for info in infos:
                if (
                    info.flag_bits & 1
                    or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.is_dir()
                    or info.file_size
                    > (MAX_MANIFEST_BYTES if info.filename == "consolidation.json" else 2_000_000)
                ):
                    raise ValueError
            manifest = json.loads(
                archive.read("consolidation.json").decode("utf-8"), object_pairs_hook=unique
            )
            if (
                not isinstance(manifest, dict)
                or set(manifest)
                != {
                    "schema",
                    "kind",
                    "base",
                    "cutoff",
                    "case_id",
                    "review_state",
                    "accounts",
                    "engine",
                    "members",
                }
                or type(manifest["schema"]) is not int
                or manifest["schema"] != 1
                or manifest["kind"] != "sig.operations.consolidation"
                or manifest["review_state"] != "PENDING_REVIEW"
                or manifest["case_id"] != case_id
                or not isinstance(manifest["accounts"], list)
                or not 2 <= len(manifest["accounts"]) <= 10
                or not isinstance(manifest["members"], dict)
            ):
                raise ValueError
            engine = manifest["engine"]
            if (
                not isinstance(engine, dict)
                or len(engine) > 20
                or any(
                    not isinstance(k, str)
                    or len(k) > 120
                    or not isinstance(v, str)
                    or len(v) != 64
                    or any(c not in "0123456789abcdef" for c in v)
                    for k, v in engine.items()
                )
            ):
                raise ValueError
            # Alias validation precedes path construction and every non-manifest read.
            import re

            for row in manifest["accounts"]:
                if (
                    not isinstance(row, dict)
                    or set(row) != {"alias", "source"}
                    or not isinstance(row["alias"], str)
                    or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,59}", row["alias"])
                ):
                    raise ValueError
            cut_names = {"accounts/" + row["alias"] + ".cut.json" for row in manifest["accounts"]}
            allowed = cut_names | {"inputs/fx.csv", "inputs/transfers.csv"}
            if (
                set(names) - {"consolidation.json"} != set(manifest["members"])
                or not cut_names.issubset(names)
                or not set(manifest["members"]).issubset(allowed)
            ):
                raise ValueError
            members = {}
            for name, descriptor in manifest["members"].items():
                if (
                    not isinstance(descriptor, dict)
                    or set(descriptor) != {"size", "sha256"}
                    or type(descriptor["size"]) is not int
                    or descriptor["size"] != archive.getinfo(name).file_size
                    or name.startswith("inputs/")
                    and descriptor["size"] > MAX_CSV_BYTES
                ):
                    raise ValueError
                data = archive.read(name)
                if sha256(data).hexdigest() != descriptor["sha256"]:
                    raise ValueError
                members[name] = data
        entries = [
            {**row, "cut": members["accounts/" + row["alias"] + ".cut.json"]} for row in manifest["accounts"]
        ]
        states = prepare_accounts(entries, case_id=case_id, allowed_accounts=allowed_accounts)
        if states[0]["cut"]["payload"]["cutoff"] != manifest["cutoff"]:
            raise ValueError
        saved = {
            "entries": entries,
            "base": manifest["base"],
            "fx": members.get("inputs/fx.csv", b""),
            "links": members.get("inputs/transfers.csv", b""),
            "review_state": "PENDING_REVIEW",
        }
        consolidate_books(
            entries,
            base=saved["base"],
            fx=saved["fx"],
            links=saved["links"],
            case_id=case_id,
            allowed_accounts=allowed_accounts,
        )
        return saved
    except (
        BadZipFile,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        ArithmeticError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
        PortfolioError,
    ):
        raise PortfolioError(
            "El paquete de consolidación no supera formato, integridad, límites o pertenencia. "
            "La revisión actual se conserva."
        ) from None
