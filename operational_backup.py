"""Portable encrypted backups for cases, drafts/jobs and the separate watchlist DB."""

import json
import sqlite3
from contextlib import closing
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from cryptography.fernet import InvalidToken

from case_workspace import CaseStore, WorkspaceError

MAX_BACKUP_BYTES = 256_000_000


def _safe_new(path):
    path = Path(path)
    if (
        path.exists()
        or not path.parent.is_dir()
        or any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)
        )
    ):
        raise WorkspaceError("El respaldo o restauración requiere un destino nuevo sin enlaces.")
    return path


def create_backup_bundle(store, principal, destination, *, technical_path=None):
    destination = _safe_new(destination)
    with TemporaryDirectory(prefix="sig-backup-", dir=destination.parent) as directory:
        temporary = Path(directory)
        store.backup(principal, temporary / "cases.db")
        files = {"cases.db": (temporary / "cases.db").read_bytes()}
        if technical_path is not None and Path(technical_path).is_file():
            technical = Path(technical_path)
            if any(p.is_symlink() for p in (technical, *technical.parents)):
                raise WorkspaceError("El seguimiento no admite enlaces para respaldar.")
            with (
                closing(sqlite3.connect(technical)) as source,
                closing(sqlite3.connect(temporary / "technical.db")) as target,
            ):
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise WorkspaceError("El seguimiento no superó la comprobación estructural.")
            files["technical.db"] = (temporary / "technical.db").read_bytes()
        if sum(map(len, files.values())) > MAX_BACKUP_BYTES:
            raise WorkspaceError("El respaldo supera el límite de este procedimiento.")
        manifest = {"schema": 1, "files": {name: sha256(raw).hexdigest() for name, raw in files.items()}}
        buffer = BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            for name, raw in files.items():
                archive.writestr(name, raw)
        encrypted = store.master.encrypt(buffer.getvalue())
        with destination.open("xb") as handle:
            handle.write(encrypted)
    return verify_backup_bundle(store, principal, destination)


def verify_backup_bundle(store, principal, source, *, restore_to=None):
    if principal.role != "ADMIN":
        raise WorkspaceError("Sólo administración puede verificar o restaurar respaldos.")
    source = Path(source)
    if not 0 < source.stat().st_size <= MAX_BACKUP_BYTES * 2:
        raise WorkspaceError("El respaldo está vacío o excede el límite.")
    try:
        decrypted = store.master.decrypt(source.read_bytes())
        with ZipFile(BytesIO(decrypted)) as archive:
            names = archive.namelist()
            if (
                len(names) != len(set(names))
                or not set(names).issubset({"manifest.json", "cases.db", "technical.db"})
                or not {"manifest.json", "cases.db"}.issubset(names)
                or sum(item.file_size for item in archive.infolist()) > MAX_BACKUP_BYTES
            ):
                raise ValueError
            manifest = json.loads(archive.read("manifest.json"))
            files = {name: archive.read(name) for name in names if name != "manifest.json"}
            if manifest != {
                "schema": 1,
                "files": {name: sha256(raw).hexdigest() for name, raw in files.items()},
            }:
                raise ValueError
        with TemporaryDirectory(prefix="sig-restore-", dir=source.parent) as directory:
            temporary = Path(directory)
            for name, raw in files.items():
                (temporary / name).write_bytes(raw)
            result = CaseStore(temporary / "cases.db", store._key).restore_check(
                principal, temporary / "cases.db"
            )
            if "technical.db" in files:
                with closing(sqlite3.connect(temporary / "technical.db")) as db:
                    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError
            if restore_to is not None:
                destination = _safe_new(restore_to)
                destination.mkdir()
                for name, raw in files.items():
                    with (destination / name).open("xb") as handle:
                        handle.write(raw)
        return {**result, "technical_included": "technical.db" in files, "encrypted": True}
    except (InvalidToken, BadZipFile, ValueError, KeyError, sqlite3.Error):
        raise WorkspaceError(
            "El respaldo no supera la verificación; no se restauró ningún registro."
        ) from None
