"""Session-local CSV correspondence editor; rendered only when requested."""

from copy import deepcopy
from datetime import date
from uuid import uuid4

import pandas as pd
import streamlit as st

from analysis_session import analysis_key, session_compute
from csv_mapping import (
    ENUMS,
    blank_mapping,
    pack_import,
    preview,
    read_source,
    read_template,
    sha,
    write_template,
)
from operations_review import review_code_fingerprints
from operations_review_ui import (
    _context_key,
    _recovery,
    _scope,
    csv_import_draft,
    download_review,
    reset_confirmation,
    review_key,
    set_csv_import,
)
from portfolio_core import PortfolioError
from scripts.csv_mapping_fixture import fictional_csv
from transaction_ledger import COLUMNS


def _save_decision(work_key, keys):
    work = st.session_state[work_key]
    values = {name: st.session_state[key] for name, key in keys.items()}
    action = values["action"]
    if action == "pending":
        work["decisions"].pop(str(values["row"]), None)
        work.pop("decision_error", None)
        return
    if not values["reason"].strip() or not values["source"].strip():
        work["decision_error"] = "Conserva la decisión pendiente hasta declarar motivo y fuente."
        return
    if len(work["decisions"]) >= 100 and str(values["row"]) not in work["decisions"]:
        work["decision_error"] = "Se admiten decisiones documentadas para un máximo de 100 filas."
        return
    work["decisions"][str(values["row"])] = {k: values[k] for k in ("action", "reason", "source")}
    work.pop("decision_error", None)


def _working():
    key = _context_key("_csv_working")
    token = _recovery().get("token")
    work = st.session_state.get(key)
    if work is None or work.get("bound_review_token") != token:
        work = deepcopy(csv_import_draft() or {"source": None, "mapping": blank_mapping([]), "decisions": {}})
        work.update(bound_review_token=token, widget_token=uuid4().hex)
        st.session_state[key] = work
    return key, work


def _field_editor(config, source, key):
    modes = {"missing": "Pendiente", "row": "ID técnico por fila", "constant": "Valor declarado"}
    origins = ["Pendiente", "ID técnico por fila", "Valor declarado"] + [
        "Columna · " + h for h in source["headers"]
    ]
    rows = []
    for field in COLUMNS:
        rule = config["fields"][field]
        origin = "Columna · " + rule["value"] if rule["mode"] == "column" else modes[rule["mode"]]
        rows.append(
            {
                "Campo": field,
                "Origen": origin if origin in origins else "Pendiente",
                "Valor declarado": rule["value"] if rule["mode"] == "constant" else "",
                "Transformación": "Magnitud" if rule["transform"] == "magnitude" else "Conservar",
            }
        )
    edited = st.data_editor(
        pd.DataFrame(rows),
        hide_index=True,
        disabled=["Campo"],
        key=key,
        column_config={
            "Origen": st.column_config.SelectboxColumn(options=origins, required=True),
            "Transformación": st.column_config.SelectboxColumn(
                options=["Conservar", "Magnitud"], required=True
            ),
        },
        width="stretch",
    )
    for _, row in edited.iterrows():
        origin = row["Origen"]
        mode = (
            "column"
            if origin.startswith("Columna · ")
            else {"Pendiente": "missing", "ID técnico por fila": "row", "Valor declarado": "constant"}[origin]
        )
        config["fields"][row["Campo"]] = {
            "mode": mode,
            "value": origin[len("Columna · ") :]
            if mode == "column"
            else str(row["Valor declarado"] or "")
            if mode == "constant"
            else "",
            "transform": "magnitude" if row["Transformación"] == "Magnitud" else "identity",
        }


def _field_form(config, source, work, key):
    """Native controls offer a complete keyboard/touch alternative to the grid."""
    with st.expander("Editar un campo con formulario"):
        field = st.selectbox("Campo del libro", list(COLUMNS), key=key("form_field"))
        rule = config["fields"][field]
        origins = ["Pendiente", "Valor declarado"]
        if field == "ID":
            origins.append("ID técnico por fila")
        origins += ["Columna · " + h for h in source["headers"]]
        selected = {"missing": "Pendiente", "constant": "Valor declarado", "row": "ID técnico por fila"}.get(
            rule["mode"], "Columna · " + rule["value"]
        )
        transforms = (
            ["identity", "magnitude"]
            if field in {"Cantidad", "Importe", "Comision", "Impuesto"}
            else ["identity"]
        )
        with st.form(key("field_form_" + field)):
            origin = st.selectbox(
                "Origen del campo",
                origins,
                index=origins.index(selected) if selected in origins else 0,
                key=key("form_origin_" + field),
            )
            value = st.text_input(
                "Valor acreditado · sólo para Valor declarado",
                value=rule["value"] if rule["mode"] == "constant" else "",
                max_chars=2000,
                key=key("form_value_" + field),
            )
            transform = st.selectbox(
                "Transformación del campo",
                transforms,
                index=transforms.index(rule["transform"]) if rule["transform"] in transforms else 0,
                format_func=lambda v: "Conservar" if v == "identity" else "Magnitud",
                key=key("form_transform_" + field),
            )
            if st.form_submit_button("Aplicar campo a la propuesta"):
                mode = (
                    "column"
                    if origin.startswith("Columna · ")
                    else {
                        "Pendiente": "missing",
                        "Valor declarado": "constant",
                        "ID técnico por fila": "row",
                    }[origin]
                )
                config["fields"][field] = {
                    "mode": mode,
                    "value": origin[len("Columna · ") :]
                    if mode == "column"
                    else value
                    if mode == "constant"
                    else "",
                    "transform": transform,
                }
                work.update(mapping=config, decisions={}, widget_token=uuid4().hex)
                st.rerun()


def _value_form(config, source, work, key):
    with st.expander("Editar una clasificación con formulario"):
        field = st.selectbox("Lista de valores", list(ENUMS), key=key("enum_field"))
        rule = config["fields"][field]
        values = (
            sorted({r["original"].get(rule["value"], "").strip() for r in source["rows"]})
            if rule["mode"] == "column"
            else [rule["value"]]
            if rule["mode"] == "constant"
            else []
        )
        values = [v for v in values if v]
        if not values or len(values) > 100:
            st.caption("Declara primero la columna o valor; esta lista admite hasta 100 valores distintos.")
            return
        original = st.selectbox("Valor original a clasificar", values, key=key("enum_raw_" + field))
        allowed = [""] + sorted(ENUMS[field])
        current = config["values"][field].get(original, original if original in allowed else "")
        with st.form(key("enum_form_" + field + "_" + sha(original.encode())[:16])):
            canonical = st.selectbox(
                "Valor del libro",
                allowed,
                index=allowed.index(current),
                key=key("enum_canonical_" + field + "_" + sha(original.encode())[:16]),
            )
            if st.form_submit_button("Aplicar clasificación a la propuesta"):
                if canonical:
                    config["values"][field][original] = canonical
                else:
                    config["values"][field].pop(original, None)
                work.update(mapping=config, decisions={}, widget_token=uuid4().hex)
                st.rerun()


def render_csv_mapping(context):
    panel = review_key("csv_mapping_panel")
    with st.expander(
        "Preparar desde CSV con otras columnas",
        expanded=bool(csv_import_draft()),
        key=panel,
        on_change="rerun",
    ):
        if not st.session_state.get(panel, False):
            return
        work_key, work = _working()
        generation = work["widget_token"]

        def key(name):
            return _context_key("csv_" + name) + "_" + generation

        st.write(
            "Relaciona cada campo del libro con una columna o un valor acreditado. "
            "Revisa los datos antes de reemplazar la revisión."
        )
        st.caption(
            "Usa archivos ficticios en la web. "
            "Los documentos y resultados reales se revisan sólo localmente. "
            "CSV de hasta 2 MB, 20,000 filas y 40 columnas."
        )
        with st.expander("Práctica con datos ficticios"):
            raw_fixture, template_fixture = fictional_csv()
            st.download_button(
                "Descargar CSV ficticio",
                raw_fixture,
                "movimientos_csv_ficticios.csv",
                "text/csv",
                on_click="ignore",
                key=key("fixture"),
            )
            st.download_button(
                "Descargar correspondencia ficticia",
                template_fixture,
                "correspondencia_ficticia.json",
                "application/json",
                on_click="ignore",
                key=key("fixture_template"),
            )
            st.caption(
                "Carga ambos archivos, aplica la correspondencia y coteja: apertura 100, aportación 50 "
                "y comisión 1; efectivo final 149 MXN. La aportación no es ganancia."
            )
        uploaded = st.file_uploader(
            "CSV original para correspondencia", type=["csv"], max_upload_size=2, key=key("source")
        )
        if uploaded is not None and uploaded.getvalue() != work.get("source"):
            work.update(
                source=uploaded.getvalue(), mapping=blank_mapping([]), decisions={}, widget_token=uuid4().hex
            )
            st.rerun()
        if work.get("source") is None:
            return
        st.caption(
            f"Original conservado en la sesión · {len(work['source'])} bytes · SHA-256 {sha(work['source'])}"
        )
        config = deepcopy(work["mapping"])
        with st.expander("Formato del archivo", expanded=True):
            config["delimiter"] = st.selectbox(
                "Separador",
                [",", ";", "\t"],
                index=[",", ";", "\t"].index(config["delimiter"]),
                format_func=lambda v: {"\t": "Tabulación", ",": "Coma", ";": "Punto y coma"}[v],
                key=key("delimiter"),
            )
            config["encoding"] = st.selectbox(
                "Codificación",
                ["utf-8-sig", "cp1252"],
                index=["utf-8-sig", "cp1252"].index(config["encoding"]),
                key=key("encoding"),
            )
            config["date_format"] = st.selectbox(
                "Formato de fechas",
                ["ISO", "DMY", "MDY"],
                index=["ISO", "DMY", "MDY"].index(config["date_format"]),
                format_func=lambda v: {"ISO": "AAAA-MM-DD", "DMY": "DD/MM/AAAA", "MDY": "MM/DD/AAAA"}[v],
                key=key("dates"),
            )
            config["decimal"] = st.selectbox(
                "Separador decimal", [".", ","], index=[".", ","].index(config["decimal"]), key=key("decimal")
            )
            config["thousands"] = st.selectbox(
                "Separador de miles",
                ["", ".", ",", " "],
                index=["", ".", ",", " "].index(config["thousands"]),
                format_func=lambda v: {"": "Sin agrupación", " ": "Espacio", ".": "Punto", ",": "Coma"}[v],
                key=key("thousands"),
            )
        try:
            source = session_compute(
                st.session_state,
                _context_key("csv_source"),
                analysis_key(work["source"], config["delimiter"], config["encoding"]),
                lambda: read_source(work["source"], config["delimiter"], config["encoding"]),
                max_entries=1,
            )
        except PortfolioError as exc:
            work["mapping"] = config
            st.error(str(exc))
            return
        template = st.file_uploader(
            "Correspondencia guardada JSON · opcional", type=["json"], max_upload_size=1, key=key("template")
        )
        if template is not None and st.button("Aplicar correspondencia guardada", key=key("apply_template")):
            try:
                loaded = read_template(template.getvalue(), work["source"])
            except PortfolioError as exc:
                st.error(str(exc))
            else:
                work.update(mapping=loaded, decisions={}, widget_token=uuid4().hex)
                st.rerun()
        with st.expander("Columnas y valores del libro", expanded=True):
            st.caption(
                "Importe es bruto; comisión e impuesto van separados. No se infieren ceros ni signos. "
                "Magnitud sólo se admite en Cantidad, Importe, Comision e Impuesto y conserva el signo "
                "original como evidencia. Un reintegro o reverso requiere revisión propia."
            )
            _field_editor(config, source, key("fields"))
            _field_form(config, source, work, key)
            trade, settlement = config["fields"]["Fecha"], config["fields"]["Liquidacion"]
            if trade["mode"] == settlement["mode"] == "column" and trade["value"] == settlement["value"]:
                st.warning(
                    "Operación y liquidación usan la misma columna. "
                    "Coteja que ambas fechas coincidan en la fuente."
                )
            for field, allowed in ENUMS.items():
                rule = config["fields"][field]
                raw_values = (
                    sorted({r["original"].get(rule["value"], "").strip() for r in source["rows"]})
                    if rule["mode"] == "column"
                    else [rule["value"]]
                    if rule["mode"] == "constant"
                    else []
                )
                if len(raw_values) > 100:
                    st.warning(
                        field + ": hay más de 100 valores distintos. Reduce el archivo o revisa su columna."
                    )
                    continue
                rows = [
                    {"Original": v, "Libro": config["values"][field].get(v, v if v in allowed else "")}
                    for v in raw_values
                    if v
                ]
                if rows:
                    st.write("Correspondencia de " + field)
                    edited = st.data_editor(
                        pd.DataFrame(rows),
                        hide_index=True,
                        disabled=["Original"],
                        key=key("values_" + field),
                        column_config={
                            "Libro": st.column_config.SelectboxColumn(options=[""] + sorted(allowed))
                        },
                        width="stretch",
                    )
                    prior = config["values"][field]
                    config["values"][field] = {
                        r["Original"]: r["Libro"]
                        for _, r in edited.iterrows()
                        if r["Libro"]
                        and (
                            r["Original"] not in allowed
                            or r["Original"] != r["Libro"]
                            or r["Original"] in prior
                        )
                    }
            _value_form(config, source, work, key)
            st.caption(
                "UNKNOWN conserva el momento del flujo desconocido. "
                "No acredita BOD/EOD ni habilita por sí solo el TWR."
            )
            config["basis"] = st.text_input(
                "Fuente y motivo de la correspondencia",
                value=config["basis"],
                max_chars=1000,
                key=key("basis"),
            )
        if config != work["mapping"]:
            if work["decisions"]:
                st.info("Cambió la correspondencia: revisa otra vez las decisiones de filas.")
            work["decisions"] = {}
        work["mapping"] = config
        try:
            result = session_compute(
                st.session_state,
                _context_key("csv_preview"),
                analysis_key(work["source"], config, work["decisions"], review_code_fingerprints(schema=6)),
                lambda: preview(work["source"], config, work["decisions"]),
                max_entries=1,
            )
        except PortfolioError as exc:
            st.error(str(exc))
            return
        st.write(
            f"{len(result['rows'])} filas · {len(result['issues'])} pendientes · "
            f"{result['excluded']} exclusiones documentadas"
        )
        with st.expander("Original, propuesta y pendientes", expanded=bool(result["issues"])):
            chosen = int(
                st.number_input(
                    "Fila original a cotejar",
                    min_value=1,
                    max_value=len(result["rows"]),
                    step=1,
                    key=key("view_row"),
                )
            )
            row = result["rows"][chosen - 1]
            st.caption(
                f"Registro {chosen} · líneas {row['line_start']} a {row['line_end']} · "
                f"{'Excluido' if row['excluded'] else 'Incluido en propuesta'}"
            )
            st.json({"original": row["original"], "propuesta": row["mapped"]}, expanded=False)
            if result["issues"]:
                st.dataframe(pd.DataFrame(result["issues"][:200]), hide_index=True, width="stretch")
                st.download_button(
                    "Descargar todos los pendientes CSV",
                    pd.DataFrame(result["issues"]).to_csv(index=False).encode("utf-8-sig"),
                    "pendientes_correspondencia.csv",
                    "text/csv",
                    key=key("issues"),
                    on_click="ignore",
                )
                st.caption("La tabla muestra hasta 200 pendientes; la descarga incluye todos.")
        with st.expander("Decidir sobre filas repetidas o excluidas"):
            fields = {n: key("decision_" + n) for n in ("row", "action", "reason", "source")}
            with st.form(key("decision_form")):
                st.number_input(
                    "Fila para la decisión",
                    min_value=1,
                    max_value=len(result["rows"]),
                    step=1,
                    key=fields["row"],
                )
                st.selectbox(
                    "Decisión de fila",
                    ["pending", "include", "exclude"],
                    format_func=lambda v: {
                        "pending": "Conservar pendiente",
                        "include": "Incluir y justificar coincidencia",
                        "exclude": "Excluir con evidencia",
                    }[v],
                    key=fields["action"],
                )
                st.text_input("Motivo de la decisión", max_chars=1000, key=fields["reason"])
                st.text_input("Fuente de la decisión", max_chars=1000, key=fields["source"])
                st.form_submit_button(
                    "Guardar decisión de fila", on_click=_save_decision, args=(work_key, fields)
                )
            if work.get("decision_error"):
                st.error(work["decision_error"])
            if work["decisions"]:
                st.json(work["decisions"], expanded=False)
        defaults = _recovery().get("settings", {})
        cutoff = st.date_input(
            "Corte del libro CSV",
            value=date.fromisoformat(defaults["cutoff"]) if defaults.get("cutoff") else date.today(),
            max_value=date.today(),
            key=key("cutoff"),
        )
        base = st.selectbox(
            "Moneda de presentación del CSV",
            ["MXN", "USD"],
            index=0 if defaults.get("base", "MXN") == "MXN" else 1,
            key=key("base"),
        )
        reset_confirmation(
            "csv_confirmed", [work["source"], config, work["decisions"], cutoff, base, _scope(context)]
        )
        confirmed = st.checkbox(
            "Revisé cuenta, moneda, fechas, importes brutos, cargos y clasificación contra la fuente",
            key=review_key("csv_confirmed"),
        )
        st.warning(
            "Guardar o usar este borrador reemplaza los CSV y borradores de Movimientos de esta revisión, "
            "incluidas valuaciones y controles anteriores. Descarga el ZIP actual antes de continuar."
        )
        origin = {
            "source": work["source"],
            "mapping": config,
            "decisions": work["decisions"],
            "scope": _scope(context),
            "applied_ledger_sha256": None,
        }
        portable = True
        try:
            pack_import(origin)
            template_bytes = write_template(config, source)
        except PortfolioError as exc:
            portable = False
            st.error(str(exc))
        if st.button("Guardar borrador de correspondencia", disabled=not portable, key=key("save")):
            set_csv_import(origin, cutoff=cutoff, base=base)
            st.rerun()
        if st.button(
            "Usar movimientos del CSV",
            disabled=not (portable and result["ready"] and confirmed),
            key=key("use"),
        ):
            set_csv_import(origin, ledger=result["ledger"], cutoff=cutoff, base=base)
            st.rerun()
        if portable:
            st.download_button(
                "Descargar correspondencia reutilizable",
                template_bytes,
                "correspondencia_csv.json",
                "application/json",
                key=key("download_template"),
                on_click="ignore",
            )
        if csv_import_draft() and not _recovery().get("files", {}).get("ledger"):
            download_review(context, {}, cutoff=cutoff, base=base, suffix="_csv")
