"""Restore private operation inputs inside the current session and account only."""

from hashlib import sha256
from io import BytesIO
from uuid import uuid4

import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_proposal import portable_proposal
from operations_recovery import ROLE_LABELS, local_copy_guide, movements_inventory
from operations_review import build_operations_review, read_operations_review, review_code_fingerprints
from operations_status import status_text
from portfolio_core import PortfolioError

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


def csv_import_draft():
    return _recovery().get("csv_import")


def set_csv_import(origin, *, ledger=None, cutoff, base):
    """Explicit replacement: no controls/valuations from the previous book survive."""
    from copy import deepcopy

    from csv_mapping import pack_import, preview

    origin = deepcopy(origin)
    if ledger is not None:
        checked = preview(origin["source"], origin["mapping"], origin["decisions"])
        if not checked["ready"] or ledger != checked["ledger"]:
            raise PortfolioError("El CSV aún tiene pendientes; no se puede utilizar como libro.")
    origin["applied_ledger_sha256"] = sha256(ledger).hexdigest() if ledger is not None else None
    pack_import(origin)
    st.session_state[_context_key("_ops_review")] = {
        "token": uuid4().hex,
        "files": {"ledger": ledger} if ledger is not None else {},
        "csv_import": origin,
        "settings": {"cutoff": str(cutoff), "base": base},
    }
    st.session_state[_context_key("_ops_proposal_form_token")] = uuid4().hex
    for name in (
        "_ops_last_book",
        "_ops_book_signature",
        "_ops_status",
        "_gbm_attached",
        "_ops_proposal_bridge",
    ):
        st.session_state.pop(_context_key(name), None)


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
    working = st.session_state.get(_context_key("_csv_working"))
    preserve_mapping = working is not None and working.get("bound_review_token") == current.get("token")
    current.update(token=uuid4().hex, files=files)
    if preserve_mapping:
        working["bound_review_token"] = current["token"]
    st.session_state[_context_key("_ops_review")] = current
    st.session_state.pop(_context_key("_ops_last_book"), None)


def set_movement_draft(draft):
    current = dict(_recovery())
    # Preserve attached originals inside this session, never in ZIP; reattachment is required after reopen.
    attached = st.session_state.get(review_key("gbm_documents"))
    # Rotating tokens retires file widgets, editor confirmations and stale derived results together.
    files = _current_files()
    if current.pop("csv_import", None) is not None:
        files = {}
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
        "cuts_panel",
        "cut_previous",
        "cuts_confirmed",
        "cuts_consent_signature",
        "cut_comparison_result",
        "cut_download",
        "cut_csv",
        *(
            "policy_" + name
            for name in (
                "panel",
                "strategy",
                "copy",
                "source",
                "date",
                "basis",
                "targets",
                "tolerance",
                "max_weight",
                "min_cash",
                "confirmed",
                "reference",
                "csv",
                "json",
            )
        ),
        "signature_policy_confirmed",
        *("remove_" + role for role in ROLE_LABELS),
    )
    keys = {_context_key(name) for name in names} | {review_key(name) for name in names}
    keys.update(_open_key(name) for name in ("ops_review_open_panel", "ops_review_zip", "ops_review_open"))
    keys.update(
        "_analysis_memo_" + _context_key(name)
        for name in (
            "operations_calculations",
            "bridge_book",
            "operations_restore",
            "csv_source",
            "csv_preview",
            "operations_zip",
        )
    )
    keys.update("_analysis_memo_" + review_key(name) for name in ("cut_build", "cut_compare"))
    keys.add("_analysis_memo_" + review_key("policy_evaluation"))
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
            "_csv_working",
        )
    )
    for key in keys:
        st.session_state.pop(key, None)
    st.session_state[_context_key("_ops_review")] = {"token": uuid4().hex, "files": {}, "settings": {}}
    st.session_state[_context_key("_ops_open_token")] = uuid4().hex
    st.session_state[_context_key("_ops_cleared_notice")] = True
    st.session_state["operations_tabs"] = "Movimientos"


def new_review(context=None):
    present = _has_current_inputs(context) or st.session_state.get(_open_key("ops_review_zip")) is not None
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


def _has_current_inputs(context=None):
    active = st.session_state.get("_execution_proposal") or {}
    current = False
    if context is not None:
        binding = (context[2]["id"] if context[2] else None, context[3])
        current = (
            active.get("context") == binding and bool(active.get("inputs")) and bool(active.get("result"))
        )
    return (
        bool(_recovery().get("files"))
        or bool(movement_draft())
        or bool(csv_import_draft())
        or bool(
            st.session_state.get(_context_key("_csv_working"), {}).get("source")
            and st.session_state[_context_key("_csv_working")].get("bound_review_token")
            == _recovery().get("token")
        )
        or bool(recovered_proposal())
        or any(st.session_state.get(review_key(name)) is not None for name in ROLE_WIDGETS)
        or current
    )


def _restore_csv_book(manifest, files):
    """Keep a readable archive separate from a book that passes current financial checks."""
    origin = manifest.get("csv_import_data")
    if not origin or origin["applied_ledger_sha256"] is None:
        return files, origin, False

    from csv_mapping import preview

    try:
        current = preview(origin["source"], origin["mapping"], origin["decisions"])
    except PortfolioError:
        current = None
    if current and current["ready"] and current["ledger"] == files["ledger"]:
        return files, origin, False
    return (
        {role: raw for role, raw in files.items() if role != "ledger"},
        {**origin, "applied_ledger_sha256": None},
        True,
    )


def open_review(context):
    with st.expander("Abrir paquete de movimientos", key=_open_key("ops_review_open_panel")):
        st.caption(
            "Elige el ZIP completo, sin extraerlo. PDF y TXT sirven para leer resultados; "
            "para continuar necesitas el ZIP. El paquete de varias cuentas se abre en "
            "Patrimonio → Consolidar libros revisados."
        )
        package = st.file_uploader(
            "Paquete de movimientos ZIP", type=["zip"], max_upload_size=15, key=_open_key("ops_review_zip")
        )
        with st.expander("Copias personales en tu computadora"):
            st.write(
                "Comprueba que descargaste el ZIP antes de cerrar. Puedes conservar una copia "
                "cifrada en tu computadora y recuperar el mismo ZIP cuando lo necesites."
            )
            st.caption(
                "La clave se conserva por separado en tu equipo. La guía explica los pasos; "
                "los documentos reales GBM se revisan únicamente en local."
            )
            st.download_button(
                "Descargar guía de copias personales",
                local_copy_guide(),
                "guia_copias_personales.txt",
                "text/plain",
                on_click="ignore",
                key=_open_key("ops_local_copy_guide"),
            )
        if package:
            try:
                raw = package.getvalue()
                scope = _scope(context)
                manifest, files = session_compute(
                    st.session_state,
                    _context_key("operations_restore"),
                    analysis_key(raw, scope, review_code_fingerprints(schema=6)),
                    lambda: read_operations_review(raw, **scope),
                    max_entries=1,
                )
            except PortfolioError as exc:
                st.error(str(exc))
            else:
                st.write("**Vista previa del paquete**")
                st.text(
                    f"Corte: {manifest['cutoff']} · Moneda: {manifest['base']} · {len(files)} archivos CSV"
                )
                if manifest.get("csv_import_data"):
                    st.caption("El paquete también conserva el CSV original y su correspondencia.")
                inventory = movements_inventory(manifest, files)
                st.info(inventory["stage"] + " · Al abrir se requiere una nueva revisión.")
                st.table(inventory["contents"])
                if inventory["originals_required"]:
                    st.warning(
                        "Debes volver a adjuntar los originales PDF/XML para cotejar el borrador. "
                        "El ZIP conserva la procedencia; los originales no están incluidos."
                    )
                if "ledger" not in files and manifest.get("draft_data"):
                    st.caption(
                        "Para llegar al rendimiento, completa la revisión del borrador y prepara el libro. "
                        "Los archivos internos JSON permiten retomar tus decisiones."
                    )
                elif "ledger" not in files and manifest.get("csv_import_data"):
                    st.caption(
                        "Retoma Preparar desde CSV con otras columnas; "
                        "revisa sus pendientes y prepara el libro."
                    )
                elif "ledger" not in files:
                    st.caption(
                        "Retoma la propuesta desde Implementación y revisa sus fuentes y supuestos. "
                        "Para calcular rendimiento necesitas además un libro de movimientos."
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
                if manifest.get("policy_data"):
                    st.caption(
                        "Incluye política propuesta. "
                        "Sus criterios requieren nuevas confirmaciones y evaluación."
                    )
                st.caption(
                    "Cargar el ZIP no cambia la revisión. Las vistas se recalculan al abrirlo; "
                    "el paquete no confirma fuentes ni flujos."
                )
                replacing = _has_current_inputs(context)
                if replacing:
                    st.warning(
                        "Se reemplazarán los CSV, el corte, la moneda y la propuesta de esta revisión. "
                        "Conserva una copia de lo que necesites antes de continuar."
                    )
                label = "Reemplazar revisión con este paquete" if replacing else "Retomar movimientos"
                if st.button(label, key=_open_key("ops_review_open")):
                    active_files, csv_import, csv_pending = _restore_csv_book(manifest, files)
                    st.session_state[_context_key("_ops_proposal_form_token")] = uuid4().hex
                    st.session_state[_context_key("_ops_review")] = {
                        "token": uuid4().hex,
                        "files": active_files,
                        "settings": {"cutoff": manifest["cutoff"], "base": manifest["base"]},
                        "code_changed": manifest["code_sha256"]
                        != review_code_fingerprints(schema=manifest["schema"]),
                        "draft": manifest.get("draft_data"),
                        "proposal": None if csv_pending else manifest.get("proposal_data"),
                        "policy": None if csv_pending else manifest.get("policy_data"),
                        "csv_import": csv_import,
                        "csv_ledger_pending": csv_pending,
                    }
                    st.session_state.pop(_context_key("_ops_last_book"), None)
                    st.session_state.pop(_context_key("_gbm_attached"), None)
                    st.rerun()
    if _recovery().get("settings"):
        st.info("Revisión recuperada. Se recalculan las vistas; confirma otra vez las fuentes y los flujos.")
        if _recovery().get("code_changed"):
            st.caption("El motor cambió desde la descarga; la revisión usa la versión actual.")
        if _recovery().get("csv_ledger_pending"):
            st.warning(
                "El libro CSV requiere correcciones con las reglas actuales. Retoma la correspondencia y "
                "vuelve a cotejar los importes. Conserva el ZIP original como evidencia."
            )


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
        else "Guardar borrador CSV"
        if suffix == "_csv"
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
        csv_import = csv_import_draft()
        if (
            csv_import
            and csv_import["applied_ledger_sha256"] is not None
            and (
                "ledger" not in present
                or sha256(present["ledger"]).hexdigest() != csv_import["applied_ledger_sha256"]
            )
        ):
            # A manually replaced book no longer has this source as its applied origin.
            csv_import = {**csv_import, "applied_ledger_sha256": None}
            st.caption("El CSV de origen se conserva como propuesta; el libro actual fue reemplazado.")
        proposal = proposal or current_proposal(context, present, cutoff=cutoff, base=base)
        status = st.session_state.get(_context_key("_ops_status"))
        policy = _recovery().get("policy")
        if policy and (policy["scope"] != _scope(context) or policy["base"] != base):
            st.caption(
                "La política guardada corresponde a otra moneda o cuenta; "
                "revisa Política y avisos de cartera."
            )
            policy = None
        summary = (
            status_text(status.snapshot("Revisión de movimientos"))
            if status and (draft or policy or csv_import)
            else None
        )
        args = {
            "cutoff": cutoff.isoformat(),
            "base": base,
            "draft": draft,
            "summary": summary,
            "proposal": proposal,
            "policy": policy,
            "csv_import": csv_import,
            **_scope(context),
        }
        _manifest, contents = session_compute(
            st.session_state,
            _context_key("operations_zip"),
            analysis_key(
                present,
                args,
                review_code_fingerprints(
                    schema=6
                    if csv_import
                    else 5
                    if policy
                    else (4 if proposal["schema"] == 2 else 3)
                    if proposal
                    else 2
                    if draft
                    else 1
                ),
            ),
            lambda: build_operations_review(present, **args),
            max_entries=1,
        )
        if csv_import and "ledger" not in present:
            st.info(
                "Este ZIP guarda el borrador CSV y sus decisiones. "
                "Revisa los pendientes antes de usarlo como libro."
            )
        elif draft and "ledger" not in present:
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
        if csv_import:
            labels.append("CSV original, correspondencia y decisiones documentadas")
        if summary:
            labels.append("Resumen TXT")
        if proposal:
            labels.append("Propuesta completa con fuentes, tarifas, límites y resultado histórico")
        if policy:
            labels.append("Política propuesta sin confirmaciones ni avisos reutilizables")
        st.write("Incluye: " + ", ".join(labels) + ".")
