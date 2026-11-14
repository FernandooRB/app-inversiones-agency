"""Guided local review; uploaded originals never enter the portable package."""

from datetime import date
from hashlib import sha256

import pandas as pd
import streamlit as st

from analysis_session import analysis_key, session_compute
from gbm_movement_review import (
    add_manual_row,
    correct_row,
    draft_controls,
    draft_issues,
    materialize_draft,
    original_rows_match,
    read_movement_documents,
)
from operations_review_ui import (
    attached_originals,
    download_review,
    movement_draft,
    review_key,
    set_movement_draft,
    use_movement_draft,
)
from portfolio_core import PortfolioError
from scripts.gbm_review_fixture import fictional_statement
from transaction_ledger import COLUMNS, KINDS


def render_movement_import(context):
    with st.expander("Preparar desde estados GBM", expanded=movement_draft() is not None):
        st.caption(
            "Revisa los originales reales en tu equipo. En la web de prueba utiliza documentos ficticios. "
            "Los archivos y sus importes permanecen privados; el ZIP excluye los PDF/XML."
        )
        fixture = session_compute(
            st.session_state, "gbm_fictional_pdf", "v1", fictional_statement, max_entries=1
        )
        st.download_button(
            "Descargar PDF ficticio de práctica",
            fixture,
            "estado_gbm_ficticio.pdf",
            "application/pdf",
            key=review_key("gbm_fixture"),
            on_click="ignore",
        )
        uploads = st.file_uploader(
            "Estados GBM de la misma cuenta · PDF",
            type=["pdf"],
            accept_multiple_files=True,
            key=review_key("gbm_documents"),
        )
        if uploads:
            st.caption(
                "Preparar otro borrador reemplaza los movimientos de esta revisión. Descarga tu ZIP primero."
            )
            if st.button("Preparar borrador GBM", key=review_key("gbm_prepare")):
                try:
                    raw = [file.getvalue() for file in uploads]
                    draft = session_compute(
                        st.session_state,
                        "gbm_movement_import",
                        analysis_key(raw),
                        lambda: read_movement_documents(raw),
                    )
                    set_movement_draft(draft)
                    st.rerun()
                except PortfolioError as error:
                    st.error("No se pudo preparar el borrador.")
                    st.text(str(error))
                except (ValueError, OSError):
                    st.error("El PDF no tiene una estructura GBM legible y admitida.")
        draft = movement_draft()
        if draft is None:
            return
        issues = draft_issues(draft)
        st.write(
            f"**{len(draft['documents'])} estados · {len(draft['rows'])} filas de evidencia · "
            f"{len(issues)} incidencias de normalización**"
        )
        st.caption(
            "Borrador sin aprobación. Las coincidencias aritméticas no confirman clasificación ni fechas."
        )
        for document in draft["documents"]:
            st.text(f"{document['start']} a {document['end']} · SHA-256 {document['sha256'][:12]}…")
            for warning in document["warnings"]:
                st.warning(warning)
        if issues:
            st.dataframe(
                pd.DataFrame(issues).rename(columns={"id": "Referencia", "reason": "Por resolver"}),
                hide_index=True,
                width="stretch",
            )
        unresolved = {issue["id"] for issue in issues}
        editable = [row for row in draft["rows"] if not row["control"]]
        editable.sort(key=lambda row: row["id"] not in unresolved)
        with st.expander("Revisar movimientos y corregir propuestas", expanded=bool(issues)):
            if editable:
                chosen = st.selectbox(
                    "Movimiento a revisar",
                    [row["id"] for row in editable],
                    format_func=lambda identifier: next(
                        f"Página {r['page']}, fila {r['line']} · {r['text'][:85]}"
                        for r in editable
                        if r["id"] == identifier
                    ),
                    key=review_key("gbm_row"),
                )
                row = next(item for item in editable if item["id"] == chosen)
                st.text(row["text"])
                st.caption(f"Documento SHA-256 {row['document']} · Texto SHA-256 {row['text_sha256']}")
                with st.form(review_key("gbm_edit_" + chosen)):
                    proposal = dict(row["proposal"])
                    columns = st.columns(2)
                    types = [""] + sorted(KINDS)
                    proposal["Tipo"] = columns[0].selectbox(
                        "Clasificación",
                        types,
                        index=types.index(proposal["Tipo"]) if proposal["Tipo"] in types else 0,
                    )
                    labels = {
                        "Fecha": "Fecha de operación · AAAA-MM-DD",
                        "Liquidacion": "Fecha de liquidación · AAAA-MM-DD",
                        "Instrumento": "Instrumento",
                        "Moneda": "Moneda",
                        "Cantidad": "Cantidad",
                        "Precio": "Precio",
                        "Importe": "Importe bruto",
                        "Comision": "Comisión",
                        "Impuesto": "Impuesto",
                        "Referencia": "Referencia verificable",
                        "Interes": "Interés incluido en bruto",
                    }
                    for index, (key, label) in enumerate(labels.items()):
                        proposal[key] = columns[index % 2].text_input(label, proposal[key])
                    timings = ["UNKNOWN", "BOD", "EOD"]
                    proposal["MomentoFlujo"] = st.selectbox(
                        "Momento del flujo · conserva UNKNOWN si no consta",
                        timings,
                        index=timings.index(proposal["MomentoFlujo"])
                        if proposal["MomentoFlujo"] in timings
                        else 0,
                    )
                    reason = st.text_input("Motivo de la corrección")
                    source = st.text_input("Fuente del dato y ubicación en el documento")
                    if st.form_submit_button("Guardar propuesta revisada"):
                        try:
                            updated = correct_row(draft, chosen, proposal, reason=reason, source=source)
                            set_movement_draft(updated)
                            st.rerun()
                        except PortfolioError as error:
                            st.text(str(error))
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "ID": row["id"],
                            "Página": row["page"],
                            "Fila": row["line"],
                            "Uso": "Control de continuidad"
                            if row["control"]
                            else ("Entrada manual respaldada" if row["manual"] else "Propuesta"),
                            **{key: row["proposal"][key] for key in COLUMNS if key != "ID"},
                        }
                        for row in draft["rows"]
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        with st.expander("Añadir movimiento respaldado"):
            st.caption(
                "Para una posición inicial o movimiento que no figura en la tabla extraída. "
                "Aporta su fuente y motivo; las diferencias de centavos se conservan sin ajustes automáticos."
            )
            with st.form(review_key("gbm_manual")):
                types = sorted(KINDS)
                entry = {key: "0" for key in COLUMNS}
                entry.update(
                    ID="",
                    Tipo=st.selectbox("Tipo de entrada", types, index=types.index("OPEN_POSITION")),
                    Fecha=min(doc["start"] for doc in draft["documents"]),
                    Liquidacion=min(doc["start"] for doc in draft["documents"]),
                    Instrumento="",
                    Moneda="MXN",
                    Referencia="",
                    MomentoFlujo="UNKNOWN",
                )
                columns = st.columns(2)
                for index, key in enumerate(key for key in COLUMNS if key not in {"ID", "Tipo"}):
                    entry[key] = columns[index % 2].text_input("Entrada · " + key, entry[key])
                source = st.text_input("Fuente documental de la entrada")
                reason = st.text_input("Motivo de la entrada")
                if st.form_submit_button("Añadir al borrador"):
                    try:
                        set_movement_draft(add_manual_row(draft, entry, reason=reason, source=source))
                        st.rerun()
                    except PortfolioError as error:
                        st.text(str(error))
        expected = {doc["sha256"] for doc in draft["documents"]}
        originals = uploads or attached_originals()
        attached = {sha256(file.getvalue()).hexdigest() for file in originals}
        originals_present = expected.issubset(attached)
        if originals_present:
            raw = [file.getvalue() for file in originals if sha256(file.getvalue()).hexdigest() in expected]
            try:
                originals_present = session_compute(
                    st.session_state,
                    "gbm_source_match",
                    analysis_key(
                        draft["documents"],
                        [
                            {
                                key: row[key]
                                for key in (
                                    "id",
                                    "document",
                                    "page",
                                    "line",
                                    "text",
                                    "text_sha256",
                                    "control",
                                    "suggested",
                                )
                            }
                            for row in draft["rows"]
                        ],
                        raw,
                    ),
                    lambda: original_rows_match(draft, raw),
                )
            except (ValueError, PortfolioError):
                originals_present = False
        if originals_present and not uploads:
            st.caption(
                "Originales cotejables conservados únicamente en esta sesión. "
                "Al reabrir un ZIP tendrás que adjuntarlos otra vez."
            )
        if not originals_present:
            st.info(
                "Adjunta los originales del borrador para cotejarlos. Las huellas deben coincidir; "
                "el ZIP conserva propuestas, sin confirmar sus fuentes."
            )
        confirmed = st.checkbox(
            "Cotejé cuenta, moneda, todas las filas, fechas, importes, cargos y clasificación "
            "contra estos originales",
            key=review_key("gbm_confirmed"),
        )
        if st.button(
            "Usar movimientos revisados",
            disabled=bool(issues) or not originals_present or not confirmed,
            key=review_key("gbm_use"),
        ):
            try:
                raw = materialize_draft(draft)
                use_movement_draft(
                    raw, draft_controls(draft), cutoff=max(doc["end"] for doc in draft["documents"])
                )
                st.rerun()
            except PortfolioError as error:
                st.text(str(error))
        if not issues:
            st.caption(
                "Antes de continuar, confirma la cobertura de las categorías del estado y revisa "
                "cualquier advertencia. Los controles de cierre conservarán las diferencias."
            )
        download_review(
            context,
            {},
            cutoff=date.fromisoformat(max(doc["end"] for doc in draft["documents"])),
            base="MXN",
            suffix="gbm",
        )
