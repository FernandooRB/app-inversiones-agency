"""Restore private operation inputs inside the current session and account only."""

from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_proposal import portable_proposal
from operations_review import build_operations_review, read_operations_review, review_code_fingerprints
from operations_status import status_text
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
ROLE_WIDGETS = (
    "ops_ledger",
    "ops_closing_controls",
    "ops_raw",
    "ops_book_fx",
    "ops_repo_values",
    "ops_nav",
    "ops_flow_fx",
)


def _context_key(name):
    return name + "_" + st.session_state.get("_ops_context_key", "temporary")


def _recovery():
    return st.session_state.get(_context_key("_ops_review"), {})


def review_key(name):
    token = _recovery().get("token")
    return _context_key(name) + ("_" + token if token else "")


def proposal_key(name):
    # A package replacement starts new input widgets. Completing a NAV/FX form
    # only renews review consent; it must preserve edited proposal assumptions.
    token = st.session_state.get(_context_key("_ops_proposal_form_token"), "initial")
    return _context_key(name) + "_" + token


def review_defaults():
    return _recovery().get("settings", {})


def movement_draft():
    return _recovery().get("draft")


def recovered_proposal():
    return _recovery().get("proposal")


def current_proposal(context, files, *, cutoff, base):
    proposal = st.session_state.get("_execution_proposal")
    binding = (context[2]["id"] if context[2] else None, context[3])
    if not proposal or proposal.get("context") != binding:
        return None
    if not st.session_state.get(proposal_key("orders_confirmation")) or proposal.get(
        "signature"
    ) != st.session_state.get(_context_key("orders_signature")):
        return None
    inputs = proposal["inputs"]
    if inputs["date"] != str(cutoff) or inputs["currency"] != base:
        return None
    origin = inputs.get("book_origin")
    if origin and ("ledger" not in files or origin["ledger_sha256"] != sha256(files["ledger"]).hexdigest()):
        return None
    return portable_proposal(proposal)


def attached_originals():
    return st.session_state.get(_context_key("_gbm_attached"), [])


def _current_files():
    files = dict(_recovery().get("files", {}))
    for widget, file_role in zip(ROLE_WIDGETS, ROLE_LABELS, strict=True):
        uploaded = st.session_state.get(review_key(widget))
        if uploaded is not None:
            files[file_role] = uploaded.getvalue()
    return files


def current_review_files():
    """Current account inputs, including uploads that replaced recovered files."""
    return _current_files()


def save_review_input(role, raw):
    current = dict(_recovery())
    files = _current_files()
    files[role] = raw
    current.update(token=uuid4().hex, files=files)
    st.session_state[_context_key("_ops_review")] = current
    st.session_state.pop(_context_key("_ops_last_book"), None)


def set_movement_draft(draft):
    current = dict(_recovery())
    # Preserve attached originals inside this session, never in ZIP; reattachment is required after reopen.
    attached = st.session_state.get(review_key("gbm_documents"))
    # Rotating tokens retires file widgets, editor confirmations and stale derived results together.
    files = _current_files()
    if current.get("draft") != draft:
        files.pop("ledger", None)
        files.pop("controls", None)
        current.pop("settings", None)
    current.update(token=uuid4().hex, draft=draft, files=files)
    st.session_state[_context_key("_ops_review")] = current
    if attached:
        st.session_state[_context_key("_gbm_attached")] = attached
    for name in ("_ops_last_book", "_ops_book_signature", "_ops_status"):
        st.session_state.pop(_context_key(name), None)


def use_movement_draft(ledger, controls, *, cutoff):
    current = dict(_recovery())
    current.update(
        token=uuid4().hex,
        files={**current.get("files", {}), "ledger": ledger, "controls": controls},
        settings={"cutoff": cutoff, "base": "MXN"},
    )
    st.session_state[_context_key("_ops_review")] = current
    st.session_state.pop(_context_key("_ops_last_book"), None)


def _open_key(name):
    token = st.session_state.get(_context_key("_ops_open_token"))
    return _context_key(name) + ("_" + token if token else "")


def clear_review():
    """Discard only the current movement inputs; never clear other tools or accounts."""
    names = (
        *ROLE_WIDGETS,
        "ops_cutoff",
        "ops_base",
        "raw_confirmation",
        "flows_confirmation",
        "signature_raw_confirmation",
        "signature_flows_confirmation",
        "ops_review_save_panel",
        "ops_review_download",
        *("remove_" + role for role in ROLE_LABELS),
    )
    keys = {_context_key(name) for name in names} | {review_key(name) for name in names}
    keys.update(_open_key(name) for name in ("ops_review_open_panel", "ops_review_zip", "ops_review_open"))
    keys.add("_analysis_memo_" + _context_key("operations_calculations"))
    keys.add("_analysis_memo_" + _context_key("bridge_book"))
    keys.add(_context_key("proposal_pdf"))
    keys.update(
        _context_key(name)
        for name in (
            "_ops_last_book",
            "_ops_book_signature",
            "_ops_status",
            "_ops_focus_step",
            "monitor_confirmation",
            "_gbm_attached",
            "_ops_proposal_bridge",
        )
    )
    for key in keys:
        st.session_state.pop(key, None)
    st.session_state[_context_key("_ops_review")] = {"token": uuid4().hex, "files": {}, "settings": {}}
    st.session_state[_context_key("_ops_open_token")] = uuid4().hex
    st.session_state[_context_key("_ops_cleared_notice")] = True
    st.session_state["operations_tabs"] = "Movimientos"


def new_review():
    present = _has_current_inputs() or st.session_state.get(_open_key("ops_review_zip")) is not None
    if present:
        st.session_state.pop(_context_key("_ops_cleared_notice"), None)
        with st.expander("Nueva revisión de movimientos"):
            st.caption(
                "Vacía los CSV de Movimientos, el ZIP seleccionado, corte, moneda y confirmaciones "
                "de esta revisión. Descarga tu ZIP antes si quieres retomarla. "
                "Tus descargas, expedientes y archivos de las otras pestañas se conservan."
            )
            st.button(
                "Vaciar movimientos y empezar", key=_context_key("ops_review_clear"), on_click=clear_review
            )
    elif st.session_state.get(_context_key("_ops_cleared_notice")):
        st.success("Revisión de movimientos vacía. Carga un libro o abre un ZIP para empezar.")


def _scope(context):
    if context is None:
        return {"case_id": None, "account_id": None}
    _store, _principal, state, account = context
    return {"case_id": state["id"] if state and account else None, "account_id": account}


def _has_current_inputs():
    return (
        bool(_recovery().get("files"))
        or bool(movement_draft())
        or bool(recovered_proposal())
        or any(st.session_state.get(review_key(name)) is not None for name in ROLE_WIDGETS)
    )


def open_review(context):
    with st.expander("Abrir paquete de movimientos", key=_open_key("ops_review_open_panel")):
        package = st.file_uploader(
            "Paquete de movimientos ZIP", type=["zip"], key=_open_key("ops_review_zip")
        )
        if package:
            try:
                manifest, files = read_operations_review(package.getvalue(), **_scope(context))
            except PortfolioError as exc:
                st.error(str(exc))
            else:
                st.write("**Vista previa del paquete**")
                st.text(
                    f"Corte: {manifest['cutoff']} · Moneda: {manifest['base']} · {len(files)} archivos CSV"
                )
                if files:
                    st.caption("Incluye: " + ", ".join(ROLE_LABELS[role] for role in files) + ".")
                if manifest.get("draft_data"):
                    st.caption(
                        "Incluye borrador GBM y procedencia. "
                        "Requiere cotejo de los originales y nuevas confirmaciones."
                    )
                if manifest.get("proposal_data"):
                    st.caption(
                        "Incluye propuesta, tarifas, fuentes y límites. "
                        "El resultado guardado es histórico; requiere revisión y nuevo cálculo."
                    )
                st.caption(
                    "Cargar el ZIP no cambia la revisión. Las vistas se recalculan al abrirlo; "
                    "el paquete no confirma fuentes ni flujos."
                )
                replacing = _has_current_inputs()
                if replacing:
                    st.warning(
                        "Se reemplazarán los CSV, el corte, la moneda y la propuesta de esta revisión. "
                        "Conserva una copia de lo que necesites antes de continuar."
                    )
                label = "Reemplazar revisión con este paquete" if replacing else "Retomar movimientos"
                if st.button(label, key=_open_key("ops_review_open")):
                    st.session_state[_context_key("_ops_proposal_form_token")] = uuid4().hex
                    st.session_state[_context_key("_ops_review")] = {
                        "token": uuid4().hex,
                        "files": files,
                        "settings": {"cutoff": manifest["cutoff"], "base": manifest["base"]},
                        "code_changed": manifest["code_sha256"]
                        != review_code_fingerprints(schema=manifest["schema"]),
                        "draft": manifest.get("draft_data"),
                        "proposal": manifest.get("proposal_data"),
                    }
                    st.session_state.pop(_context_key("_ops_last_book"), None)
                    st.session_state.pop(_context_key("_gbm_attached"), None)
                    st.rerun()
    if _recovery().get("settings"):
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


def download_review(context, files, *, cutoff, base, suffix="", proposal=None):
    panel_key = review_key("ops_review_save_panel" + suffix)
    with st.expander(
        "Guardar propuesta y revisión"
        if suffix == "_proposal"
        else "Guardar borrador GBM"
        if suffix
        else "Guardar revisión de movimientos",
        key=panel_key,
        on_change="rerun",
    ):
        if not st.session_state.get(panel_key, False):
            return
        present = current_review_files()
        for role, source in files.items():
            if source is None:
                present.pop(role, None)
            else:
                present[role] = source.getvalue()
        draft = movement_draft()
        proposal = proposal or current_proposal(context, present, cutoff=cutoff, base=base)
        status = st.session_state.get(_context_key("_ops_status"))
        summary = status_text(status.snapshot("Revisión de movimientos")) if status and draft else None
        args = {
            "cutoff": cutoff.isoformat(),
            "base": base,
            "draft": draft,
            "summary": summary,
            "proposal": proposal,
            **_scope(context),
        }
        _manifest, contents = session_compute(
            st.session_state,
            "operations_zip",
            analysis_key(
                present, args, review_code_fingerprints(schema=3 if proposal else 2 if draft else 1)
            ),
            lambda: build_operations_review(present, **args),
            max_entries=1,
        )
        if draft and "ledger" not in present:
            st.info(
                "Este ZIP guarda el borrador GBM. Para preparar el libro, revisa las incidencias, "
                "coteja los datos con el PDF y pulsa Usar movimientos revisados."
            )
            st.caption(
                "Los archivos internos permiten retomar el borrador; "
                "el cálculo de rendimiento sigue pendiente."
            )
        elif "ledger" in present:
            st.write("**Este ZIP incluye el libro de movimientos y los datos disponibles de esta revisión.**")
        st.caption("El PDF de rendimiento se prepara por separado en Archivos y resumen descargable.")
        st.caption(
            "Descarga este ZIP y comprueba que quedó guardado en tu dispositivo antes de cerrar. "
            "Para continuar, abre Abrir paquete de movimientos, carga el ZIP y revisa la vista previa. "
            "Al retomarlo se recalculan las vistas y se renuevan las confirmaciones. "
            "El ZIP contiene datos privados sin cifrar; guárdalo como el documento original."
        )
        st.download_button(
            "Descargar paquete de movimientos",
            contents,
            f"movimientos_{cutoff}.zip",
            "application/zip",
            key=review_key("ops_review_download" + suffix),
            on_click="ignore",
        )
        labels = [ROLE_LABELS[role] for role in ROLE_LABELS if role in present]
        if draft:
            labels.append("Borrador GBM con sus correcciones")
        if summary:
            labels.append("Resumen TXT")
        if proposal:
            labels.append("Propuesta completa con fuentes, tarifas, límites y resultado histórico")
        st.write("Incluye: " + ", ".join(labels) + ".")
