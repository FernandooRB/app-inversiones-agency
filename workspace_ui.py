"""Internal case-register UI. Storage is explicitly configured, never inferred."""

import json
from datetime import date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
import streamlit as st

from account_consolidation import consolidate_snapshots, prepare_account_snapshot
from case_workspace import (
    EVIDENCE,
    PRODUCTS,
    CaseStore,
    Principal,
    WorkspaceError,
    case_readiness,
    principal_from_claims,
)
from consolidated_reporting import create_consolidation_pdf
from portfolio_core import PortfolioError, normalize_tickers


def configured_workspace():
    try:
        configuration = st.secrets.get("workspace", {})
        policy = st.secrets.get("access", {})
    except FileNotFoundError:
        raise WorkspaceError(
            "Configura almacenamiento cifrado y roles antes de guardar expedientes."
        ) from None
    if configuration.get("enabled") is not True:
        raise WorkspaceError(
            "El registro persistente está desactivado; el análisis en sesión sigue disponible."
        )
    principal = principal_from_claims(st.user.to_dict(), policy)
    key = configuration.get("encryption_key", "")
    location = configuration.get("database_path", "")
    if not isinstance(key, str) or not isinstance(location, str) or not Path(location).is_absolute():
        raise WorkspaceError("Configura una clave y una ruta absoluta de almacenamiento privado.")
    store = CaseStore(Path(location), key.encode())
    return store, principal, policy


def render_workspace():
    st.title("Expedientes por cuenta")
    st.caption("Archivo interno · alias sin nombres ni números de cuenta · entrega a clientes pendiente")
    try:
        store, principal, policy = configured_workspace()
    except WorkspaceError as error:
        st.info(str(error))
        st.markdown(
            "El registro conserva perfiles, cuentas, evidencia, archivos y versiones cifradas. "
            "Un administrador debe configurar su ubicación, clave y roles. "
            "La guía operativa explica la preparación y las pruebas de respaldo."
        )
        return
    try:
        if not store.path.exists():
            st.info("Aún no hay un registro inicializado en la ubicación configurada.")
            if principal.role == "ADMIN" and st.button("Inicializar registro privado", type="primary"):
                store.initialize(principal)
                st.rerun()
            return
        rows = store.list_cases(principal)
        active = [row for row in rows if not row["archived"]]
        st.write(f"**{len(active)} expediente(s) activo(s)** · {len(rows) - len(active)} archivado(s)")
        if principal.role in {"ADMIN", "ANALYST"}:
            with st.expander("Crear expediente"):
                with st.form("create_case"):
                    alias = st.text_input(
                        "Alias del expediente",
                        max_chars=80,
                        help="Usa un alias interno; guarda la identidad del titular en el sistema "
                        "autorizado correspondiente.",
                    )
                    own = st.checkbox("Es una cuenta propia para el piloto", value=True)
                    if st.form_submit_button("Crear expediente"):
                        created = store.create(principal, alias, own_account=own)
                        st.session_state["workspace_case_id"] = created["id"]
                        st.rerun()
        if not rows:
            st.info("No tienes expedientes asignados. Crea uno o solicita la asignación al administrador.")
            return
        ids = [row["id"] for row in rows]
        labels = {row["id"]: row["alias"] + (" · archivado" if row["archived"] else "") for row in rows}
        if st.session_state.get("workspace_case_id") not in ids:
            st.session_state["workspace_case_id"] = ids[0]
        case_id = st.selectbox("Expediente", ids, format_func=labels.get, key="workspace_case_id")
        state = store.read(principal, case_id)
        readiness = case_readiness(state)
        purpose = "Piloto propio" if state["own_account"] else "Cliente pendiente de habilitación"
        st.caption(f"Versión {state['revision']} · {purpose}")
        pending_label = f"**{len(readiness['missing'])} pendiente(s)**"
        st.write(pending_label + " · revisiones internas; entrega a clientes pendiente.")
        tabs = st.tabs(
            [
                "Cuenta y perfil",
                "Evidencia",
                "Archivos",
                "Revisión e historial",
                "Administración",
                "Consolidado",
            ]
        )
        editable = principal.role in {"ADMIN", "ANALYST"} and not state["archived"]
        with tabs[0]:
            account_column, profile_column = st.columns(2, gap="medium")
            with account_column:
                st.subheader("Intermediario, producto y cartera")
                if state["accounts"]:
                    st.dataframe(
                        pd.DataFrame(state["accounts"])[
                            ["broker", "product", "portfolio", "currency"]
                        ].rename(
                            columns={
                                "broker": "Intermediario",
                                "product": "Producto",
                                "portfolio": "Cartera",
                                "currency": "Moneda",
                            }
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                else:
                    st.caption(
                        "Sin cuentas registradas; no se han creado cuentas reales en ningún intermediario."
                    )
                if editable:
                    with st.expander("Añadir una cuenta"):
                        with st.form(f"account_{case_id}"):
                            broker = st.text_input("Intermediario", value="GBM", max_chars=80)
                            product = st.selectbox("Producto", PRODUCTS)
                            portfolio = st.text_input("Alias de cartera o subcuenta", max_chars=80)
                            currency = st.selectbox("Moneda de la cuenta", ["MXN", "USD"])
                            if st.form_submit_button("Añadir cuenta al expediente"):
                                store.update(
                                    principal,
                                    case_id,
                                    state["revision"],
                                    "account",
                                    {
                                        "broker": broker,
                                        "product": product,
                                        "portfolio": portfolio,
                                        "currency": currency,
                                    },
                                )
                                st.rerun()
            with profile_column:
                st.subheader("Objetivo y restricciones")
                st.caption(
                    "Capacidad y tolerancia a pérdidas se registran por separado. No asignamos un "
                    "portafolio automáticamente a partir de estas respuestas."
                )
                profile = state["profile"] or {}
                if profile:
                    st.write(profile["objective"])
                    st.write(f"**Horizonte declarado:** {profile['horizon_months']} meses")
                    st.write(f"**Necesidad de liquidez:** {profile['liquidity_mxn']:,.2f} MXN")
                    st.write(f"**Capacidad de pérdida:** {profile['loss_capacity_pct']:.2f}%")
                    st.write(f"**Tolerancia a pérdidas:** {profile['loss_tolerance_pct']:.2f}%")
                    st.caption(f"Respuestas declaradas · revisión {profile['reviewed_on']}")
                with st.expander("Recabar o actualizar perfil", expanded=not bool(profile)):
                    with st.form(f"profile_{case_id}"):
                        objective = st.text_input(
                            "Objetivo de inversión",
                            value=profile.get("objective", ""),
                            max_chars=500,
                            disabled=not editable,
                        )
                        horizon = st.number_input(
                            "Horizonte en meses",
                            min_value=1,
                            max_value=600,
                            value=profile.get("horizon_months", 12),
                            disabled=not editable,
                        )
                        liquidity = st.number_input(
                            "Necesidad de liquidez (MXN)",
                            min_value=0.0,
                            value=float(profile.get("liquidity_mxn", 0)),
                            disabled=not editable,
                        )
                        capacity = st.number_input(
                            "Pérdida que puede absorber (%)",
                            min_value=0.0,
                            max_value=100.0,
                            value=float(profile.get("loss_capacity_pct", 0)),
                            disabled=not editable,
                        )
                        tolerance = st.number_input(
                            "Pérdida que está dispuesto a aceptar (%)",
                            min_value=0.0,
                            max_value=100.0,
                            value=float(profile.get("loss_tolerance_pct", 0)),
                            disabled=not editable,
                        )
                        experiences = ["BASICA", "INTERMEDIA", "AVANZADA"]
                        experience = st.selectbox(
                            "Experiencia declarada",
                            experiences,
                            index=experiences.index(profile.get("experience", "BASICA")),
                            disabled=not editable,
                        )
                        restrictions = st.text_input(
                            "Restricciones y exclusiones",
                            value=profile.get("restrictions", ""),
                            max_chars=1000,
                            disabled=not editable,
                        )
                        reviewed = st.date_input(
                            "Fecha de entrevista o revisión",
                            value=date.fromisoformat(profile["reviewed_on"]) if profile else date.today(),
                            max_value=date.today(),
                            disabled=not editable,
                        )
                        confirmed = st.checkbox(
                            "Las respuestas fueron recabadas y revisadas; no son valores de ejemplo",
                            disabled=not editable,
                        )
                        if st.form_submit_button("Guardar perfil", disabled=not editable):
                            if not confirmed:
                                st.error("Confirma que las respuestas fueron recabadas antes de guardarlas.")
                            else:
                                store.update(
                                    principal,
                                    case_id,
                                    state["revision"],
                                    "profile",
                                    {
                                        "objective": objective,
                                        "horizon_months": int(horizon),
                                        "liquidity_mxn": liquidity,
                                        "loss_capacity_pct": capacity,
                                        "loss_tolerance_pct": tolerance,
                                        "experience": experience,
                                        "restrictions": restrictions,
                                        "reviewed_on": reviewed.isoformat(),
                                    },
                                )
                                st.rerun()
        with tabs[1]:
            st.subheader("Evidencia declarada")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Control": label,
                            "Estado": "Declarada; requiere cotejo"
                            if code in state["evidence"]
                            else "Pendiente",
                            "Referencia": state["evidence"].get(code, {}).get("reference", "—"),
                        }
                        for code, label in EVIDENCE.items()
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
            if editable:
                with st.form(f"evidence_{case_id}"):
                    control = st.selectbox("Control a documentar", list(EVIDENCE), format_func=EVIDENCE.get)
                    document = st.file_uploader(
                        "Documento de evidencia (máximo 5 MB)",
                        type=["pdf", "csv", "json", "xml", "txt"],
                        key=f"evidence_file_{case_id}",
                    )
                    reference = st.text_input("Referencia y alcance de la evidencia", max_chars=300)
                    reviewed_on = st.date_input("Fecha de revisión documental", max_value=date.today())
                    expiry_applies = st.checkbox("La evidencia tiene vencimiento")
                    expiry = st.date_input("Vence el", value=date.today())
                    if st.form_submit_button("Registrar huella de evidencia"):
                        if document is None or not 0 < document.size <= 5_000_000:
                            st.error("Selecciona un documento válido de hasta 5 MB.")
                        else:
                            store.update(
                                principal,
                                case_id,
                                state["revision"],
                                "evidence",
                                {
                                    "control": control,
                                    "sha256": sha256(document.getvalue()).hexdigest(),
                                    "reference": reference,
                                    "reviewed_on": reviewed_on.isoformat(),
                                    "expires_on": expiry.isoformat() if expiry_applies else None,
                                },
                            )
                            st.rerun()
                st.caption(
                    "Este control guarda la huella y referencia; conserva el original en Archivos si "
                    "deseas incluirlo en el registro cifrado. No verifica su autenticidad."
                )
        with tabs[2]:
            st.subheader("Archivos versionados")
            if editable:
                accounts = {
                    item["id"]: " · ".join(item[key] for key in ("broker", "product", "portfolio"))
                    for item in state["accounts"]
                }
                artifact_account = st.selectbox(
                    "Alcance del archivo",
                    [None, *accounts],
                    format_func=lambda value: accounts.get(value, "Expediente completo"),
                )
                upload = st.file_uploader(
                    "Adjuntar archivo privado (máximo 5 MB)",
                    type=["pdf", "csv", "json", "xml", "txt"],
                    key=f"artifact_{case_id}",
                )
                if st.button("Guardar archivo cifrado", disabled=upload is None):
                    store.attach(
                        principal,
                        case_id,
                        state["revision"],
                        upload.name,
                        upload.getvalue(),
                        account_id=artifact_account,
                    )
                    st.rerun()
            for item in state.get("artifacts", []):
                st.write(f"**{item['name']}** · versión {item['added_in_revision']} · {item['size']:,} bytes")
                if st.button("Preparar descarga", key=f"prepare_{item['id']}"):
                    metadata, contents = store.artifact(principal, case_id, item["id"])
                    st.download_button(
                        "Descargar archivo", contents, metadata["name"], key=f"download_{item['id']}"
                    )
            if not state.get("artifacts"):
                st.caption("Sin archivos guardados.")
        with tabs[3]:
            st.subheader("Revisión de la versión vigente")
            for item in readiness["missing"]:
                st.write(f"• {item}")
            if principal.role in {"ADMIN", "REVIEWER"} and not state["archived"]:
                with st.form(f"review_{case_id}"):
                    kind = st.selectbox("Tipo de revisión", ["TECNICA", "FINANCIERA"])
                    note = st.text_input("Conclusión, límites y pendientes de la revisión", max_chars=500)
                    if st.form_submit_button("Registrar revisión interna"):
                        store.review(principal, case_id, state["revision"], kind, note)
                        st.rerun()
            if st.checkbox("Consultar historial del expediente", key=f"history_{case_id}"):
                events = store.history(principal, case_id)
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Secuencia": row["sequence"],
                                "Acción": row["action"],
                                "Fecha UTC": row["at"],
                                "Responsable": row.get("actor", "")[:12],
                                "Versión": row.get("state", {}).get("revision", "—"),
                            }
                            for row in events
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
                st.download_button(
                    "Exportar historial privado JSON",
                    json.dumps(events, ensure_ascii=False, indent=2),
                    "historial_privado.json",
                    "application/json",
                )
        with tabs[4]:
            st.subheader("Acceso y conservación")
            if principal.role != "ADMIN":
                st.caption("Las asignaciones, respaldos y conservación corresponden a administración.")
            else:
                members = [
                    Principal(row["issuer"], row["subject"], row["role"])
                    for row in policy.get("identities", [])
                    if row.get("role") in {"ADMIN", "ANALYST", "REVIEWER", "VIEWER"}
                ]
                choice = st.selectbox(
                    "Identidad autorizada a asignar",
                    members,
                    format_func=lambda p: f"{p.role} · {p.actor[:12]}",
                )
                if st.button("Asignar integrante al expediente"):
                    store.grant(principal, case_id, choice)
                    st.rerun()
                if st.button(
                    "Revocar acceso de este integrante", disabled=choice is None or choice.role == "ADMIN"
                ):
                    store.revoke(principal, case_id, choice)
                    st.rerun()
                if st.button("Recuperar expediente" if state["archived"] else "Archivar expediente"):
                    store.update(principal, case_id, state["revision"], "archived", not state["archived"])
                    st.rerun()
                st.caption(
                    "La copia de seguridad y la comprobación de recuperación se realizan con el "
                    "comando operativo. El borrado definitivo exige expediente archivado y "
                    "confirmación explícita; también deben gestionarse los respaldos antiguos."
                )
        with tabs[5]:
            render_consolidation(store, principal, state, editable)
    except WorkspaceError as error:
        st.error(str(error))


def render_operations():
    st.title("Guía de operación")
    st.caption("Stochastics Investment Group · procedimiento del equipo")
    for title, body in (
        (
            "1. Preparar el expediente",
            "Usa un alias y registra intermediario, producto y cartera. Recaba objetivo, liquidez, "
            "horizonte y restricciones sin sustituir la entrevista por una puntuación automática.",
        ),
        (
            "2. Verificar los datos",
            "Coteja posiciones y cobertura al corte. Confirma identidad, moneda, ajustes, permisos de"
            " uso y una referencia independiente para los precios. Conserva las excepciones abiertas.",
        ),
        (
            "3. Ejecutar el análisis",
            "Compara cartera actual, referencia simple y alternativas. Revisa estabilidad, fuera de "
            "muestra, estrés, costos e impuestos. Las medias históricas no son pronósticos.",
        ),
        (
            "4. Registrar la revisión",
            "Guarda insumos y resultados en el expediente cifrado. Dos revisores distintos de quien "
            "editó registran la versión examinada. Los cambios posteriores requieren nuevas "
            "revisiones.",
        ),
        (
            "5. Preparar la entrega",
            "El registro actual conserva revisiones internas. La entrega personalizada sigue "
            "pendiente del alcance del servicio, permisos, privacidad y validación operativa del "
            "entorno final.",
        ),
    ):
        st.subheader(title)
        st.write(body)
    st.info(
        "Para el piloto GBM se puede estudiar una foto de posiciones mientras el cotejo histórico "
        "continúa; no se atribuye rendimiento realizado a una cuenta sin conciliar su historia."
    )


def render_archive_report(pdf: bytes, manifest: dict):
    """Explicitly bind an internal report bundle to an assigned case and account."""
    try:
        store, principal, _ = configured_workspace()
        if principal.role not in {"ADMIN", "ANALYST"} or not store.path.is_file():
            return
        cases = [item for item in store.list_cases(principal) if not item["archived"]]
        if not cases:
            return
        with st.expander("Guardar el análisis en un expediente"):
            st.caption(
                "Elige la cuenta y comprueba que corresponde a los insumos del análisis. La asociación "
                "declarada requiere revisión humana."
            )
            labels = {item["id"]: item["alias"] for item in cases}
            chosen = st.selectbox(
                "Expediente de destino",
                list(labels),
                format_func=labels.get,
                index=None,
                placeholder="Selecciona el expediente",
            )
            if chosen is None:
                st.caption("Selecciona el expediente antes de asociar una cuenta y guardar el reporte.")
                return
            state = store.read(principal, chosen)
            accounts = {
                item["id"]: " · ".join(item[key] for key in ("broker", "product", "portfolio"))
                for item in state["accounts"]
            }
            account = st.selectbox(
                "Cuenta del análisis",
                list(accounts),
                format_func=accounts.get,
                index=None,
                placeholder="Selecciona la cuenta",
            )
            confirmed = st.checkbox("Comprobé que los insumos y el reporte corresponden a esta cuenta")
            if st.button("Guardar comparativo y parámetros cifrados", disabled=not account or not confirmed):
                buffer = BytesIO()
                manifest = {
                    **manifest,
                    "case_id": chosen,
                    "account_id": account,
                    "case_revision_before_save": state["revision"],
                    "report_sha256": sha256(pdf).hexdigest(),
                    "client_delivery_allowed": False,
                }
                with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
                    archive.writestr("comparativo_interno.pdf", pdf)
                    archive.writestr(
                        "parametros_y_procedencia.json",
                        json.dumps(
                            manifest,
                            ensure_ascii=False,
                            sort_keys=True,
                            indent=2,
                            default=str,
                            allow_nan=False,
                        ),
                    )
                store.attach(
                    principal,
                    chosen,
                    state["revision"],
                    "analisis_interno.zip",
                    buffer.getvalue(),
                    account_id=account,
                )
                st.success(
                    "Análisis guardado; las revisiones deben corresponder a la nueva versión del expediente."
                )
    except WorkspaceError as error:
        # Disabled or absent storage is expected; it must not interrupt in-memory analysis.
        if st.session_state.get("workspace_case_id"):
            st.info(str(error))


def render_consolidation(store, principal, state, editable):
    st.subheader("Consolidado de posiciones en MXN")
    st.caption(
        "Primero se revisa cada cuenta. El consolidado suma valuaciones al mismo corte; no calcula "
        "rendimiento ni mezcla tramos de comisión."
    )
    eligible_accounts = [account for account in state["accounts"] if account["currency"] == "MXN"]
    if len(eligible_accounts) < 2:
        st.info(
            "Registra al menos dos cuentas MXN para preparar el consolidado. El piloto puede continuar con "
            "una sola."
        )
        return
    labels = {
        item["id"]: " · ".join(item[key] for key in ("broker", "product", "portfolio"))
        for item in eligible_accounts
    }
    selected = st.multiselect(
        "Cuentas a consolidar", list(labels), format_func=labels.get, disabled=not editable
    )
    supplied = []
    for account_id in selected:
        st.write(labels[account_id])
        assets = st.text_input(
            "Instrumentos, en orden", key=f"consolidation_assets_{account_id}", disabled=not editable
        )
        uploads = {
            role: st.file_uploader(
                label, type=["csv"], key=f"cons_{account_id}_{role}", disabled=not editable
            )
            for role, label in (
                ("holdings", "Posiciones al corte"),
                ("coverage", "Cobertura de esta cuenta"),
                ("identity", "Identidad de estas series MXN"),
            )
        }
        supplied.append((account_id, assets, uploads))
    confirmed = st.checkbox("Revisé pertenencia y corte de las cuentas seleccionadas", disabled=not editable)
    if st.button(
        "Preparar y guardar consolidado interno", disabled=not editable or not confirmed or len(selected) < 2
    ):
        try:
            snapshots = []
            for account_id, assets, uploads in supplied:
                if any(value is None for value in uploads.values()):
                    raise PortfolioError("Faltan archivos de una cuenta.")
                snapshots.append(
                    prepare_account_snapshot(
                        "Cuenta_" + account_id[:8],
                        tuple(normalize_tickers(assets)),
                        {role: value.getvalue() for role, value in uploads.items()},
                    )
                )
            result = consolidate_snapshots(tuple(snapshots))
            result["case_revision_before_save"] = state["revision"]
            result["account_ids"] = selected
            contents = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode()
            pdf = create_consolidation_pdf(result)
            bundle = BytesIO()
            with ZipFile(bundle, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("consolidado_interno.json", contents)
                archive.writestr("consolidado_interno.pdf", pdf)
            store.attach(
                principal, state["id"], state["revision"], "consolidado_interno.zip", bundle.getvalue()
            )
            st.success("Consolidado guardado como una nueva versión; requiere revisión interna.")
            st.dataframe(
                pd.DataFrame(result["accounts"]).drop(columns="fingerprints"),
                hide_index=True,
                width="stretch",
            )
            st.download_button(
                "Descargar consolidado interno JSON", contents, "consolidado_interno.json", "application/json"
            )
            st.download_button(
                "Descargar consolidado interno PDF", pdf, "consolidado_interno.pdf", "application/pdf"
            )
        except PortfolioError:
            st.error(
                "No se pudo consolidar. Comprueba archivos completos, corte común, identidad MXN y "
                "ausencia de duplicados."
            )
