"""Content inventory derived from existing bounded readers, never financial approval."""

import json
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from operations_consolidation_bundle import read_bundle
from operations_review import MAX_PACKAGE_BYTES, read_operations_review, review_code_fingerprints
from portfolio_core import PortfolioError

ROLE_LABELS = {
    "ledger": "Libro de movimientos",
    "controls": "Controles de cierre",
    "quotes": "Cotizaciones de cierre",
    "fx": "FX del cierre",
    "repo_values": "Valuaciones de reportos",
    "nav": "Valuaciones históricas",
    "flow_fx": "FX de los flujos",
}


def movements_inventory(manifest, files):
    """Only accepts the manifest/files returned by read_operations_review."""
    rows = [
        {"Contenido": label, "Guardado": "Incluido" if role in files else "No incluido"}
        for role, label in ROLE_LABELS.items()
    ]
    extras = (
        ("draft_data", "Borrador GBM y correcciones"),
        ("proposal_data", "Propuesta de cartera"),
        ("policy_data", "Política propuesta"),
        ("csv_import_data", "CSV original y correspondencia"),
        ("summary", "Resumen TXT"),
    )
    rows.extend(
        {"Contenido": label, "Guardado": "Incluido" if manifest.get(field) else "No incluido"}
        for field, label in extras
    )
    return {
        "kind": manifest["kind"],
        "schema": manifest["schema"],
        "cutoff": manifest["cutoff"],
        "base": manifest["base"],
        "stage": "Libro incluido"
        if "ledger" in files
        else "Borrador sin libro"
        if manifest.get("draft_data")
        else "Borrador CSV sin libro"
        if manifest.get("csv_import_data")
        else "Propuesta sin libro",
        "contents": rows,
        "csv_count": len(files),
        "account_count": 1,
        "originals_included": False,
        "originals_required": bool(manifest.get("draft_data")),
        "review_state": "PENDING_REVIEW",
        "code_changed": manifest["code_sha256"] != review_code_fingerprints(schema=manifest["schema"]),
    }


def inspect_package(raw, *, case_id=None, account_id=None, allowed_accounts=None):
    """Identify data-only package, then defer every integrity/scope check to its reader."""
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PACKAGE_BYTES:
            raise ValueError
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            if len(names) > 14 or len(names) != len(set(names)):
                raise ValueError
            if "review.json" in names and "consolidation.json" not in names:
                manifest, files = read_operations_review(raw, case_id=case_id, account_id=account_id)
                result = movements_inventory(manifest, files)
            elif "consolidation.json" in names and "review.json" not in names:
                if account_id is not None:
                    raise ValueError
                proposal = read_bundle(raw, case_id=case_id, allowed_accounts=allowed_accounts)
                # The reader has already bounded and validated this manifest and its cutoff.
                manifest = json.loads(archive.read("consolidation.json"))
                result = {
                    "kind": manifest["kind"],
                    "schema": 1,
                    "cutoff": manifest["cutoff"],
                    "base": proposal["base"],
                    "stage": "Consolidación de cortes",
                    "account_count": len(proposal["entries"]),
                    "csv_count": bool(proposal["fx"]) + bool(proposal["links"]),
                    "originals_included": False,
                    "originals_required": False,
                    "review_state": "PENDING_REVIEW",
                }
            else:
                raise ValueError
        return {**result, "sha256": sha256(raw).hexdigest(), "bytes": len(raw)}
    except (BadZipFile, ValueError, TypeError, KeyError, RecursionError, NotImplementedError, PortfolioError):
        raise PortfolioError(
            "La copia requiere un ZIP de movimientos o consolidación válido y su contexto explícito."
        ) from None


def local_copy_guide():
    return """SIG · Copias personales y recuperación

En la web gratuita guarda el ZIP en tu dispositivo antes de cerrar.
PDF y TXT sirven para leer resultados; no permiten reabrir el trabajo.
El ZIP de movimientos se abre en Movimientos > Abrir paquete de movimientos.
El ZIP de consolidación se abre en Patrimonio > Consolidar libros revisados.
No necesitas extraer los archivos internos.

Los documentos reales GBM se usan sólo en la app local. Sus PDF/XML no están en
el ZIP: adjúntalos de nuevo si debes cotejar la evidencia. Al reabrir, revisa las
fuentes y confirma otra vez; los datos incompletos permanecen pendientes.

Copia cifrada opcional en tu computadora, desde la carpeta del proyecto:
python -m scripts.local_review keygen --destination clave.sigkey
python -m scripts.local_review save --source r.zip --key-file clave.sigkey --destination copia.siglocal
python -m scripts.local_review verify --source copia.siglocal --key-file clave.sigkey
python -m scripts.local_review restore --source copia.siglocal --key-file clave.sigkey --destination r2.zip

Sustituye r.zip por el ZIP descargado y r2.zip por un nombre nuevo. Puedes indicar
una ubicación privada para clave.sigkey; usa esa misma ruta en todos los comandos.
Los archivos .sigkey están excluidos de Git. Nunca se sobrescriben archivos.
No subas la clave ni la copia cifrada a la app. Conserva una copia de la clave en
otro lugar protegido: perderla impide recuperar el archivo; quien la tenga puede
leerlo. El ZIP recuperado vuelve a estar sin cifrar. Las rutas de cuenta ligada
requieren además --case-id y --account-id; los grupos ligados usan --allowed-account.

Retención manual: comprueba la recuperación antes de retirar copias antiguas.
La herramienta permite cambiar de clave a una copia nueva y eliminar una copia
individual con su SHA256 exacto. No elimina otras copias ni acredita borrado físico.
Guía completa: docs/local_review_recovery.md. Alojamiento USD 0.
""".encode()
