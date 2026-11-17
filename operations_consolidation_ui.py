"""Session-private multi-account review, independent from the active single-account book."""

import csv
from hashlib import sha256
from io import StringIO
from uuid import uuid4

import pandas as pd
import streamlit as st

from analysis_session import analysis_key, session_compute
from operations_consolidation import (
    FX_COLUMNS,
    LINK_COLUMNS,
    canonical,
    code_hashes,
    consolidate_books,
    prepare_accounts,
)
from operations_consolidation_bundle import build_bundle, read_bundle
from operations_consolidation_report import money, report_csv, report_pdf, report_text
from portfolio_core import PortfolioError

CONFIRM = "Confirmé pertenencia, corte común, valuaciones y fuentes de estas cuentas"


def renew_confirmation(state, key, signature):
    if state.get(key + "_signature") != signature:
        state[key] = False
        state[key + "_signature"] = signature


def group_scope(context):
    store, principal, state, _ = context
    return analysis_key(
        str(store.path) if store else None,
        principal.actor if principal else None,
        state["id"] if state else None,
    )


def _append(key, columns, values):
    current = st.session_state.get(key, ",".join(columns) + "\n")
    stream = StringIO(newline="")
    csv.writer(stream).writerow(values)
    st.session_state[key] = current.rstrip("\r\n") + "\n" + stream.getvalue()


def _submit_fx(target, cutoff, base, currency_key, rate_key, source_key):
    _append(
        target,
        FX_COLUMNS,
        [
            cutoff,
            st.session_state[currency_key],
            base,
            st.session_state[rate_key],
            st.session_state[source_key],
        ],
    )


def _submit_links(target, out_key, in_key, source_key):
    _append(
        target,
        LINK_COLUMNS,
        [*st.session_state[out_key], *st.session_state[in_key], st.session_state[source_key]],
    )


def _cuts_changed(root, upload_key):
    files = st.session_state.get(upload_key) or []
    saved = st.session_state[root]
    st.session_state[root + "_" + saved["token"] + "_reviewed"] = False
    if len(files) > 10 or sum(len(f.getvalue()) for f in files) > 10_000_000:
        saved["upload_error"] = True
        return
    saved["upload_error"] = False
    previous = {sha256(e["cut"]).hexdigest(): e for e in saved["proposal"].get("entries", [])}
    entries = []
    for i, file in enumerate(files):
        raw = file.getvalue()
        entries.append(
            previous.get(sha256(raw).hexdigest(), {"alias": "Cuenta" + str(i + 1), "source": "", "cut": raw})
        )
    saved["proposal"]["entries"] = entries


def render_consolidation(context):
    scope = group_scope(context)
    root = "consolidation_" + scope
    saved = st.session_state.setdefault(root, {"token": uuid4().hex, "proposal": {}})
    token = saved["token"]

    def key(name):
        return root + "_" + token + "_" + name

    case_id = context[2]["id"] if context[2] else None
    allowed = {a["id"] for a in context[2]["accounts"]} if context[2] else None
    with st.expander("Consolidar libros revisados", key=root + "_panel", on_change="rerun"):
        if not st.session_state.get(root + "_panel", False):
            st.session_state[key("reviewed")] = False
            st.session_state.pop(key("pdf"), None)
            st.session_state.pop(key("zip"), None)
            return
        st.write("Reúne cortes de cuentas diferentes sin cambiar sus libros.")
        st.caption(
            "Exporta el JSON de cada cuenta desde Movimientos → Comparar y guardar cortes. "
            "Usa el mismo corte y declara la fuente de pertenencia. Originales reales sólo en local."
        )
        with st.expander("Reabrir consolidación guardada"):
            upload = st.file_uploader(
                "Paquete de consolidación ZIP", ["zip"], max_upload_size=12, key=key("restore")
            )
            if upload:
                try:
                    proposed = session_compute(
                        st.session_state,
                        root + "_restore",
                        analysis_key(upload.getvalue(), case_id, sorted(allowed or []), code_hashes()),
                        lambda: read_bundle(upload.getvalue(), case_id=case_id, allowed_accounts=allowed),
                        max_entries=1,
                    )
                    st.caption(
                        f"Propuesta: {len(proposed['entries'])} cuentas · {proposed['base']} · "
                        "requiere nueva confirmación."
                    )
                    if st.button(
                        "Reemplazar consolidación"
                        if saved["proposal"].get("entries")
                        else "Retomar consolidación",
                        key=key("replace"),
                    ):
                        _replace(root, proposed)
                except PortfolioError as exc:
                    st.error(str(exc))
        if st.button("Vaciar consolidación", key=key("clear")):
            _replace(root, {})
        proposal = saved["proposal"]
        base = st.selectbox(
            "Moneda del grupo de cuentas",
            ["MXN", "USD"],
            index=1 if proposal.get("base") == "USD" else 0,
            key=key("base"),
        )
        proposal["base"] = base
        st.file_uploader(
            "Cortes JSON de las cuentas",
            ["json"],
            accept_multiple_files=True,
            max_upload_size=2,
            key=key("cuts"),
            on_change=_cuts_changed,
            args=(root, key("cuts")),
        )
        original = proposal.get("entries", [])
        if saved.get("upload_error"):
            st.error("Hasta diez cuentas y 10 MB de cortes en total. Quita los archivos excedentes.")
            return
        if len(original) > 10 or sum(len(e["cut"]) for e in original) > 10_000_000:
            st.error("Hasta diez cuentas y 10 MB de cortes en total.")
            return
        entries = []
        for i, entry in enumerate(original):
            prefix = "account_" + str(i) + "_" + sha256(entry["cut"]).hexdigest()[:16]
            with st.expander(f"Identificar cuenta {i + 1}", expanded=True):
                alias = st.text_input(
                    f"Alias de cuenta {i + 1}", value=entry["alias"], max_chars=60, key=key(prefix + "alias")
                )
                source = st.text_input(
                    f"Fuente de pertenencia de cuenta {i + 1}",
                    value=entry["source"],
                    max_chars=500,
                    key=key(prefix + "source"),
                    help="Descripción local que permite cotejar que las cuentas te pertenecen; "
                    "evita datos personales en prácticas publicadas.",
                )
                entries.append({"alias": alias, "source": source, "cut": entry["cut"]})
        proposal["entries"] = entries
        if len(entries) < 2:
            st.info("Carga al menos dos cortes de cuentas diferentes para continuar.")
            return
        # A change invalidates consent even when the replacement later fails validation.
        signature = analysis_key(entries, base, sorted(allowed or []), code_hashes())
        if st.session_state.get(key("accounts_signature")) != signature:
            st.session_state[key("reviewed")] = False
            st.session_state[key("accounts_signature")] = signature
        try:
            prepared = session_compute(
                st.session_state,
                root + "_accounts",
                signature,
                lambda: prepare_accounts(entries, case_id=case_id, allowed_accounts=allowed),
                max_entries=1,
            )
            cutoff = prepared[0]["cut"]["payload"]["cutoff"]
        except PortfolioError as exc:
            st.error(str(exc))
            return
        st.caption(f"Corte común del grupo: {cutoff}. Valores nativos convertidos una sola vez.")
        fx_key, link_key = key("fx_text"), key("links_text")
        st.session_state.setdefault(
            fx_key, proposal.get("fx", b"").decode("utf-8-sig") or ",".join(FX_COLUMNS) + "\n"
        )
        st.session_state.setdefault(
            link_key, proposal.get("links", b"").decode("utf-8-sig") or ",".join(LINK_COLUMNS) + "\n"
        )
        with st.expander("Completar tipo de cambio"):
            with st.form(key("fx_form")):
                currency = st.selectbox(
                    "Moneda de origen FX", [c for c in ("MXN", "USD") if c != base], key=key("fx_currency")
                )
                st.text_input("Tasa FX del corte", key=key("fx_rate"))
                st.text_input("Fuente FX del grupo", max_chars=500, key=key("fx_source"))
                st.caption(f"Fecha {cutoff} · {currency} → {base}. No se estima ni se invierte la tasa.")
                st.form_submit_button(
                    "Añadir FX al CSV",
                    on_click=_submit_fx,
                    args=(fx_key, cutoff, base, key("fx_currency"), key("fx_rate"), key("fx_source")),
                )
            st.caption(
                "Si corriges una tasa, reemplaza la fila previa; no puede haber dos tasas de la misma moneda."
            )
        fx_input = st.text_area("FX documentado del grupo CSV", key=fx_key, height=100, max_chars=100_000)
        fx_upload = st.file_uploader(
            "Importar FX del grupo CSV", ["csv"], max_upload_size=1, key=key("fx_upload")
        )
        fx = fx_upload.getvalue() if fx_upload else fx_input.encode()
        proposal["fx"] = fx
        if fx_upload:
            st.caption("Se usa el CSV FX importado. Quítalo para utilizar el formulario o el texto editable.")
        with st.expander("Vincular transferencias con evidencia"):
            outs = [(s["alias"], e.id) for s in prepared for e in s["events"] if e.kind == "TRANSFER_OUT"]
            ins = [(s["alias"], e.id) for s in prepared for e in s["events"] if e.kind == "TRANSFER_IN"]
            if outs and ins:
                with st.form(key("links_form")):
                    st.selectbox(
                        "Pata de salida", outs, format_func=lambda v: v[0] + " · " + v[1], key=key("out")
                    )
                    st.selectbox(
                        "Pata de entrada", ins, format_func=lambda v: v[0] + " · " + v[1], key=key("in")
                    )
                    st.text_input("Fuente del vínculo entre cuentas", max_chars=500, key=key("link_source"))
                    st.form_submit_button(
                        "Añadir vínculo al CSV",
                        on_click=_submit_links,
                        args=(link_key, key("out"), key("in"), key("link_source")),
                    )
            st.caption(
                "Una coincidencia es sólo candidata. Se exige vínculo con fuente e importes, "
                "moneda y fechas iguales; diferencias y títulos quedan pendientes."
            )
        links_input = st.text_area("Vínculos documentados CSV", key=link_key, height=100, max_chars=100_000)
        links_upload = st.file_uploader(
            "Importar vínculos del grupo CSV", ["csv"], max_upload_size=1, key=key("links_upload")
        )
        links = links_upload.getvalue() if links_upload else links_input.encode()
        proposal["links"] = links
        if links_upload:
            st.caption("Se usa el CSV de vínculos importado. Quítalo para utilizar el texto editable.")
        full_signature = analysis_key(signature, fx, links)
        # Use one complete signature, including membership and code, for every financial output.
        renew_confirmation(st.session_state, key("reviewed"), full_signature)
        kwargs = {"base": base, "fx": fx, "links": links, "case_id": case_id, "allowed_accounts": allowed}
        try:
            session_compute(
                st.session_state,
                root + "_preview",
                full_signature,
                lambda: consolidate_books(entries, **kwargs),
                max_entries=1,
            )
        except PortfolioError as exc:
            st.session_state[key("reviewed")] = False
            st.error(str(exc))
            return
        confirmed = st.checkbox(CONFIRM, key=key("reviewed"))
        if st.session_state.get(key("artifact_signature")) != full_signature:
            st.session_state.pop(key("pdf"), None)
            st.session_state.pop(key("zip"), None)
            st.session_state[key("artifact_signature")] = full_signature
        try:
            report = session_compute(
                st.session_state,
                root + "_report",
                analysis_key(full_signature, confirmed),
                lambda: consolidate_books(entries, confirmed=confirmed, **kwargs),
                max_entries=2,
            )
        except PortfolioError as exc:
            st.error(str(exc))
            return
        if confirmed:
            st.metric(f"Patrimonio completo del grupo · {base}", money(report["nav"], base))
            st.write("Subtotal documentado del grupo: " + money(report["known_subtotal"], base))
            st.caption(report["notice"])
            display = [
                {
                    "Cuenta": a["alias"],
                    "Patrimonio": money(a["nav"], base),
                    "Subtotal": money(a["known_subtotal"], base),
                }
                for a in report["accounts"]
            ]
            st.dataframe(pd.DataFrame(display), hide_index=True, width="stretch")
            for issue in report["issues"]:
                st.warning(issue)
            with st.expander("Detalle de cuentas y evidencia"):
                st.dataframe(pd.DataFrame(report["detail"]), hide_index=True, width="stretch")
                if report["transfers"]:
                    st.dataframe(pd.DataFrame(report["transfers"]), hide_index=True, width="stretch")
                st.json(report["accounts"], expanded=False)
            st.download_button(
                "Descargar consolidación CSV",
                report_csv(report),
                "patrimonio_consolidado.csv",
                "text/csv",
                key=key("csv"),
                on_click="ignore",
            )
            st.download_button(
                "Descargar consolidación TXT",
                report_text(report).encode(),
                "patrimonio_consolidado.txt",
                "text/plain",
                key=key("txt"),
                on_click="ignore",
            )
            st.download_button(
                "Descargar resultado consolidado JSON",
                canonical(report),
                "patrimonio_consolidado.json",
                "application/json",
                key=key("json"),
                on_click="ignore",
            )
            if st.button("Preparar PDF de patrimonio", key=key("prepare_pdf")):
                st.session_state[key("pdf")] = report_pdf(report)
            if st.session_state.get(key("pdf")):
                st.download_button(
                    "Descargar PDF de patrimonio",
                    st.session_state[key("pdf")],
                    "patrimonio_consolidado.pdf",
                    "application/pdf",
                    key=key("pdf_download"),
                    on_click="ignore",
                )
        else:
            st.info("Revisión del grupo pendiente. Reabrir recupera propuestas y exige confirmar de nuevo.")
        if st.button("Preparar paquete de consolidación", key=key("prepare_zip")):
            st.session_state[key("zip")] = build_bundle(entries, **kwargs)
        if st.session_state.get(key("zip")):
            st.download_button(
                "Descargar paquete de consolidación",
                st.session_state[key("zip")],
                "consolidacion_cuentas.zip",
                "application/zip",
                key=key("zip_download"),
                on_click="ignore",
            )


def _replace(root, proposal):
    # Only this group and its memo are cleared; single-account work remains intact.
    for name in list(st.session_state):
        if (name.startswith(root + "_") and name != root + "_panel") or name.startswith(
            "_analysis_memo_" + root
        ):
            del st.session_state[name]
    st.session_state[root] = {"token": uuid4().hex, "proposal": proposal}
    st.rerun()
