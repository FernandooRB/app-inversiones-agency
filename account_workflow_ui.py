"""Account-centered research, with explicit review and immutable encrypted run attachments."""

from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pandas as pd
import streamlit as st

from account_demo import demo_account
from account_drafts import draft_payload, is_run, restore_draft, run_name, run_options
from account_import import confirm_gbm_draft, read_gbm_draft
from account_workflow import (
    AccountSettings,
    account_pdf,
    code_fingerprint,
    compare_account_cuts,
    make_run_bundle,
    read_run_bundle,
    run_account_analysis,
)
from analysis_session import analysis_key, session_compute
from case_workspace import WorkspaceError
from data_rights import RIGHTS_COLUMNS, read_data_rights_csv
from holdings import read_current_holdings_csv
from model_estimation import METHOD_LABELS
from portfolio_core import PortfolioError, normalize_tickers
from portfolio_exposure import ASSET_KINDS, COMPONENT_COLUMNS


def _context():
    from workspace_ui import configured_workspace

    try:
        store, principal, _ = configured_workspace()
        cases = [item for item in store.list_cases(principal) if not item["archived"]]
    except WorkspaceError:
        st.caption("Sesión temporal · configura Expedientes para guardar y retomar por cuenta.")
        return None, None, None, None
    labels = {None: "Analizar en esta sesión", **{item["id"]: item["alias"] for item in cases}}
    requested = st.session_state.pop("_open_analysis_case", None)
    if requested is not None and requested in labels:
        st.session_state["account_flow_case"] = requested
    if st.session_state.get("account_flow_case") not in labels:
        st.session_state["account_flow_case"] = None
    chosen = st.selectbox(
        "Expediente del análisis", list(labels), format_func=labels.get, key="account_flow_case"
    )
    if chosen is None:
        return store, principal, None, None
    state = store.read(principal, chosen)
    accounts = {
        item["id"]: " · ".join(item[key] for key in ("broker", "product", "portfolio"))
        for item in state["accounts"]
        if item["currency"] == "MXN"
    }
    if not accounts:
        st.info("Añade una cuenta MXN en Expedientes para usar este recorrido.")
        return store, principal, state, None
    requested_account = st.session_state.pop("_open_analysis_account", None)
    if requested_account in accounts:
        st.session_state[f"account_flow_account_{chosen}"] = requested_account
    account = st.selectbox(
        "Cuenta MXN", list(accounts), format_func=accounts.get, key=f"account_flow_account_{chosen}"
    )
    return store, principal, state, account


def _new_state(context):
    return {
        "context": context,
        "files": {},
        "metadata": {},
        "token": uuid4().hex,
        "defaults": {},
        "demo": False,
        "completed": None,
        "import_review": None,
    }


def _load(flow, manifest, files, settings, bundle):
    flow.update(
        files=files,
        metadata=manifest["metadata"],
        defaults=asdict(settings),
        token=uuid4().hex,
        completed=None,
        import_review=manifest.get("import_review"),
        loaded_manifest=manifest,
        demo=settings.objective == "Demostración ficticia",
    )
    with ZipFile(BytesIO(bundle)) as archive:
        flow["archived_pdf"] = archive.read("report.pdf") if "report.pdf" in archive.namelist() else None


def _archive_picker(flow, store, principal, state, account):
    if state is None or account is None:
        return
    runs = run_options(state, account)
    if not runs:
        return
    with st.expander("Retomar un análisis guardado"):
        chosen = st.selectbox("Ejecución guardada", list(runs), format_func=runs.get)
        if st.button("Abrir ejecución"):
            _, contents = store.artifact(principal, state["id"], chosen)
            manifest, files, settings = read_run_bundle(contents, case_id=state["id"], account_id=account)
            _load(flow, manifest, files, settings, contents)
            st.rerun()


def _import_positions(flow, prefix):
    st.subheader("1. Preparar la cartera")
    source = st.radio(
        "Origen de las posiciones",
        ["Cartera GBM XLSX", "Estado GBM PDF", "Cartera normalizada CSV"],
        key=prefix + "origin",
        horizontal=True,
    )
    if source == "Cartera GBM XLSX":
        uploaded = st.file_uploader(
            "Cartera GBM: formato de capitales y efectivo", type=["xlsx"], key=prefix + "gbm"
        )
        if uploaded:
            raw = uploaded.getvalue()
            draft = read_gbm_draft(raw)
            st.caption(
                "Confirma símbolo local por fila, corte y moneda. El formato no acredita por sí"
                " solo la cuenta."
            )
            st.dataframe(draft.rows.drop(columns=["Instrumento"]), hide_index=True, width="stretch")
            mapping = st.data_editor(
                draft.rows[["Fila", "Instrumento"]],
                disabled=["Fila"],
                hide_index=True,
                key=prefix + sha256(raw).hexdigest()[:10] + "mapping",
            )
            cutoff = st.date_input(
                "Corte declarado del documento", date.today(), max_value=date.today(), key=prefix + "cutoff"
            )
            total = st.number_input(
                "Total de cuenta cotejado con el original · MXN",
                min_value=0.0,
                step=1000.0,
                key=prefix + "total",
            )
            checked = st.checkbox(
                "Revisé las correspondencias y confirmé que posiciones y efectivo están valuados en MXN",
                key=prefix + "reviewed",
            )
            if st.button("Confirmar e importar cartera", disabled=not checked):
                review = confirm_gbm_draft(draft, mapping, cutoff, total, currency_confirmed=checked)
                flow["files"]["holdings"] = review["holdings"]
                flow["files"]["source_xlsx"] = raw
                flow["files"].pop("source_pdf", None)
                flow["import_review"] = {key: value for key, value in review.items() if key != "holdings"}
                flow["defaults"].update(outside_cash=float(review["cash_mxn"]))
                st.session_state[prefix + "cash"] = float(review["cash_mxn"])
                st.success("Cartera importada; se conservaron filas, huella y declaraciones de revisión.")
    elif source == "Estado GBM PDF":
        from gbm_documents import confirm_statement, read_statement

        uploaded = st.file_uploader("Estado de cuenta GBM · PDF original", type=["pdf"], key=prefix + "pdf")
        if uploaded:
            raw = uploaded.getvalue()
            draft = session_compute(
                st.session_state,
                "gbm_pdf",
                analysis_key(raw, code_fingerprint()),
                lambda: read_statement(raw),
            )
            st.caption(f"Corte {draft['end']} · revisa cuenta, moneda y correspondencias en el original.")
            st.dataframe(pd.DataFrame(draft["positions"]), hide_index=True, width="stretch")
            for warning in draft["warnings"]:
                st.warning(warning)
            mapping = st.data_editor(
                pd.DataFrame(
                    {
                        "Documento": [row["Instrumento"] for row in draft["positions"]],
                        "Instrumento local": [""] * len(draft["positions"]),
                    }
                ),
                disabled=["Documento"],
                hide_index=True,
                key=prefix + draft["sha256"][:10] + "pdfmap",
            )
            checked = st.checkbox(
                "Confirmé la cuenta, la moneda MXN y las correspondencias del PDF", key=prefix + "pdfchecked"
            )
            accepted = st.checkbox(
                "Revisé las diferencias impresas y acepto conservarlas como advertencias",
                key=prefix + "pdfaccepted",
            )
            if st.button("Confirmar e importar PDF", disabled=not checked):
                holdings_raw = confirm_statement(
                    draft,
                    contract_confirmed=checked,
                    currency_confirmed=checked,
                    differences_accepted=accepted,
                    mapping=dict(zip(mapping["Documento"], mapping["Instrumento local"], strict=True)),
                )
                flow["files"].update(holdings=holdings_raw, source_pdf=raw)
                flow["files"].pop("source_xlsx", None)
                flow["import_review"] = {
                    key: draft[key] for key in ("sha256", "end", "positions", "cash", "warnings", "checks")
                }
                flow["defaults"]["outside_cash"] = float(draft["cash"])
                st.session_state[prefix + "cash"] = float(draft["cash"])
                st.success(
                    "Posiciones importadas con procedencia. Los movimientos requieren revisión separada."
                )
    else:
        uploaded = st.file_uploader(
            "Posiciones: FechaCorte,Instrumento,ValorMXN", type=["csv"], key=prefix + "holdings"
        )
        if uploaded:
            flow["files"]["holdings"] = uploaded.getvalue()
            flow["files"].pop("source_xlsx", None)
            flow["files"].pop("source_pdf", None)
            flow["import_review"] = None
    if not flow["files"].get("holdings"):
        st.info("Importa la cartera o abre la demostración ficticia para continuar.")
        return None
    raw = flow["files"]["holdings"]
    if len(raw) > 2_000_000:
        raise PortfolioError("La cartera supera 2 MB.")
    try:
        frame = pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False)
        assets = tuple(normalize_tickers(frame["Instrumento"].tolist()))
    except (ValueError, KeyError, UnicodeError, pd.errors.ParserError):
        raise PortfolioError("La cartera CSV no tiene el formato requerido.") from None
    holdings = read_current_holdings_csv(raw, assets)
    st.dataframe(
        pd.DataFrame(
            {
                "Instrumento": assets,
                "Valuación MXN": holdings.values.to_numpy(),
                "Peso": holdings.weights.to_numpy(),
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={"Peso": st.column_config.NumberColumn(format="percent")},
    )
    st.caption(
        f"Corte {holdings.as_of.date()} · {holdings.total_value:,.2f} MXN en posiciones · "
        f"{len(assets)} instrumentos"
    )
    return holdings


def _inputs(flow, prefix):
    with st.expander("Precios y procedencia", expanded=not bool(flow["files"].get("prices"))):
        st.caption(
            "Cierres locales ajustados en MXN: Fecha y una columna por instrumento. "
            "Conserva fuente y derechos."
        )
        for name, label in (
            ("prices", "Precios ajustados MXN CSV"),
            ("rights", "Manifiesto de derechos CSV"),
            ("identity", "Identidad local e ISIN CSV · opcional"),
        ):
            uploaded = st.file_uploader(label, type=["csv"], key=prefix + name)
            if uploaded:
                flow["files"][name] = uploaded.getvalue()
            if name in flow["files"]:
                st.caption(f"{label}: cargado · SHA-256 {sha256(flow['files'][name]).hexdigest()[:12]}")
        st.caption("Las plantillas de derechos e identidad están disponibles en Análisis avanzado.")
        with st.form(prefix + "source_form"):
            st.write("**Declarar procedencia sin preparar un CSV**")
            source = st.text_input("Proveedor o fuente de precios", max_chars=150)
            product = st.text_input("Producto o serie de datos", max_chars=150)
            markets = st.text_input("Mercados cubiertos", "BMV / SIC", max_chars=150)
            reviewed = st.date_input(
                "Fecha de comprobación de derechos", date.today(), max_value=date.today()
            )
            expires = st.date_input("Vigencia hasta", date.today())
            convention = st.text_input("Horario y zona del cierre", max_chars=150)
            reference = st.text_input("Referencia del permiso o contrato", max_chars=300)
            scope = st.selectbox(
                "Uso permitido comprobado",
                ["INVESTIGACION_INTERNA", "ENTREGABLES_DERIVADOS", "REDISTRIBUCION_DATOS"],
            )
            checked = st.checkbox(
                "Comprobé permiso de uso y que los cierres están ajustados y expresados en MXN"
            )
            if st.form_submit_button("Guardar procedencia revisada"):
                if not checked:
                    raise PortfolioError(
                        "Comprueba derechos, ajuste y moneda antes de guardar la procedencia."
                    )
                contents = (
                    pd.DataFrame(
                        [
                            [
                                source,
                                product,
                                markets,
                                reviewed.isoformat(),
                                expires.isoformat(),
                                "CONFIRMADO",
                                scope,
                                "AJUSTADO",
                                convention,
                                reference,
                            ]
                        ],
                        columns=RIGHTS_COLUMNS,
                    )
                    .to_csv(index=False)
                    .encode("utf-8-sig")
                )
                read_data_rights_csv(contents)
                flow["files"]["rights"] = contents
                st.success("Procedencia guardada con la declaración revisada.")
    with st.expander("Exposición: clasificación y componentes de fondos"):
        st.caption(
            "Clasifica sólo lo que hayas comprobado. La moneda económica puede diferir de la cotización."
        )
        assets = flow["defaults"]["assets"]
        fields = ("Tipo", "Emisor", "EmisorID", "Sector", "Pais", "Moneda", "Fecha", "Fuente")
        frame = pd.DataFrame(
            [
                {
                    "Instrumento": asset,
                    **{
                        field: flow["metadata"]
                        .get(asset, {})
                        .get(field, "Sin clasificar" if field == "Tipo" else "")
                        for field in fields
                    },
                }
                for asset in assets
            ]
        )
        edited = st.data_editor(
            frame,
            disabled=["Instrumento"],
            hide_index=True,
            key=prefix + analysis_key(assets)[:10] + "metadata",
            column_config={"Tipo": st.column_config.SelectboxColumn(options=ASSET_KINDS, required=True)},
        )
        flow["metadata"] = {
            row["Instrumento"]: {field: row[field] for field in fields}
            for row in edited.to_dict(orient="records")
        }
        uploaded = st.file_uploader(
            "Componentes fechados CSV · pesos de 0 a 1", type=["csv"], key=prefix + "components"
        )
        if uploaded:
            flow["files"]["components"] = uploaded.getvalue()
        st.download_button(
            "Plantilla de componentes",
            (",".join(COMPONENT_COLUMNS) + "\n").encode(),
            "plantilla_componentes.csv",
            "text/csv",
            on_click="ignore",
        )


def _settings(flow, holdings, profile, prefix):
    defaults = flow["defaults"]
    defaults.update(as_of=holdings.as_of.date().isoformat(), assets=tuple(holdings.values.index))
    base = AccountSettings(
        as_of=defaults["as_of"],
        history_start=date(max(2000, holdings.as_of.year - 3), 1, 1).isoformat(),
        assets=defaults["assets"],
    )
    base = replace(base, **{key: value for key, value in defaults.items() if key in asdict(base)})
    with st.expander("Supuestos del análisis", expanded=True):
        start = st.date_input(
            "Historia desde",
            date.fromisoformat(base.history_start),
            max_value=holdings.as_of.date(),
            key=prefix + "start",
        )
        method = st.selectbox(
            "Estimador para esta cuenta",
            list(METHOD_LABELS),
            index=list(METHOD_LABELS).index(base.covariance_method),
            format_func=METHOD_LABELS.get,
            key=prefix + "method",
        )
        rate = (
            st.number_input(
                "Tasa libre de riesgo MXN · % anual",
                value=base.risk_free_rate * 100,
                min_value=-5.0,
                max_value=50.0,
                key=prefix + "rf",
            )
            / 100
        )
        cap = (
            st.slider(
                "Tope de las propuestas · % por activo",
                1,
                100,
                int(base.max_weight * 100),
                key=prefix + "cap",
            )
            / 100
        )
        fraction = (
            st.slider(
                "Acercamiento parcial hacia mínima volatilidad · %",
                5,
                95,
                int(base.partial_fraction * 100),
                key=prefix + "partial",
            )
            / 100
        )
        references = ["Conservar", "Cambio parcial", "Mínima volatilidad", "Máximo Sharpe", "Pesos iguales"]
        tracking = st.selectbox(
            "Referencia declarada para seguimiento",
            references,
            index=references.index(base.tracking_reference),
            key=prefix + "reference",
        )
        tolerance = (
            st.number_input(
                "Tolerancia de desvío · puntos porcentuales",
                0.0,
                100.0,
                float(base.drift_tolerance * 100),
                key=prefix + "drift",
            )
            / 100
        )
        st.caption(
            "La referencia permite comparar el próximo corte; no aprueba una recomendación u operación."
        )
        cash = st.number_input(
            "Efectivo fuera de las posiciones · MXN",
            min_value=0.0,
            value=float(base.outside_cash),
            key=prefix + "cash",
        )
        objective = st.text_input(
            "Objetivo de este análisis",
            value=base.objective or (profile or {}).get("objective", ""),
            max_chars=500,
            key=prefix + "objective",
        )
        if profile:
            st.caption(
                f"Perfil: {profile['horizon_months']} meses · liquidez "
                f"{profile['liquidity_mxn']:,.2f} MXN · capacidad de pérdida "
                f"{profile['loss_capacity_pct']:.1f}% · tolerancia {profile['loss_tolerance_pct']:.1f}%"
            )
            if profile["horizon_months"] > 120:
                st.info(
                    "El perfil supera 120 meses. La simulación actual admite hasta 120; confirma un"
                    " horizonte dentro de ese alcance."
                )
            if cash < profile["liquidity_mxn"]:
                st.warning(
                    "El efectivo declarado es inferior a la necesidad de liquidez del perfil; "
                    "requiere revisión."
                )
    with st.expander("Costos del cambio y mantenimiento"):
        confirmed = st.checkbox(
            "Confirmé los supuestos de costos y su fuente",
            value=base.costs_confirmed,
            key=prefix + "costknown",
        )
        commission = st.number_input(
            "Comisión por compra/venta · pb",
            0.0,
            1000.0,
            float(base.commission_bps),
            key=prefix + "commission",
        )
        market = st.number_input(
            "Costo de mercado supuesto · pb", 0.0, 500.0, float(base.market_cost_bps), key=prefix + "market"
        )
        vat = (
            st.number_input("IVA sobre comisión · %", 0.0, 100.0, base.vat_rate * 100, key=prefix + "vat")
            / 100
        )
        minimum = st.number_input(
            "Comisión mínima por orden · MXN",
            min_value=0.0,
            value=float(base.minimum_commission),
            key=prefix + "minimum",
        )
        fixed = st.number_input(
            "Cargo fijo anual · MXN", min_value=0.0, value=float(base.annual_fixed_cost), key=prefix + "fixed"
        )
        management = (
            st.number_input(
                "Costo anual proporcional · %",
                0.0,
                20.0,
                base.annual_management_rate * 100,
                key=prefix + "management",
            )
            / 100
        )
        source = st.text_input("Fuente de costos", base.cost_source, max_chars=300, key=prefix + "costsource")
        cost_date = st.date_input(
            "Fecha de revisión de costos",
            date.fromisoformat(base.cost_date) if base.cost_date else date.today(),
            max_value=date.today(),
            key=prefix + "costdate",
        )
        st.caption(
            "Sin confirmación, los costos se muestran pendientes. El cambio se financia con"
            " el efectivo externo declarado."
        )
    with st.expander("Meta y flujos", expanded=base.goal_amount > 0):
        goal = st.number_input(
            "Monto objetivo · MXN", min_value=0.0, value=float(base.goal_amount), key=prefix + "goal"
        )
        months = st.number_input(
            "Horizonte de la meta · meses",
            1,
            120,
            int(base.goal_months if base.goal_amount or not profile else min(120, profile["horizon_months"])),
            key=prefix + "months",
        )
        real = st.checkbox("Meta en pesos de hoy", value=base.goal_real, key=prefix + "real")
        inflation = (
            st.number_input(
                "Inflación anual supuesta · %",
                -49.0,
                100.0,
                base.inflation_rate * 100,
                key=prefix + "inflation",
            )
            / 100
        )
        contribution = st.number_input(
            "Aportación mensual · MXN",
            min_value=0.0,
            value=float(base.monthly_contribution),
            key=prefix + "contribution",
        )
        withdrawal = st.number_input(
            "Retiro mensual · MXN",
            min_value=0.0,
            value=float(base.monthly_withdrawal),
            key=prefix + "withdrawal",
        )
        sim_method = st.selectbox(
            "Método de trayectorias",
            ["bootstrap_blocks", "lognormal"],
            index=0 if base.simulation_method == "bootstrap_blocks" else 1,
            format_func=lambda key: {
                "bootstrap_blocks": "Histórico por bloques",
                "lognormal": "Lognormal correlacionado",
            }[key],
            key=prefix + "simmethod",
        )
        paths = st.number_input("Trayectorias", 100, 2000, int(base.paths), step=100, key=prefix + "paths")
        seed = st.number_input("Semilla de la meta", 0, 2**32 - 1, int(base.seed), key=prefix + "seed")
        st.caption(
            "La meta incluye posiciones y efectivo externo, sin rendimiento del efectivo. "
            "Aportaciones o retiros al cierre mensual; "
            "sin rebalanceo. El cargo porcentual se aplica sólo a posiciones; "
            "se descuentan costos iniciales confirmados, cargo anual "
            "proporcional y fijo mensual. "
            "No incluye impuestos ni cargos por operaciones futuras. La frecuencia simulada"
            " no garantiza el resultado."
        )
    return replace(
        base,
        history_start=start.isoformat(),
        covariance_method=method,
        risk_free_rate=rate,
        max_weight=cap,
        partial_fraction=fraction,
        outside_cash=cash,
        tracking_reference=tracking,
        drift_tolerance=tolerance,
        objective=objective,
        costs_confirmed=confirmed,
        commission_bps=commission,
        market_cost_bps=market,
        vat_rate=vat,
        minimum_commission=minimum,
        annual_fixed_cost=fixed,
        annual_management_rate=management,
        cost_source=source,
        cost_date=cost_date.isoformat(),
        goal_amount=goal,
        goal_months=months,
        goal_real=real,
        inflation_rate=inflation,
        monthly_contribution=contribution,
        monthly_withdrawal=withdrawal,
        simulation_method=sim_method,
        paths=paths,
        seed=seed,
    )


def _comparison_view(frame):
    formats = {column: "{:,.2f}" for column in frame.columns if column.endswith("MXN")}
    formats.update(
        {
            column: "{:.2%}"
            for column in ("Media histórica anualizada", "Volatilidad anualizada", "Rotación")
            if column in frame
        }
    )
    formats.update(
        {
            column: lambda value: "Sí" if value else "No"
            for column in ("Financiable con efectivo externo", "Cumple tope por activo")
            if column in frame
        }
    )
    display = frame.copy()
    for column in display:
        if display[column].isna().any():
            formatter = formats.pop(column, None)
            display[column] = [
                "Pendiente"
                if pd.isna(value)
                else (
                    formatter(value)
                    if callable(formatter)
                    else formatter.format(value)
                    if formatter
                    else str(value)
                )
                for value in display[column]
            ]
    return display.style.format(formats, na_rep="Pendiente")


def _results(flow, store, principal, state, account):
    completed = flow["completed"]
    if completed is None:
        return
    result, settings = completed["result"], completed["settings"]
    st.subheader("2. Comparar y revisar")
    st.caption(
        f"Ejecución {completed['run_id'][:12]} · corte {settings.as_of} · "
        f"{result['model'].moments.description}"
    )
    st.write(
        f"**{result['holdings'].total_value:,.2f} MXN analizados** · "
        f"efectivo externo {settings.outside_cash:,.2f} MXN"
    )
    st.caption(
        "Medias y riesgos describen la muestra. Cambiar una cartera no garantiza mejorar su resultado futuro."
    )
    st.write(f"**{len(result['pending'])} controles pendientes de revisión**")
    with st.expander("Ver evidencia y pendientes"):
        for pending in result["pending"]:
            st.write("• " + pending)
    if not settings.costs_confirmed:
        st.caption("Tarifario pendiente: costos desconocidos y metas brutas quedan identificados.")
    tabs = st.tabs(
        ["Alternativas y costos", "Exposición", "Meta", "Cortes y archivo"],
        key="account_result_tabs_" + completed["run_id"],
    )
    with tabs[0]:
        st.dataframe(
            _comparison_view(result["comparison"]),
            hide_index=True,
            width="stretch",
        )
        selected = st.selectbox(
            "Alternativa que deseas revisar",
            [item.name for item in result["alternatives"]],
            index=2,
            key="account_selected_" + completed["run_id"],
        )
        alternative = next(item for item in result["alternatives"] if item.name == selected)
        st.dataframe(
            pd.DataFrame(
                {
                    "Instrumento": settings.assets,
                    "Peso actual": result["holdings"].weights.to_numpy(),
                    "Peso de la alternativa": alternative.metrics.weights,
                }
            ).style.format({"Peso actual": "{:.2%}", "Peso de la alternativa": "{:.2%}"}),
            hide_index=True,
            width="stretch",
        )
        estimate = next((item for item in result["costs"] if item.alternative_name == selected), None)
        if estimate:
            st.dataframe(estimate.detail, hide_index=True, width="stretch")
        st.caption(
            "Las órdenes son importes teóricos. No aplican lotes, redondeo de títulos, "
            "impuestos ni validación de ejecución. "
            "Conservar evita transacciones; puede tener costos de mantenimiento. El cambio "
            "parcial puede conservar concentraciones previas."
        )
    with tabs[1]:
        exposure = result["exposure"]
        st.write(f"**Cobertura de exposición: {exposure['coverage']:.1%}** del capital analizado")
        st.caption(
            f"Emisor con ID estable: {exposure['identity_coverage']:.1%} · "
            f"clasificación con antigüedad máxima de 90 días: {exposure['fresh_coverage_90_days']:.1%}"
        )
        dimension = st.selectbox("Agrupar exposición", ["Emisor", "Sector", "Pais", "Moneda"])
        st.dataframe(
            exposure["aggregates"][dimension].rename("Peso de cartera").reset_index(),
            hide_index=True,
            width="stretch",
        )
        st.write("**Emisores presentes a través de varios instrumentos**")
        st.dataframe(exposure["overlap"].reset_index(), hide_index=True, width="stretch")
        with st.expander("Componentes y procedencia"):
            st.dataframe(exposure["detail"], hide_index=True, width="stretch")
    with tabs[2]:
        if result["goals"].empty:
            st.info("Define un monto objetivo en Meta y flujos y vuelve a analizar.")
        else:
            st.caption(
                f"Meta {settings.goal_amount:,.2f} MXN {'de hoy' if settings.goal_real else 'nominales'} · "
                f"{settings.goal_months} meses · {settings.paths} trayectorias · semilla {settings.seed}"
            )
            goal_formats = {
                column: "{:.1%}" if column.startswith("Probabilidad") else "{:,.2f}"
                for column in result["goals"].columns
                if column != "Alternativa"
            }
            st.dataframe(
                result["goals"].style.format(goal_formats, na_rep="No simulada"),
                hide_index=True,
                width="stretch",
            )
            if result["simulations"]:
                choice = st.selectbox("Trayectoria de la alternativa", list(result["simulations"]))
                bands = result["simulations"][choice].bands().set_index("Mes")
                bands = bands.drop(columns=["Capital aportado"])
                if settings.goal_real:
                    bands = bands.div((1 + settings.inflation_rate) ** (bands.index.to_numpy() / 12), axis=0)
                bands["Meta"] = settings.goal_amount
                st.caption(
                    "Trayectorias en pesos de hoy."
                    if settings.goal_real
                    else "Trayectorias en pesos nominales."
                )
                st.line_chart(
                    bands,
                    color=["#a3a3a3", "#1d5fbf", "#737373", "#141414"],
                )
            st.caption(
                "Una alternativa sin efectivo suficiente para sus costos queda sin simulación. "
                "Los supuestos de flujos y tarifas "
                "se mantienen iguales entre alternativas; el cargo fijo se distribuye mensualmente."
            )
    with tabs[3]:
        st.caption("Genera el PDF antes de descargar o guardar el paquete para incluirlo.")
        if st.button("Generar PDF de esta ejecución"):
            completed["pdf"] = account_pdf(result, settings, run_id=completed["run_id"], selected=selected)
        manifest, bundle = make_run_bundle(
            completed["files"],
            settings,
            completed["metadata"],
            result,
            case_id=state["id"] if state and account else None,
            account_id=account,
            profile=completed["profile"],
            run_id=completed["run_id"],
            import_review=completed["import_review"],
            pdf=completed.get("pdf"),
        )
        if store and state and account and principal.role in {"ADMIN", "ANALYST"}:
            saved = any(is_run(item["name"], completed["run_id"]) for item in state.get("artifacts", []))
            if st.button("Guardar ejecución y sus insumos cifrados", disabled=saved):
                store.attach(
                    principal,
                    state["id"],
                    state["revision"],
                    run_name(settings, completed["run_id"]),
                    bundle,
                    account_id=account,
                )
                st.success("Ejecución guardada. La nueva versión requiere sus revisiones correspondientes.")
                st.rerun()
            if saved:
                st.caption(
                    "Esta ejecución ya está guardada. Recalcular con otros supuestos crea una "
                    "ejecución nueva."
                )
            earlier = run_options(state, account, excluding=completed["run_id"])
            if earlier:
                older = st.selectbox("Corte guardado para comparar", list(earlier), format_func=earlier.get)
                if st.button("Comparar cortes"):
                    _, raw = store.artifact(principal, state["id"], older)
                    before, _, _ = read_run_bundle(raw, case_id=state["id"], account_id=account)
                    st.dataframe(compare_account_cuts(before, manifest), hide_index=True, width="stretch")
                    st.caption(
                        "Cambios de valuación y peso; no son rendimiento realizado. Aportaciones, "
                        "retiros y operaciones requieren conciliación."
                    )
        st.download_button(
            "Descargar paquete para retomar",
            bundle,
            run_name(settings, completed["run_id"]),
            "application/zip",
            on_click="ignore",
        )
        st.caption(
            "El paquete descargado contiene los insumos y debe custodiarse como el "
            "documento original. En Expedientes se conserva cifrado."
        )
        if completed.get("pdf"):
            st.download_button(
                "Descargar comparativo de cuenta PDF",
                completed["pdf"],
                f"comparativo_{completed['run_id']}.pdf",
                "application/pdf",
                on_click="ignore",
            )


def render_account_workflow():
    st.title("Análisis por cuenta")
    st.caption(
        "Importa o retoma una cartera MXN, compara alternativas y conserva la evidencia de la revisión."
    )
    try:
        store, principal, state, account = _context()
        context = (
            str(store.path) if store else None,
            principal.actor if principal else None,
            state["id"] if state else None,
            account,
        )
        if st.session_state.get("_account_flow", {}).get("context") != context:
            st.session_state["_account_flow"] = _new_state(context)
        flow = st.session_state["_account_flow"]
        if store and state and account and principal.role in {"ADMIN", "ANALYST"}:
            if "draft_version" not in flow:
                drafts = store.working_records(principal, state["id"], account, "draft")
                draft = next((item for item in drafts if item["name"] == "analysis"), None)
                flow["draft_version"] = draft["version"] if draft else 0
                flow["draft_candidate"] = draft
            candidate = flow.get("draft_candidate")
            if candidate and not flow["files"]:
                st.caption(f"Borrador cifrado disponible · guardado {candidate['updated'][:19]} UTC")
                if st.button("Recuperar borrador de esta cuenta"):
                    flow.update(restore_draft(candidate["data"]))
                    flow.pop("draft_candidate", None)
                    st.rerun()
        _archive_picker(flow, store, principal, state, account)
        if st.button("Abrir demostración ficticia"):
            files, metadata, defaults = demo_account()
            flow.update(
                files=files,
                metadata=metadata,
                defaults=defaults,
                token=uuid4().hex,
                demo=True,
                completed=None,
                import_review=None,
            )
            flow.pop("loaded_manifest", None)
            flow.pop("archived_pdf", None)
            st.rerun()
        if flow["demo"]:
            st.info(
                "Demostración ficticia: instrumentos SIM y series sintéticas; no son "
                "cotizaciones ni posiciones reales."
            )
        with st.expander("Abrir un paquete descargado"):
            package = st.file_uploader("Paquete de ejecución ZIP", type=["zip"], key="account_package")
            if package and st.button("Retomar paquete"):
                manifest, files, settings = read_run_bundle(
                    package.getvalue(), case_id=state["id"] if state and account else None, account_id=account
                )
                if not state and manifest["case_id"] is not None:
                    raise PortfolioError(
                        "Abre el expediente y la cuenta correspondientes antes de retomar este paquete."
                    )
                _load(flow, manifest, files, settings, package.getvalue())
                st.rerun()
        if flow.get("loaded_manifest"):
            loaded = flow["loaded_manifest"]
            st.caption(f"Recuperado: {loaded['run_id'][:12]}. Recalcular creará otra ejecución.")
            with st.expander("Resumen de la ejecución recuperada"):
                st.dataframe(
                    _comparison_view(pd.DataFrame(loaded["summary"].get("comparison", []))),
                    hide_index=True,
                    width="stretch",
                )
                st.caption("Resultados archivados, sin recálculo en esta apertura.")
                if flow.get("archived_pdf"):
                    st.download_button(
                        "Descargar PDF archivado",
                        flow["archived_pdf"],
                        f"comparativo_{loaded['run_id']}.pdf",
                        "application/pdf",
                        on_click="ignore",
                    )
            if loaded["code_sha256"] != code_fingerprint():
                st.info(
                    "La versión del motor cambió. Se conserva el análisis anterior; el nuevo "
                    "cálculo usará la versión actual."
                )
            if state and loaded.get("profile") != state.get("profile"):
                st.info("El perfil vigente difiere del guardado. Revisa los supuestos antes de recalcular.")
        prefix = "account_" + flow["token"] + "_"
        preparation_id = flow["completed"]["run_id"] if flow["completed"] else flow["token"]
        with st.expander(
            "Preparación y supuestos de la cuenta",
            expanded=flow["completed"] is None,
            key="account_preparation_" + preparation_id,
        ):
            holdings = _import_positions(flow, prefix)
            if holdings is None:
                return
            flow["defaults"].update(assets=tuple(holdings.values.index))
            _inputs(flow, prefix)
            profile = state.get("profile") if state else None
            settings = _settings(flow, holdings, profile, prefix)
            flow["defaults"].update(asdict(settings))
            if store and state and account and principal.role in {"ADMIN", "ANALYST"}:
                payload = draft_payload(flow)
                digest = analysis_key(payload)
                if flow.get("draft_digest") != digest:
                    try:
                        flow["draft_version"] = store.save_working(
                            principal,
                            state["id"],
                            account,
                            "draft",
                            "analysis",
                            payload,
                            expected_version=flow["draft_version"],
                        )
                        flow["draft_digest"] = digest
                    except WorkspaceError as exc:
                        st.warning(str(exc))
                if flow.get("draft_digest") == digest:
                    st.caption("Borrador guardado automáticamente y cifrado para esta cuenta.")
            ready = {"holdings", "prices", "rights"}.issubset(flow["files"])
            confirmed = st.checkbox(
                "Confirmé que posiciones, fechas y precios corresponden a esta cuenta y están en MXN",
                key=prefix + "analysis_confirmation",
            )
            if st.button("Analizar cuenta", type="primary", disabled=not ready or not confirmed):
                with st.spinner("Calculando alternativas y comprobando los insumos…"):
                    result = run_account_analysis(
                        flow["files"], settings, flow["metadata"], session=st.session_state
                    )
                flow["completed"] = {
                    "result": result,
                    "settings": settings,
                    "files": dict(flow["files"]),
                    "metadata": {key: dict(value) for key, value in flow["metadata"].items()},
                    "run_id": uuid4().hex,
                    "profile": profile,
                    "import_review": flow["import_review"],
                }
                st.rerun()
            if not ready:
                st.info("Faltan precios ajustados o su manifiesto de derechos para ejecutar el análisis.")
            if flow["completed"] and analysis_key(
                asdict(settings), flow["files"], flow["metadata"]
            ) != analysis_key(
                asdict(flow["completed"]["settings"]),
                flow["completed"]["files"],
                flow["completed"]["metadata"],
            ):
                st.info(
                    "Hay cambios sin calcular. Los resultados y descargas siguientes corresponden a"
                    " la ejecución anterior."
                )
        _results(flow, store, principal, state, account)
    except (PortfolioError, WorkspaceError, ValueError) as exc:
        st.error(str(exc))
