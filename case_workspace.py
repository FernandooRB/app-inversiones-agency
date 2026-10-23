"""Encrypted, versioned internal case register. No method authorizes client delivery.

The server owns the master key; callers must come from verified OIDC identities.
This is a single-server store, not a substitute for host security or legal review.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROLES = {"ADMIN", "ANALYST", "REVIEWER", "VIEWER"}
EVIDENCE = {
    "positions": "Posiciones y cobertura al corte",
    "identity": "Identidad de instrumentos",
    "primary_prices": "Precios principales y permiso de uso",
    "reference_prices": "Precios de referencia y permiso de uso",
    "tariff": "Comisiones aplicables a la cuenta",
    "model_validation": "Validación del modelo y costos",
    "legal": "Revisión del servicio y contratación",
    "labor": "Revisión de actividad externa",
    "privacy": "Privacidad y tratamiento de datos",
    "operations": "Acceso, respaldo y entrega segura",
}
PRODUCTS = ("Trading MX", "Trading USA", "Smart Cash", "Smart Cash Dólares", "Advisory", "Otro")
_ID = re.compile(r"^[a-f0-9]{32}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")


class WorkspaceError(ValueError):
    """Safe errors must never contain input values, keys or document contents."""


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    role: str

    @property
    def actor(self) -> str:
        if (
            not all(isinstance(value, str) and value for value in (self.issuer, self.subject, self.role))
            or self.role not in ROLES
        ):
            raise WorkspaceError("Identidad o rol no autorizado.")
        return hashlib.sha256(_json([self.issuer, self.subject])).hexdigest()


def principal_from_claims(claims: dict, policy: dict, *, now=None) -> Principal:
    from access import authorized

    if not authorized(claims, policy, now):
        raise WorkspaceError("La sesión no está autorizada.")
    matches = [
        row
        for row in policy.get("identities", [])
        if isinstance(row, Mapping)
        and row.get("issuer") == claims.get("iss")
        and row.get("subject") == claims.get("sub")
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("role"), str) or matches[0]["role"] not in ROLES:
        raise WorkspaceError("Configura un único rol explícito para esta identidad.")
    return Principal(claims["iss"], claims["sub"], matches[0]["role"])


def _json(value) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _text(value, maximum=300) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise WorkspaceError("El texto falta o tiene un formato no permitido.")
    return value.strip()


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise WorkspaceError("Identificador de expediente inválido.")
    return value


def validate_profile(profile: dict) -> dict:
    expected = {
        "objective",
        "horizon_months",
        "liquidity_mxn",
        "loss_capacity_pct",
        "loss_tolerance_pct",
        "experience",
        "restrictions",
        "reviewed_on",
    }
    if not isinstance(profile, dict) or set(profile) != expected:
        raise WorkspaceError("Completa todos los campos del perfil.")
    result = dict(profile)
    for field, maximum in (("objective", 500), ("restrictions", 1000)):
        result[field] = _text(result[field], maximum)
    if type(result["horizon_months"]) is not int or not 1 <= result["horizon_months"] <= 600:
        raise WorkspaceError("El horizonte debe estar entre 1 y 600 meses.")
    for field, ceiling in (("liquidity_mxn", 1e12), ("loss_capacity_pct", 100), ("loss_tolerance_pct", 100)):
        value = result[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= ceiling:
            raise WorkspaceError("Hay un importe o porcentaje fuera de rango.")
    if result["experience"] not in {"BASICA", "INTERMEDIA", "AVANZADA"}:
        raise WorkspaceError("Indica la experiencia declarada.")
    try:
        reviewed = date.fromisoformat(result["reviewed_on"])
    except (TypeError, ValueError):
        raise WorkspaceError("Fecha de revisión inválida.") from None
    if reviewed > date.today():
        raise WorkspaceError("La fecha de revisión no puede ser futura.")
    # No score-to-allocation mapping: capacity and willingness are separate declarations.
    return result


def case_readiness(state: dict) -> dict:
    missing = []
    if state.get("profile") is None:
        missing.append("Perfil y objetivo")
    if not state.get("accounts"):
        missing.append("Cuenta o cartera identificada")
    for code, label in EVIDENCE.items():
        item = state.get("evidence", {}).get(code)
        if item is None or (item.get("expires_on") and item["expires_on"] < date.today().isoformat()):
            missing.append(label)
    valid_reviews = [r for r in state.get("reviews", []) if r["revision"] == state["revision"]]
    if len({r["actor"] for r in valid_reviews}) < 2:
        missing.append("Dos revisiones independientes de la versión vigente")
    if {review["kind"] for review in valid_reviews} != {"TECNICA", "FINANCIERA"}:
        missing.append("Revisión técnica y financiera de la versión vigente")
    if state.get("archived"):
        missing.append("Expediente archivado")
    return {
        "missing": missing,
        "declared_evidence": len(state.get("evidence", {})),
        "current_reviews": len(valid_reviews),
        "client_delivery_allowed": False,
        "status": "INTERNAL_REVIEW_PENDING" if missing else "INTERNAL_REVIEW_RECORDED",
        "notice": "Registrar evidencia y revisiones no habilita entrega a clientes.",
    }


class CaseStore:
    def __init__(self, path: Path, key: bytes):
        self.path = Path(path)
        self._key = key
        try:
            self.master = Fernet(key)
            self.mac_key = hmac.new(base64.urlsafe_b64decode(key), b"SIG audit v1", hashlib.sha256).digest()
        except (TypeError, ValueError):
            raise WorkspaceError("La clave de almacenamiento no es válida.") from None
        # Reject links/junctions; the configured location is an administrator decision.
        if any(
            part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction())
            for part in (self.path, *self.path.parents)
        ):
            raise WorkspaceError("El almacenamiento no admite enlaces o junctions.")

    @contextmanager
    def _connection(self):
        if not self.path.is_file():
            raise WorkspaceError("El registro aún no está inicializado.")
        try:
            connection = sqlite3.connect(self.path, timeout=10)
        except sqlite3.Error:
            raise WorkspaceError("No se pudo abrir el registro privado.") from None
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("BEGIN IMMEDIATE")
            self._verify(connection)
            yield connection
            connection.commit()
        except WorkspaceError:
            connection.rollback()
            raise
        except (sqlite3.Error, InvalidToken, ValueError, KeyError, TypeError):
            connection.rollback()
            raise WorkspaceError("No se pudo validar o actualizar el registro privado.") from None
        finally:
            connection.close()

    def initialize(self, principal: Principal):
        if principal.role != "ADMIN":
            raise WorkspaceError("Sólo administración puede inicializar el registro.")
        _ = principal.actor
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("xb"):
                pass
        except FileExistsError:
            raise WorkspaceError("El registro ya existe; no se sobrescribió.") from None
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE meta (value BLOB NOT NULL);
                CREATE TABLE cases (id TEXT PRIMARY KEY, wrapped_key BLOB NOT NULL,
                    token BLOB NOT NULL, revision INTEGER NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE artifacts (id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
                    token BLOB NOT NULL, FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE);
                CREATE TABLE audit (seq INTEGER PRIMARY KEY, case_id TEXT NOT NULL,
                    action TEXT NOT NULL, token BLOB NOT NULL, digest TEXT NOT NULL,
                    previous TEXT NOT NULL, mac TEXT NOT NULL);
            """)
            db.execute("INSERT INTO meta VALUES (?)", (self.master.encrypt(b"SIG_CASE_STORE_V1"),))

    def _verify(self, db):
        row = db.execute("SELECT value FROM meta").fetchone()
        if row is None or self.master.decrypt(row[0]) != b"SIG_CASE_STORE_V1":
            raise WorkspaceError("Clave o versión del registro incompatible.")
        previous = "0" * 64
        latest = {}
        for expected, row in enumerate(db.execute("SELECT * FROM audit ORDER BY seq"), 1):
            values = [
                row["seq"],
                row["case_id"],
                row["action"],
                row["token"].decode("ascii"),
                row["digest"],
                row["previous"],
            ]
            signature = hmac.new(self.mac_key, _json(values), hashlib.sha256).hexdigest()
            if (
                row["seq"] != expected
                or row["previous"] != previous
                or not hmac.compare_digest(signature, row["mac"])
            ):
                raise WorkspaceError("El historial no supera el control de integridad.")
            if _ID.fullmatch(row["case_id"]):
                latest[row["case_id"]] = row["digest"] if row["action"] != "PURGE" else None
            previous = row["mac"]
        rows = db.execute("SELECT * FROM cases").fetchall()
        if {r["id"] for r in rows} != {key for key, digest in latest.items() if digest is not None}:
            raise WorkspaceError("El inventario no coincide con el historial.")
        for row in rows:
            if (
                row["digest"] != hashlib.sha256(row["token"]).hexdigest()
                or latest[row["id"]] != row["digest"]
            ):
                raise WorkspaceError("La versión actual no coincide con el historial.")
            state = json.loads(self._cipher(row).decrypt(row["token"]))
            if state["id"] != row["id"] or state["revision"] != row["revision"]:
                raise WorkspaceError("La versión declarada no coincide con el contenido cifrado.")

    def _cipher(self, row):
        wrapped = json.loads(self.master.decrypt(row["wrapped_key"]))
        if wrapped["case_id"] != row["id"]:
            raise WorkspaceError("La clave no corresponde al expediente.")
        return Fernet(wrapped["key"].encode())

    def _state(self, db, case_id, principal, *, edit=False, allow_archived=False):
        row = db.execute("SELECT * FROM cases WHERE id=?", (_identifier(case_id),)).fetchone()
        if row is None:
            raise WorkspaceError("Expediente no disponible o acceso no autorizado.")
        cipher = self._cipher(row)
        state = json.loads(cipher.decrypt(row["token"]))
        if state["id"] != case_id or state["revision"] != row["revision"]:
            raise WorkspaceError("La versión del expediente no es válida.")
        if principal.role not in ROLES or (
            principal.role != "ADMIN" and principal.actor not in state["members"]
        ):
            raise WorkspaceError("Expediente no disponible o acceso no autorizado.")
        if edit and (
            principal.role not in {"ADMIN", "ANALYST"} or (state["archived"] and not allow_archived)
        ):
            raise WorkspaceError("Tu rol o el estado del expediente no permite editarlo.")
        return row, cipher, state

    def _event(self, db, case_id, action, cipher, detail, digest):
        last = db.execute("SELECT seq, mac FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last["seq"] + 1, last["mac"]) if last else (1, "0" * 64)
        token = cipher.encrypt(_json({**detail, "at": datetime.now(UTC).isoformat()}))
        values = [seq, case_id, action, token.decode("ascii"), digest, previous]
        mac = hmac.new(self.mac_key, _json(values), hashlib.sha256).hexdigest()
        db.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?)", (*values[:3], token, digest, previous, mac))

    def create(self, principal, alias, *, own_account=True):
        if principal.role not in {"ADMIN", "ANALYST"} or type(own_account) is not bool:
            raise WorkspaceError("No puedes crear este expediente.")
        case_id = uuid.uuid4().hex
        key = Fernet.generate_key()
        cipher = Fernet(key)
        state = {
            "id": case_id,
            "alias": _text(alias, 80),
            "revision": 1,
            "profile": None,
            "own_account": own_account,
            "accounts": [],
            "evidence": {},
            "reviews": [],
            "members": [principal.actor],
            "archived": False,
            "last_editor": principal.actor,
            "content_editor": principal.actor,
            "client_delivery_allowed": False,
        }
        token = cipher.encrypt(_json(state))
        digest = hashlib.sha256(token).hexdigest()
        wrapped = self.master.encrypt(_json({"case_id": case_id, "key": key.decode()}))
        with self._connection() as db:
            db.execute("INSERT INTO cases VALUES (?,?,?,?,?)", (case_id, wrapped, token, 1, digest))
            self._event(db, case_id, "CREATE", cipher, {"actor": principal.actor, "state": state}, digest)
        return state

    def list_cases(self, principal):
        _ = principal.actor
        result = []
        with self._connection() as db:
            for row in db.execute("SELECT * FROM cases"):
                state = json.loads(self._cipher(row).decrypt(row["token"]))
                if principal.role == "ADMIN" or principal.actor in state["members"]:
                    result.append(
                        {key: state[key] for key in ("id", "alias", "revision", "archived", "own_account")}
                    )
            self._event(
                db, "inventory", "LIST", self.master, {"actor": principal.actor, "count": len(result)}, ""
            )
        return result

    def read(self, principal, case_id):
        with self._connection() as db:
            row, cipher, state = self._state(db, case_id, principal)
            self._event(db, case_id, "READ", cipher, {"actor": principal.actor}, row["digest"])
            return state

    def update(self, principal, case_id, expected_revision, section, value):
        with self._connection() as db:
            row, cipher, state = self._state(
                db, case_id, principal, edit=True, allow_archived=section == "archived"
            )
            if type(expected_revision) is not int or expected_revision != state["revision"]:
                raise WorkspaceError("Otra persona cambió el expediente; vuelve a cargarlo.")
            if section == "profile":
                value = validate_profile(value)
            elif section == "account":
                if not isinstance(value, dict) or set(value) != {
                    "broker",
                    "product",
                    "portfolio",
                    "currency",
                }:
                    raise WorkspaceError("Completa intermediario, producto, cartera y moneda.")
                value = {key: _text(item, 80) for key, item in value.items()}
                if value["currency"] not in {"MXN", "USD"} or value["product"] not in PRODUCTS:
                    raise WorkspaceError("Producto o moneda no permitido.")
                if any(
                    all(account[field] == value[field] for field in value) for account in state["accounts"]
                ):
                    raise WorkspaceError("Esa cartera ya está registrada.")
                state["accounts"].append({"id": uuid.uuid4().hex, **value})
            elif section == "evidence":
                if not isinstance(value, dict) or set(value) != {
                    "control",
                    "sha256",
                    "reference",
                    "reviewed_on",
                    "expires_on",
                }:
                    raise WorkspaceError("La evidencia no coincide con el formato requerido.")
                value = dict(value)
                if value["control"] not in EVIDENCE or not _SHA.fullmatch(value.get("sha256", "")):
                    raise WorkspaceError("Control o huella de evidencia inválido.")
                value["reference"] = _text(value["reference"], 300)
                reviewed = date.fromisoformat(value["reviewed_on"])
                expiry = date.fromisoformat(value["expires_on"]) if value["expires_on"] else None
                if reviewed > date.today() or (expiry is not None and expiry < reviewed):
                    raise WorkspaceError("Fechas de evidencia incompatibles.")
                value = {**value, "recorded_by": principal.actor, "status": "DECLARADA_REQUIERE_COTEJO"}
                state["evidence"][value["control"]] = value
            elif section == "archived":
                if principal.role != "ADMIN" or type(value) is not bool:
                    raise WorkspaceError("Sólo administración puede archivar o recuperar.")
            else:
                raise WorkspaceError("Sección de expediente no editable.")
            if section in {"profile", "archived"}:
                state[section] = value
            state["revision"] += 1
            if section != "archived":
                state["content_editor"] = principal.actor
            state["last_editor"] = principal.actor
            token = cipher.encrypt(_json(state))
            digest = hashlib.sha256(token).hexdigest()
            db.execute(
                "UPDATE cases SET token=?,revision=?,digest=? WHERE id=?",
                (token, state["revision"], digest, case_id),
            )
            self._event(
                db,
                case_id,
                "UPDATE",
                cipher,
                {"actor": principal.actor, "section": section, "state": state},
                digest,
            )
            return state

    def grant(self, principal, case_id, member: Principal):
        if principal.role != "ADMIN":
            raise WorkspaceError("Sólo administración puede asignar integrantes.")
        with self._connection() as db:
            _, cipher, state = self._state(db, case_id, principal)
            if member.actor not in state["members"]:
                state["members"].append(member.actor)
            state["revision"] += 1
            state["last_editor"] = principal.actor
            token = cipher.encrypt(_json(state))
            digest = hashlib.sha256(token).hexdigest()
            db.execute(
                "UPDATE cases SET token=?,revision=?,digest=? WHERE id=?",
                (token, state["revision"], digest, case_id),
            )
            self._event(db, case_id, "GRANT", cipher, {"actor": principal.actor, "state": state}, digest)

    def review(self, principal, case_id, expected_revision, kind, note):
        if principal.role not in {"ADMIN", "REVIEWER"} or kind not in {"TECNICA", "FINANCIERA"}:
            raise WorkspaceError("Tu rol no permite registrar esta revisión.")
        with self._connection() as db:
            row, cipher, state = self._state(db, case_id, principal)
            if (
                state["archived"]
                or expected_revision != state["revision"]
                or principal.actor == state.get("content_editor", state["last_editor"])
            ):
                raise WorkspaceError(
                    "La revisión exige versión vigente y una persona distinta de quien editó."
                )
            if any(
                r["revision"] == expected_revision and r["actor"] == principal.actor for r in state["reviews"]
            ):
                raise WorkspaceError("Esta persona ya revisó la versión vigente.")
            review = {
                "revision": expected_revision,
                "actor": principal.actor,
                "kind": kind,
                "note": _text(note, 500),
                "at": datetime.now(UTC).isoformat(),
            }
            state["reviews"].append(review)
            token = cipher.encrypt(_json(state))
            digest = hashlib.sha256(token).hexdigest()
            db.execute("UPDATE cases SET token=?,digest=? WHERE id=?", (token, digest, case_id))
            self._event(db, case_id, "REVIEW", cipher, {"actor": principal.actor, "state": state}, digest)
            return state

    def revoke(self, principal, case_id, member: Principal):
        if principal.role != "ADMIN" or member.role == "ADMIN":
            raise WorkspaceError(
                "Sólo administración puede revocar integrantes sin rol global de administrador."
            )
        with self._connection() as db:
            _, cipher, state = self._state(db, case_id, principal)
            state["members"] = [actor for actor in state["members"] if actor != member.actor]
            state["revision"] += 1
            state["last_editor"] = principal.actor
            token = cipher.encrypt(_json(state))
            digest = hashlib.sha256(token).hexdigest()
            db.execute(
                "UPDATE cases SET token=?,revision=?,digest=? WHERE id=?",
                (token, state["revision"], digest, case_id),
            )
            self._event(db, case_id, "REVOKE", cipher, {"actor": principal.actor, "state": state}, digest)

    def attach(self, principal, case_id, expected_revision, name, contents, *, account_id=None):
        if not isinstance(contents, bytes) or not 0 < len(contents) <= 5_000_000:
            raise WorkspaceError("El archivo debe tener de 1 byte a 5 MB.")
        name = _text(name, 100)
        if "/" in name or "\\" in name:
            raise WorkspaceError("El nombre del archivo no puede incluir una ruta.")
        with self._connection() as db:
            row, cipher, state = self._state(db, case_id, principal, edit=True)
            if account_id is not None and account_id not in {item["id"] for item in state["accounts"]}:
                raise WorkspaceError("La cuenta seleccionada no pertenece a este expediente.")
            if expected_revision != state["revision"]:
                raise WorkspaceError("La versión cambió; vuelve a cargarla antes de adjuntar.")
            artifact_id = uuid.uuid4().hex
            digest = hashlib.sha256(contents).hexdigest()
            token = cipher.encrypt(
                _json(
                    {
                        "case_id": case_id,
                        "id": artifact_id,
                        "name": name,
                        "account_id": account_id,
                        "sha256": digest,
                        "revision": expected_revision,
                        "bytes": base64.b64encode(contents).decode(),
                    }
                )
            )
            db.execute("INSERT INTO artifacts VALUES (?,?,?)", (artifact_id, case_id, token))
            # An attachment changes the evidence set and invalidates reviews.
            state["revision"] += 1
            state["content_editor"] = principal.actor
            state["last_editor"] = principal.actor
            state.setdefault("artifacts", []).append(
                {
                    "id": artifact_id,
                    "name": name,
                    "sha256": digest,
                    "size": len(contents),
                    "account_id": account_id,
                    "added_in_revision": state["revision"],
                }
            )
            state_token = cipher.encrypt(_json(state))
            state_digest = hashlib.sha256(state_token).hexdigest()
            db.execute(
                "UPDATE cases SET token=?,revision=?,digest=? WHERE id=?",
                (state_token, state["revision"], state_digest, case_id),
            )
            self._event(
                db, case_id, "ATTACH", cipher, {"actor": principal.actor, "state": state}, state_digest
            )
            return artifact_id

    def artifact(self, principal, case_id, artifact_id):
        with self._connection() as db:
            row, cipher, state = self._state(db, case_id, principal)
            record = db.execute(
                "SELECT token FROM artifacts WHERE id=? AND case_id=?", (_identifier(artifact_id), case_id)
            ).fetchone()
            if record is None:
                raise WorkspaceError("Archivo no disponible.")
            value = json.loads(cipher.decrypt(record[0]))
            contents = base64.b64decode(value.pop("bytes"), validate=True)
            expected = next((item for item in state.get("artifacts", []) if item["id"] == artifact_id), None)
            if (
                expected is None
                or value["id"] != artifact_id
                or value["case_id"] != case_id
                or value["sha256"] != expected["sha256"]
                or hashlib.sha256(contents).hexdigest() != expected["sha256"]
            ):
                raise WorkspaceError("El archivo no supera el control de integridad.")
            self._event(
                db,
                case_id,
                "DOWNLOAD",
                cipher,
                {"actor": principal.actor, "artifact": artifact_id},
                row["digest"],
            )
            return value, contents

    def history(self, principal, case_id):
        with self._connection() as db:
            row, cipher, _ = self._state(db, case_id, principal)
            events = [
                {
                    "sequence": item["seq"],
                    "action": item["action"],
                    **json.loads(cipher.decrypt(item["token"])),
                }
                for item in db.execute("SELECT * FROM audit WHERE case_id=? ORDER BY seq", (case_id,))
            ]
            self._event(db, case_id, "HISTORY", cipher, {"actor": principal.actor}, row["digest"])
            return events

    def backup(self, principal, destination: Path):
        if principal.role != "ADMIN":
            raise WorkspaceError("Sólo administración puede generar respaldos.")
        _ = principal.actor
        destination = Path(destination)
        if (
            destination.exists()
            or not destination.parent.is_dir()
            or destination.resolve() == self.path.resolve()
        ):
            raise WorkspaceError("El respaldo requiere un destino nuevo en una carpeta existente.")
        if any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in (destination, *destination.parents)
        ):
            raise WorkspaceError("El destino no admite enlaces.")
        # Validate and audit before using SQLite's consistent backup API (no WAL file copying).
        with self._connection() as db:
            self._event(db, "inventory", "BACKUP", self.master, {"actor": principal.actor}, "")
        with destination.open("xb"):
            pass
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return self.restore_check(principal, destination)

    def restore_check(self, principal, source: Path):
        if principal.role != "ADMIN":
            raise WorkspaceError("Sólo administración puede comprobar una restauración.")
        _ = principal.actor
        other = CaseStore(source, self._key)
        with other._connection() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise WorkspaceError("El respaldo no supera el control estructural.")
            expected_ids = set()
            for row in db.execute("SELECT * FROM cases").fetchall():
                state = json.loads(other._cipher(row).decrypt(row["token"]))
                for item in state.get("artifacts", []):
                    other._check_artifact(db, row, item)
                    expected_ids.add(item["id"])
            if expected_ids != {row[0] for row in db.execute("SELECT id FROM artifacts")}:
                raise WorkspaceError("El inventario de archivos del respaldo no coincide.")
            return {
                "cases": db.execute("SELECT count(*) FROM cases").fetchone()[0],
                "events": db.execute("SELECT count(*) FROM audit").fetchone()[0],
                "integrity": "VERIFIED",
                "client_delivery_allowed": False,
            }

    def _check_artifact(self, db, case_row, item):
        record = db.execute(
            "SELECT token FROM artifacts WHERE id=? AND case_id=?", (item["id"], case_row["id"])
        ).fetchone()
        if record is None:
            raise WorkspaceError("Falta un archivo declarado en el expediente.")
        value = json.loads(self._cipher(case_row).decrypt(record[0]))
        contents = base64.b64decode(value["bytes"], validate=True)
        if (
            value["case_id"] != case_row["id"]
            or value["id"] != item["id"]
            or value["name"] != item["name"]
            or value["sha256"] != item["sha256"]
            or hashlib.sha256(contents).hexdigest() != item["sha256"]
            or len(contents) != item["size"]
        ):
            raise WorkspaceError("Un archivo del respaldo no supera el control de integridad.")

    def purge(self, principal, case_id, confirmation):
        if principal.role != "ADMIN":
            raise WorkspaceError("Sólo administración puede eliminar un expediente.")
        with self._connection() as db:
            _, _, state = self._state(db, case_id, principal)
            if not state["archived"] or confirmation != state["alias"]:
                raise WorkspaceError("Archiva el expediente y confirma su alias exacto antes de eliminar.")
            db.execute("DELETE FROM artifacts WHERE case_id=?", (case_id,))
            db.execute("DELETE FROM cases WHERE id=?", (case_id,))
            # Per-case decryption key is destroyed in this live database. Old backups are separate.
            self._event(db, case_id, "PURGE", self.master, {"actor": principal.actor}, "")

    def restore_new(self, principal, source: Path, destination: Path):
        """Restore a verified backup to a new path; never roll back a live store."""
        self.restore_check(principal, source)
        destination = Path(destination)
        if destination.exists() or not destination.parent.is_dir():
            raise WorkspaceError("La recuperación exige un destino nuevo y una carpeta existente.")
        recovered = CaseStore(destination, self._key)
        with destination.open("xb"):
            pass
        with sqlite3.connect(source) as origin, sqlite3.connect(destination) as target:
            origin.backup(target)
        result = recovered.restore_check(principal, destination)
        with recovered._connection() as db:
            recovered._event(db, "inventory", "RESTORE", recovered.master, {"actor": principal.actor}, "")
        return result
