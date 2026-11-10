"""Restore private operation inputs inside the current session and account only."""

from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import streamlit as st

from operations_review import build_operations_review, read_operations_review, review_code_fingerprints
from portfolio_core import PortfolioError

ROLE_LABELS = {
    "ledger": "Libro de movimientos", "controls": "Controles de cierre", "quotes": "Cotizaciones de cierre",
    "fx": "FX del cierre", "repo_values": "Valuaciones de reportos", "nav": "Valuaciones históricas",
    "flow_fx": "FX de los flujos",
}


def _context_key(name):
    return name + "_" + st.session_state.get("_ops_context_key", "temporary")


def _recovery():
    return st.session_state.get(_context_key("_ops_review"), {})


def review_key(name):
    token = _recovery().get("token")
    return _context_key(name) + ("_" + token if token else "")


def review_defaults():
    return _recovery().get("settings", {})


def _scope(context):
    if context is None:
        return {"case_id": None, "account_id": None}
    _store, _principal, state, account = context
    return {"case_id": state["id"] if state and account else None, "account_id": account}


def open_review(context):
    with st.expander("Abrir paquete de movimientos"):
        package = st.file_uploader(
            "Paquete de movimientos ZIP", type=["zip"], key=_context_key("ops_review_zip")
        )
        if package and st.button("Retomar movimientos", key=_context_key("ops_review_open")):
            try:
                manifest, files = read_operations_review(package.getvalue(), **_scope(context))
            except PortfolioError as exc:
                st.error(str(exc))
            else:
                st.session_state[_context_key("_ops_review")] = {
                    "token": uuid4().hex, "files": files,
                    "settings": {"cutoff": manifest["cutoff"], "base": manifest["base"]},
                    "code_changed": manifest["code_sha256"] != review_code_fingerprints(),
                }
                st.session_state.pop(_context_key("_ops_last_book"), None)
                st.rerun()
    if _recovery():
        st.info("Revisión recuperada. Se recalculan las vistas; confirma otra vez las fuentes y los flujos.")
        if _recovery().get("code_changed"):
            st.caption("El motor cambió desde la descarga; la revisión usa la versión actual.")


def review_upload(label, role, *, key):
    uploaded = st.file_uploader(label, type=["csv"], key=review_key(key))
    files = _recovery().get("files", {})
    if uploaded is not None:
        # A replacement takes ownership of this role; removing it must not resurrect the old file.
        files.pop(role, None)
        return uploaded
    if role in files:
        st.caption("Recuperado: " + ROLE_LABELS[role] + ".")
        if st.button("Quitar archivo recuperado · " + ROLE_LABELS[role], key=review_key("remove_" + role)):
            files.pop(role)
            st.rerun()
        return BytesIO(files[role])
    return None


def reset_confirmation(name, parts):
    """Changing the reviewed inputs invalidates consent before the checkbox is constructed."""
    digest = sha256()
    for part in parts:
        raw = part if isinstance(part, bytes) else str(part).encode()
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    signature_key = review_key("signature_" + name)
    signature = digest.hexdigest()
    if st.session_state.get(signature_key) != signature:
        st.session_state[review_key(name)] = False
        st.session_state[signature_key] = signature


def download_review(context, files, *, cutoff, base):
    present = {role: source.getvalue() for role, source in files.items() if source is not None}
    _manifest, contents = build_operations_review(
        present, cutoff=cutoff.isoformat(), base=base, **_scope(context)
    )
    with st.expander("Guardar revisión de movimientos"):
        st.write("Incluye: " + ", ".join(ROLE_LABELS[role] for role in present) + ".")
        st.caption(
            "Conserva los CSV, el corte y la moneda para retomarlos. No conserva confirmaciones ni "
            "resultados aprobados. El ZIP contiene datos privados sin cifrar; "
            "guárdalo como el documento original."
        )
        st.download_button(
            "Descargar paquete de movimientos", contents, f"movimientos_{cutoff}.zip", "application/zip",
            key=review_key("ops_review_download"), on_click="ignore",
        )
